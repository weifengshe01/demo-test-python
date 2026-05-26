"""
__main__.py
Entry point: python -m pr_test_agent --base <sha> --head <sha> ...
"""

import argparse
import os
import sys
from pathlib import Path

from .differ import get_changed_files, load_ignore_set, is_ignored
from .generator import generate
from .runner import run_tests
from .repairer import repair_loop
from .reporter import write_report


def parse_args():
    p = argparse.ArgumentParser(prog="pr_test_agent",
                                description="Generate, run, and auto-repair tests for a PR.")
    p.add_argument("--base", required=True, help="Base branch/SHA (e.g. origin/main).")
    p.add_argument("--head", required=True, help="Head commit SHA.")
    p.add_argument("--repo-root", default=".", help="Path to repository root.")
    p.add_argument("--output", default="generated_tests", help="Output directory.")
    p.add_argument("--test-dir", default="tests", help="Directory to write test files into.")
    p.add_argument("--max-tests", type=int, default=10)
    p.add_argument("--repair-attempts", type=int, default=3,
                   help="LLM repair attempts before blocking merge.")
    p.add_argument("--timeout", type=int, default=120, help="Pytest timeout in seconds.")
    # LLM config (can also be set via env vars)
    p.add_argument("--llm-model", default="", help="LLM model string.")
    return p.parse_args()


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    output_dir = Path(args.output)
    test_dir = repo_root / args.test_dir

    # LLM credentials from args or environment
    llm_model    = args.llm_model or os.environ.get("LLM_MODEL", "")
    llm_base_url = os.environ.get("OPENAI_BASE_URL", "")
    llm_api_key  = os.environ.get("OPENAI_API_KEY", "")

    print(f"[agent] Comparing {args.base}...{args.head}")
    changed = get_changed_files(repo_root, args.base, args.head)
    ignore  = load_ignore_set(repo_root)

    if not changed:
        print("[agent] No Python files changed — nothing to do.")
        sys.exit(0)

    results = []
    for cf in changed:
        if is_ignored(cf.path, ignore):
            print(f"[agent] Skipping ignored: {cf.path}")
            continue

        print(f"[agent] Generating tests for {cf.path}")
        test_file = generate(
            cf, test_dir, args.max_tests,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
        )

        print(f"[agent] Running {test_file}")
        result = run_tests(test_file, repo_root, timeout=args.timeout)

        if not result.passed and llm_model and llm_base_url and llm_api_key:
            result = repair_loop(
                cf, test_file, result, repo_root,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                max_attempts=args.repair_attempts,
                timeout=args.timeout,
            )

        results.append((str(cf.path), result))

    exit_code = write_report(output_dir, results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
