"""
differ.py
Compares base..head and returns changed Python source files.
"""

from __future__ import annotations
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class ChangedFile:
    path: Path
    added_lines: List[str] = field(default_factory=list)
    removed_lines: List[str] = field(default_factory=list)
    raw_diff: str = ""
    full_source: str = ""


def get_changed_files(repo_root: Path, base: str, head: str) -> List[ChangedFile]:
    """Return ChangedFile records for every .py file changed between base and head."""
    names = _git(repo_root, ["diff", "--name-only", f"{base}...{head}"])
    results: List[ChangedFile] = []

    for rel in names.splitlines():
        rel = rel.strip()
        if not rel.endswith(".py"):
            continue
        p = Path(rel)
        raw = _git(repo_root, ["diff", f"{base}...{head}", "--", rel])
        added, removed = _parse_diff(raw)
        full_source = ""
        abs_path = repo_root / p
        if abs_path.exists():
            full_source = abs_path.read_text(errors="replace")
        results.append(ChangedFile(
            path=p,
            added_lines=added,
            removed_lines=removed,
            raw_diff=raw,
            full_source=full_source,
        ))
    return results


def _parse_diff(raw: str):
    added, removed = [], []
    for line in raw.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    return added, removed


def _git(repo_root: Path, args: list) -> str:
    r = subprocess.run(
        ["git"] + args,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout


def load_ignore_set(repo_root: Path) -> set:
    p = repo_root / ".pr-test-agent-ignore"
    if not p.exists():
        return set()
    patterns = set()
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.add(line)
    return patterns


def is_ignored(path: Path, patterns: set) -> bool:
    import fnmatch
    s = str(path)
    return any(fnmatch.fnmatch(s, pat) or s == pat for pat in patterns)
