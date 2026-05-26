"""
repairer.py
LLM auto-repair loop: regenerate → rerun → repeat up to N times.
Returns the final RunResult (pass or exhausted).
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .differ import ChangedFile
    from .runner import RunResult

from .runner import run_tests
from .generator import regenerate_with_llm


def repair_loop(
    cf: "ChangedFile",
    test_path,
    first_result: "RunResult",
    repo_root,
    llm_model: str,
    llm_base_url: str,
    llm_api_key: str,
    max_attempts: int = 3,
    timeout: int = 120,
) -> "RunResult":
    """
    If the first run failed, try up to max_attempts LLM repairs.
    Returns the last RunResult — caller checks .passed to decide whether to block.
    """
    result = first_result
    for attempt in range(1, max_attempts + 1):
        if result.passed:
            break
        print(f"[repair] Attempt {attempt}/{max_attempts} for {cf.path}")
        repaired = regenerate_with_llm(
            cf, test_path, result.output,
            llm_model, llm_base_url, llm_api_key,
        )
        if not repaired:
            print("[repair] LLM could not produce a valid fix — stopping.")
            break
        result = run_tests(test_path, repo_root, timeout=timeout)
        if result.passed:
            print(f"[repair] Tests pass after attempt {attempt}.")
    return result
