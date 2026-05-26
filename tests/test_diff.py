"""
tests/test_differ.py
"""
import unittest
from pathlib import Path
from unittest.mock import patch
from pr_test_agent.differ import _parse_diff, get_changed_files, load_ignore_set, is_ignored


class TestParseDiff(unittest.TestCase):
    def test_added_lines(self):
        added, _ = _parse_diff("+new line\n")
        self.assertEqual(added, ["new line"])

    def test_removed_lines(self):
        _, removed = _parse_diff("-old line\n")
        self.assertEqual(removed, ["old line"])

    def test_ignores_headers(self):
        added, removed = _parse_diff("+++ b/f.py\n--- a/f.py\n")
        self.assertEqual(added, [])
        self.assertEqual(removed, [])

    def test_empty_diff(self):
        self.assertEqual(_parse_diff(""), ([], []))


class TestGetChangedFiles(unittest.TestCase):
    @patch("pr_test_agent.differ._git")
    def test_filters_non_python(self, mock_git):
        mock_git.side_effect = ["README.md\nfoo.ts\n"]
        result = get_changed_files(Path("."), "main", "HEAD")
        self.assertEqual(result, [])

    @patch("pr_test_agent.differ._git")
    def test_returns_python_files(self, mock_git):
        mock_git.side_effect = ["src/app.py\n", "+def foo(): pass\n"]
        result = get_changed_files(Path("."), "main", "HEAD")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path, Path("src/app.py"))


