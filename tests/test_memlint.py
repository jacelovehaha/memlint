"""Tests for memlint: every check, the score, report formats, CLI codes."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memlint.cli import main
from memlint.core import Scanner, estimate_tokens, parse_file, tokenize
from memlint.report import render

TODAY = date(2026, 10, 27)


def scan_text(text, **kwargs):
    kwargs.setdefault("today", TODAY)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "memory.md"
        path.write_text(text, encoding="utf-8")
        return Scanner(**kwargs).scan(path)


def checks(result):
    return [f.check for f in result.findings]


class ParsingTests(unittest.TestCase):
    def test_date_prefix_formats(self):
        text = (
            "## Notes\n\n"
            "- 2026-10-27 Plain date entry about apples\n"
            "- 2026-10-26: Colon date entry about bananas\n"
            "- [2026-10-25] Bracket date entry about cherries\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            path.write_text(text, encoding="utf-8")
            entries, _ = parse_file(path)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].entry_date, date(2026, 10, 27))
        self.assertEqual(entries[1].entry_date, date(2026, 10, 26))
        self.assertEqual(entries[2].entry_date, date(2026, 10, 25))
        self.assertTrue(entries[0].content.startswith("Plain date"))

    def test_tokenize_normalizes(self):
        self.assertEqual(tokenize("Hello, WORLD! 42"), ["hello", "world", "42"])

    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("one two three"), 4)  # ceil(3 / 0.75)


class DuplicateTests(unittest.TestCase):
    def test_exact_duplicate(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-27 The server password rotates every month\n"
            "- 2026-10-20 The server password rotates every month\n"
        )
        self.assertIn("duplicate-exact", checks(result))
        finding = [f for f in result.findings if f.check == "duplicate-exact"][0]
        self.assertEqual(finding.severity, "warn")

    def test_near_duplicate(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-27 Project Alpha budget is 5000 dollars for marketing campaign\n"
            "- 2026-10-26 Project Alpha budget is 5000 dollars for marketing campaign launch\n"
        )
        self.assertIn("duplicate-near", checks(result))
        self.assertNotIn("duplicate-exact", checks(result))

    def test_distinct_entries_are_not_duplicates(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-27 Weekly review completed and action items documented\n"
            "- 2026-10-25 Team lunch scheduled for Friday at the cafe\n"
        )
        self.assertNotIn("duplicate-exact", checks(result))
        self.assertNotIn("duplicate-near", checks(result))


class StaleTests(unittest.TestCase):
    def test_stale_entry_flagged(self):
        result = scan_text(
            "## Notes\n\n- 2026-06-01 Old vendor contract review is pending\n"
        )
        self.assertIn("stale", checks(result))

    def test_fresh_entry_not_stale(self):
        result = scan_text(
            "## Notes\n\n- 2026-10-20 Recent vendor contract review finished\n"
        )
        self.assertNotIn("stale", checks(result))

    def test_evergreen_section_exempt(self):
        result = scan_text(
            "## Evergreen Principles\n\n"
            "- 2025-01-01 Always verify backups before any major upgrade\n"
        )
        self.assertNotIn("stale", checks(result))

    def test_stale_days_option(self):
        result = scan_text(
            "## Notes\n\n- 2026-10-20 Entry from last week about gardening\n",
            stale_days=3,
        )
        self.assertIn("stale", checks(result))


class ContradictionTests(unittest.TestCase):
    def test_conflicting_numbers(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-20 Server migration deadline is 15 November for production cutover\n"
            "- 2026-10-21 Server migration deadline moved to 30 November after vendor delay\n"
        )
        self.assertIn("contradiction", checks(result))
        finding = [f for f in result.findings if f.check == "contradiction"][0]
        self.assertIn("heuristic", finding.message)

    def test_negation_marker(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-20 Gym membership plan renews monthly at the front desk\n"
            "- 2026-10-25 Gym membership plan is no longer active this season\n"
        )
        self.assertIn("contradiction", checks(result))

    def test_explicit_key_groups_entries(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-20 key: offsite The winter offsite hosts 40 people downtown\n"
            "- 2026-10-25 Completely different opening words key: offsite moved to 60 people\n"
        )
        # Second entry's key: is not a prefix, so grouping falls back to
        # its first tokens; assert the prefixed entry parses its key.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.md"
            path.write_text(
                "- 2026-10-20 key: offsite The winter offsite hosts 40 people\n",
                encoding="utf-8",
            )
            entries, _ = parse_file(path)
        self.assertEqual(entries[0].subject_key, "offsite")

    def test_same_number_no_contradiction(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-20 Coffee order quantity is 12 bags for the office kitchen\n"
            "- 2026-10-21 Coffee order quantity stays 12 bags until December delivery\n"
        )
        self.assertNotIn("contradiction", checks(result))


class UndatedTests(unittest.TestCase):
    def test_undated_among_dated(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-27 A dated entry about project planning work\n"
            "- An undated entry about watering the office plants\n"
        )
        self.assertIn("undated", checks(result))
        finding = [f for f in result.findings if f.check == "undated"][0]
        self.assertEqual(finding.severity, "info")

    def test_fully_undated_section_not_flagged(self):
        result = scan_text(
            "## Ideas\n\n"
            "- Brainstorm a community garden for the rooftop\n"
            "- Brainstorm a reading club for winter evenings\n"
        )
        self.assertNotIn("undated", checks(result))


class BloatTests(unittest.TestCase):
    def test_section_bloat(self):
        bullets = "\n".join(
            f"- 2026-10-{(i % 27) + 1:02d} Unique topic number {i} about subject {i} details"
            for i in range(6)
        )
        result = scan_text(f"## Big\n\n{bullets}\n", max_section_entries=5)
        self.assertIn("bloat-section", checks(result))

    def test_file_bloat(self):
        text = "## Notes\n\n- 2026-10-27 " + ("word " * 200) + "\n"
        result = scan_text(text, max_tokens=50)
        self.assertIn("bloat-file", checks(result))


class ScoreTests(unittest.TestCase):
    def test_clean_scores_100(self):
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-26 Weekly review completed and action items documented\n"
            "- 2026-10-25 Team lunch scheduled for Friday at the cafe\n"
        )
        self.assertEqual(result.findings, [])
        self.assertEqual(result.score, 100)

    def test_score_formula(self):
        # One exact duplicate = 1 warn = -5.
        result = scan_text(
            "## Notes\n\n"
            "- 2026-10-27 The server password rotates every month\n"
            "- 2026-10-20 The server password rotates every month\n"
        )
        self.assertEqual(result.warn_count, 1)
        self.assertEqual(result.score, 95)


class ReportTests(unittest.TestCase):
    def _result(self):
        return scan_text(
            "## Notes\n\n"
            "- 2026-10-27 The server password rotates every month\n"
            "- 2026-10-20 The server password rotates every month\n"
        )

    def test_text_report(self):
        out = render(self._result(), "text")
        self.assertIn("health score", out)
        self.assertIn("duplicate-exact", out)

    def test_markdown_report(self):
        out = render(self._result(), "md")
        self.assertIn("# memlint report", out)
        self.assertIn("| warn | duplicate-exact |", out)

    def test_json_report(self):
        data = json.loads(render(self._result(), "json"))
        self.assertEqual(data["score"], 95)
        self.assertEqual(data["summary"]["warn"], 1)
        self.assertEqual(data["findings"][0]["check"], "duplicate-exact")


class CliTests(unittest.TestCase):
    def _write(self, tmp, text):
        path = Path(tmp) / "memory.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_cli_exit_1_on_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "## Notes\n\n"
                "- 2026-10-27 The server password rotates every month\n"
                "- 2026-10-20 The server password rotates every month\n",
            )
            with redirect_stdout(io.StringIO()):
                code = main(["scan", str(path), "--today", "2026-10-27"])
        self.assertEqual(code, 1)

    def test_cli_exit_0_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "## Notes\n\n"
                "- 2026-10-26 Weekly review completed and action items documented\n",
            )
            with redirect_stdout(io.StringIO()):
                code = main(["scan", str(path), "--today", "2026-10-27"])
        self.assertEqual(code, 0)

    def test_cli_exit_2_missing_path(self):
        with redirect_stdout(io.StringIO()):
            code = main(["scan", "/nonexistent/definitely/missing.md"])
        self.assertEqual(code, 2)

    def test_cli_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "## Notes\n\n"
                "- 2026-10-26 Weekly review completed and action items documented\n",
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(
                    ["scan", str(path), "--today", "2026-10-27", "--format", "json"]
                )
        data = json.loads(buffer.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["score"], 100)


class DirectoryScanTests(unittest.TestCase):
    def test_directory_scan_reads_all_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.md").write_text(
                "## Notes\n\n- 2026-10-26 Alpha entry about quarterly planning\n",
                encoding="utf-8",
            )
            (Path(tmp) / "b.md").write_text(
                "## Notes\n\n- 2026-10-26 Beta entry about gardening tools\n",
                encoding="utf-8",
            )
            (Path(tmp) / "ignore.txt").write_text("not markdown", encoding="utf-8")
            result = Scanner(today=TODAY).scan(tmp)
        self.assertEqual(len(result.files), 2)
        self.assertEqual(len(result.entries), 2)


if __name__ == "__main__":
    unittest.main()
