#!/usr/bin/env python3
"""Download a public GitHub tree through raw.githubusercontent.com when git/codeload is unavailable."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

OWNER = "amu354084-ops"
REPO = "ecohush"
BRANCH = "main"
DEST = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/app")
API_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees/{BRANCH}?recursive=1"
RAW_ROOT = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/"


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ecohush-deployer"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read()


def main() -> None:
    tree = json.loads(get(API_URL).decode("utf-8"))
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree response was truncated")
    files = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]
    if not files:
        raise RuntimeError("No repository files were found")
    DEST.mkdir(parents=True, exist_ok=True)
    for relative_path in files:
        if relative_path.startswith((".env", ".git/")):
            continue
        target = DEST / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(get(RAW_ROOT + relative_path))
        print(relative_path)
    print(f"Downloaded {len(files)} repository files to {DEST}")


if __name__ == "__main__":
    main()
