"""LLM client factory — fully driven by env vars, zero hardcoding.

Environment variables:
  CAPSULE_LLM_PROVIDER   — "anthropic" | "bedrock" | "litellm"
                           Auto-detected if unset: uses "anthropic" when
                           ANTHROPIC_API_KEY is present, else passthrough.
  CAPSULE_MODEL          — Model name/ID to use (overrides per-provider default).
                           bedrock default: derived from AWS_DEFAULT_REGION prefix.
                           anthropic/litellm default: claude-sonnet-4-6.

  Provider-specific:
    anthropic  → ANTHROPIC_API_KEY
    bedrock    → AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
    litellm    → CAPSULE_LITELLM_BASE_URL, CAPSULE_LITELLM_API_KEY
"""

import os


_BEDROCK_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _bedrock_model() -> str:
    if os.environ.get("CAPSULE_MODEL"):
        return os.environ["CAPSULE_MODEL"]
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    prefix = "eu" if region.startswith("eu") else "ap" if region.startswith("ap") else "us"
    return f"{prefix}.anthropic.{_BEDROCK_DEFAULT_MODEL}"


def make_client():
    """Return (client, model, provider) or (None, None, None) for passthrough mode."""
    provider = os.environ.get("CAPSULE_LLM_PROVIDER", "")

    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        else:
            return None, None, None

    if provider == "litellm":
        from openai import OpenAI
        client = OpenAI(
            base_url=os.environ.get("CAPSULE_LITELLM_BASE_URL", ""),
            api_key=os.environ.get("CAPSULE_LITELLM_API_KEY", ""),
        )
        model = os.environ.get("CAPSULE_MODEL", _DEFAULT_MODEL)

    elif provider == "bedrock":
        from anthropic import AnthropicBedrock
        client = AnthropicBedrock()
        model = _bedrock_model()

    else:  # anthropic (default)
        import anthropic
        client = anthropic.Anthropic()
        model = os.environ.get("CAPSULE_MODEL", _DEFAULT_MODEL)

    return client, model, provider


def llm_call(client, model: str, provider: str, system: str, user: str, max_tokens: int = 512) -> str:
    """Call the LLM and return the response text."""
    if provider == "litellm":
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()
    else:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text.strip()
