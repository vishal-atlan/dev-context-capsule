"""Read open files from VS Code via the capsule-open-files extension.

The extension writes ~/.capsule/vscode-open-files.json on every tab change.
This reader picks it up and filters to files inside the current repo.

If the file doesn't exist (extension not installed / VS Code not open),
returns an empty list silently.
"""

import json
from pathlib import Path

_OPEN_FILES_PATH = Path.home() / ".capsule" / "vscode-open-files.json"


def read_open_files(repo_path: str = "") -> list[str]:
    if not _OPEN_FILES_PATH.exists():
        return []
    try:
        data = json.loads(_OPEN_FILES_PATH.read_text())
        files = data.get("files", [])
        if repo_path:
            abs_repo = str(Path(repo_path).resolve())
            files = [f for f in files if f.startswith(abs_repo)]
        return files
    except Exception:
        return []
