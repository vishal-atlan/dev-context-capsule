"""Tests for ticket ID parsing from branch names (provider-agnostic)."""

from capsule.mcp_tools.ticket_reader import parse_ticket_id


def test_extracts_lowercase_id():
    assert parse_ticket_id("dev/proj-123-some-feature") == "PROJ-123"


def test_extracts_uppercase_id():
    assert parse_ticket_id("fix/PROJ-278-auth-bug") == "PROJ-278"


def test_extracts_short_prefix():
    assert parse_ticket_id("feat/ENG-1005-granular-perms") == "ENG-1005"


def test_no_ticket_in_branch():
    assert parse_ticket_id("feat/delete-user-ttl-refresh") is None


def test_skips_non_feature_branches():
    for branch in ("main", "master", "develop", "staging", "beta", "release"):
        assert parse_ticket_id(branch) is None, f"Expected None for {branch}"


def test_ticket_in_middle_of_branch():
    assert parse_ticket_id("user/fix-ENG-99-auth-bug") == "ENG-99"
