"""
reporter.py
Writes PR_TEST_AGENT_REPORT.md and returns the final exit code.
Exit 0  → all tests pass  (merge allowed)
Exit 1  → any test still failing after repair (merge blocked)
"""

from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import RunResult


def write_report(
    output_dir: Path,
    results: List[Tuple[str, "RunResult"]],   # [(src_path, RunResult), ...]
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# PR Test Agent Report\n"]

    all_passed = True
    for src, r in results:
        icon = "✅" if r.passed else "❌"
        status = "PASS" if r.passed else ("TIMEOUT" if r.timed_out else "FAIL")
        lines.append(f"## {icon} `{src}` — {status} ({r.duration:.1f}s)\n")
        lines.append(f"**Test file:** `{r.test_file}`\n")
        if not r.passed:
            all_passed = False
            lines.append(f"<details><summary>Output</summary>\n\n```\n{r.output[:3000]}\n```\n\n</details>\n")

    lines.append("\n---\n")
    if all_passed:
        lines.append("**Result: ✅ All generated tests pass. Merge allowed.**\n")
    else:
        lines.append("**Result: ❌ Some tests still fail after LLM repair. Merge blocked.**\n")

    report = output_dir / "PR_TEST_AGENT_REPORT.md"
    report.write_text("\n".join(lines))
    print(f"[reporter] Report → {report}")
    return 0 if all_passed else 1