class TestIgnore(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(is_ignored(Path("src/foo.py"), {"src/foo.py"}))

    def test_glob_match(self):
        self.assertTrue(is_ignored(Path("src/internal/bar.py"), {"src/internal/*.py"}))

    def test_no_match(self):
        self.assertFalse(is_ignored(Path("src/ok.py"), {"src/bad.py"}))

    def test_empty_patterns(self):
        self.assertFalse(is_ignored(Path("anything.py"), set()))


"""
tests/test_generator.py
"""
import tempfile, re
from pr_test_agent.generator import (
    _extract_functions, _has_test_functions, _write_block,
    generate, PY_BEGIN, PY_END,
)
from pr_test_agent.differ import ChangedFile


class TestExtractFunctions(unittest.TestCase):
    def test_finds_public_function(self):
        self.assertEqual(_extract_functions(["def compute(x):\n"]), ["compute"])

    def test_skips_private(self):
        self.assertEqual(_extract_functions(["def _helper():\n"]), [])

    def test_deduplicates(self):
        self.assertEqual(_extract_functions(["def foo():\n", "def foo(x):\n"]), ["foo"])

    def test_empty(self):
        self.assertEqual(_extract_functions([]), [])


class TestHasTestFunctions(unittest.TestCase):
    def test_detects_test_def(self):
        self.assertTrue(_has_test_functions("def test_foo(): pass"))

    def test_returns_false_when_none(self):
        self.assertFalse(_has_test_functions("def helper(): pass"))


class TestWriteBlock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_file_with_markers(self):
        p = self.root / "test_foo.py"
        _write_block(p, "def test_x(): pass")
        content = p.read_text()
        self.assertIn(PY_BEGIN, content)
        self.assertIn(PY_END, content)

    def test_replaces_existing_block(self):
        p = self.root / "test_foo.py"
        _write_block(p, "def test_old(): pass")
        _write_block(p, "def test_new(): pass")
        content = p.read_text()
        self.assertIn("test_new", content)
        self.assertNotIn("test_old", content)
        self.assertEqual(content.count(PY_BEGIN), 1)

    def test_appends_when_no_existing_block(self):
        p = self.root / "test_foo.py"
        p.write_text("# hand written\n")
        _write_block(p, "def test_gen(): pass")
        content = p.read_text()
        self.assertIn("# hand written", content)
        self.assertIn("test_gen", content)


class TestGenerateDeterministic(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_test_file(self):
        cf = ChangedFile(path=Path("src/calc.py"),
                         added_lines=["def add(a, b):\n", "    return a + b\n"])
        test_dir = self.root / "tests"
        result = generate(cf, test_dir, max_tests=5)
        self.assertTrue(result.exists())

    def test_test_file_named_correctly(self):
        cf = ChangedFile(path=Path("src/calc.py"), added_lines=["def add(): pass\n"])
        test_dir = self.root / "tests"
        result = generate(cf, test_dir, max_tests=5)
        self.assertEqual(result.name, "test_calc.py")

    def test_respects_max_tests(self):
        lines = [f"def fn{i}(): pass\n" for i in range(15)]
        cf = ChangedFile(path=Path("src/m.py"), added_lines=lines)
        result = generate(cf, self.root / "tests", max_tests=3)
        count = result.read_text().count("def test_")
        self.assertLessEqual(count, 3)


"""
tests/test_runner.py
"""
from unittest.mock import patch, MagicMock
import subprocess
from pr_test_agent.runner import run_tests, RunResult


class TestRunTests(unittest.TestCase):
    @patch("pr_test_agent.runner.subprocess.run")
    def test_pass_on_returncode_0(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
        r = run_tests(Path("tests/test_x.py"), Path("."), timeout=30)
        self.assertTrue(r.passed)
        self.assertFalse(r.timed_out)

    @patch("pr_test_agent.runner.subprocess.run")
    def test_fail_on_nonzero(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="FAILED")
        r = run_tests(Path("tests/test_x.py"), Path("."), timeout=30)
        self.assertFalse(r.passed)

    @patch("pr_test_agent.runner.subprocess.run",
           side_effect=subprocess.TimeoutExpired("cmd", 30))
    def test_timeout_flag(self, _):
        r = run_tests(Path("tests/test_x.py"), Path("."), timeout=30)
        self.assertTrue(r.timed_out)
        self.assertFalse(r.passed)

    @patch("pr_test_agent.runner.subprocess.run")
    def test_output_captured(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="warn\n")
        r = run_tests(Path("tests/test_x.py"), Path("."), timeout=30)
        self.assertIn("ok", r.output)
        self.assertIn("warn", r.output)


"""
tests/test_reporter.py
"""
import tempfile
from pr_test_agent.reporter import write_report
from pr_test_agent.runner import RunResult


class TestWriteReport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _result(self, passed=True, timed_out=False):
        return RunResult(passed=passed, output="output", duration=1.2,
                         test_file=Path("tests/test_x.py"), timed_out=timed_out)

    def test_creates_report_file(self):
        write_report(self.out, [])
        self.assertTrue((self.out / "PR_TEST_AGENT_REPORT.md").exists())

    def test_exit_0_when_all_pass(self):
        code = write_report(self.out, [("src/x.py", self._result(passed=True))])
        self.assertEqual(code, 0)

    def test_exit_1_when_any_fail(self):
        code = write_report(self.out, [("src/x.py", self._result(passed=False))])
        self.assertEqual(code, 1)

    def test_checkmark_in_report_for_pass(self):
        write_report(self.out, [("src/x.py", self._result(passed=True))])
        content = (self.out / "PR_TEST_AGENT_REPORT.md").read_text()
        self.assertIn("✅", content)

    def test_cross_in_report_for_fail(self):
        write_report(self.out, [("src/x.py", self._result(passed=False))])
        content = (self.out / "PR_TEST_AGENT_REPORT.md").read_text()
        self.assertIn("❌", content)

    def test_timeout_shown_in_report(self):
        write_report(self.out, [("src/x.py", self._result(passed=False, timed_out=True))])
        content = (self.out / "PR_TEST_AGENT_REPORT.md").read_text()
        self.assertIn("TIMEOUT", content)

    def test_merge_allowed_message_on_all_pass(self):
        write_report(self.out, [("src/x.py", self._result(passed=True))])
        content = (self.out / "PR_TEST_AGENT_REPORT.md").read_text()
        self.assertIn("Merge allowed", content)

    def test_merge_blocked_message_on_fail(self):
        write_report(self.out, [("src/x.py", self._result(passed=False))])
        content = (self.out / "PR_TEST_AGENT_REPORT.md").read_text()
        self.assertIn("Merge blocked", content)


if __name__ == "__main__":
    unittest.main()
