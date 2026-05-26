"""
runner.py
Runs pytest against a generated test file and captures results.
"""

from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    passed: bool
    output: str
    duration: float
    test_file: Path
    timed_out: bool = False


def run_tests(test_file: Path, repo_root: Path, timeout: int = 120) -> RunResult:
    """Run pytest on a single test file. Returns a RunResult."""
    start = time.monotonic()
    cmd = ["python", "-m", "pytest", str(test_file), "-v", "--tb=short", "--no-header"]
    try:
        r = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        return RunResult(
            passed=r.returncode == 0,
            output=r.stdout + r.stderr,
            duration=elapsed,
            test_file=test_file,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return RunResult(
            passed=False,
            output=f"[timeout after {timeout}s]",
            duration=elapsed,
            test_file=test_file,
            timed_out=True,
        )
