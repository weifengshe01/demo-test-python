"""
generator.py
Generates a pytest test file for a changed Python source file.
Uses LLM if available, otherwise produces deterministic stubs.
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .differ import ChangedFile

PY_BEGIN = "# BEGIN PR TEST AGENT GENERATED TESTS"
PY_END   = "# END PR TEST AGENT GENERATED TESTS"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(cf: "ChangedFile", test_dir: Path, max_tests: int,
             llm_model: str = "", llm_base_url: str = "", llm_api_key: str = "") -> Path:
    """
    Generate (or regenerate) a test file for the changed file.
    Returns the path to the written test file.
    """
    test_path = _test_path(cf.path, test_dir)
    proposal = ""

    if llm_model and llm_base_url and llm_api_key:
        proposal = _llm_generate(cf, test_path, max_tests, llm_model, llm_base_url, llm_api_key)

    if not proposal or not _has_test_functions(proposal):
        proposal = _deterministic_generate(cf, max_tests)

    _write_block(test_path, proposal)
    return test_path


def regenerate_with_llm(cf: "ChangedFile", test_path: Path, failure_output: str,
                        llm_model: str, llm_base_url: str, llm_api_key: str) -> bool:
    """
    Ask the LLM to fix a failing test file.
    Returns True if a valid replacement was written.
    """
    current = test_path.read_text() if test_path.exists() else ""
    fixed = _llm_repair(cf, current, failure_output, llm_model, llm_base_url, llm_api_key)
    if fixed and _has_test_functions(fixed):
        _write_block(test_path, fixed)
        return True
    return False


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

def _llm_generate(cf, test_path: Path, max_tests: int,
                  model: str, base_url: str, api_key: str) -> str:
    existing = test_path.read_text() if test_path.exists() else ""
    prompt = (
        f"Generate up to {max_tests} pytest tests for the Python source file below.\n"
        f"Focus only on the changed lines. Return a complete, runnable test file.\n"
        f"Use pytest style (functions starting with test_). No placeholders.\n\n"
        f"### Changed lines (added)\n```python\n{''.join(cf.added_lines[:80])}\n```\n\n"
        f"### Full source\n```python\n{cf.full_source[:3000]}\n```\n"
        + (f"\n### Existing tests (append/update, don't duplicate)\n```python\n{existing[:2000]}\n```\n"
           if existing else "")
    )
    return _call_llm(prompt, model, base_url, api_key)


def _llm_repair(cf, current_tests: str, failure_output: str,
                model: str, base_url: str, api_key: str) -> str:
    prompt = (
        f"The following pytest test file failed. Fix it so all tests pass.\n"
        f"Return only the corrected, complete test file.\n\n"
        f"### Source under test\n```python\n{cf.full_source[:2000]}\n```\n\n"
        f"### Failing test file\n```python\n{current_tests}\n```\n\n"
        f"### Failure output\n```\n{failure_output[:1500]}\n```\n"
    )
    return _call_llm(prompt, model, base_url, api_key)


def _call_llm(prompt: str, model: str, base_url: str, api_key: str) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("[llm] openai package not installed.")
        return ""
    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = resp.choices[0].message.content or ""
        return _extract_code_block(content) or content
    except Exception as e:
        print(f"[llm] Call failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

def _deterministic_generate(cf: "ChangedFile", max_tests: int) -> str:
    module = cf.path.stem
    functions = _extract_functions(cf.added_lines)
    if not functions:
        return ""
    import_hint = _import_path(cf.path)
    lines = [
        "import pytest",
        f"# from {import_hint} import {', '.join(functions[:3])}",
        "",
        "",
    ]
    for fn in functions[:max_tests]:
        lines += [
            f"def test_{fn}_basic():",
            f"    # TODO: import and call {fn}(), then assert expected output",
            f"    raise NotImplementedError('test_{fn}_basic not implemented')",
            "",
        ]
    return "\n".join(lines)


def _extract_functions(added_lines):
    fn_re = re.compile(r"^\s*def\s+([a-zA-Z_]\w*)\s*\(")
    seen, fns = set(), []
    for line in added_lines:
        m = fn_re.match(line)
        if m:
            name = m.group(1)
            if name not in seen and not name.startswith("_"):
                seen.add(name)
                fns.append(name)
    return fns


def _import_path(path: Path) -> str:
    return ".".join(path.with_suffix("").parts)


# ---------------------------------------------------------------------------
# File write helpers
# ---------------------------------------------------------------------------

def _test_path(src_path: Path, test_dir: Path) -> Path:
    return test_dir / f"test_{src_path.stem}.py"


def _write_block(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    block = f"{PY_BEGIN}\n{content}\n{PY_END}"
    if not path.exists():
        path.write_text(block + "\n")
        return
    existing = path.read_text()
    if PY_BEGIN in existing:
        new = re.sub(
            re.escape(PY_BEGIN) + r".*?" + re.escape(PY_END),
            block,
            existing,
            flags=re.DOTALL,
        )
        path.write_text(new)
    else:
        path.write_text(existing.rstrip() + "\n\n" + block + "\n")


def _has_test_functions(text: str) -> bool:
    return bool(re.search(r"def test_\w+", text))


def _extract_code_block(text: str) -> Optional[str]:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else None
