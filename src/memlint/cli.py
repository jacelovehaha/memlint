"""Command-line interface for memlint."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from . import __version__
from .core import (
    DEFAULT_MAX_SECTION_ENTRIES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_STALE_DAYS,
    Scanner,
)
from .report import render


def _parse_today(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memlint",
        description="Lint AI-agent memory files for duplicates, "
        "staleness, contradictions, and bloat.",
    )
    parser.add_argument("--version", action="version", version=f"memlint {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a memory file or directory.")
    scan.add_argument("path", help="A Markdown file, or a directory of them.")
    scan.add_argument(
        "--format",
        choices=["text", "md", "json"],
        default="text",
        help="Report format (default: text).",
    )
    scan.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Entries older than this many days are stale "
        f"(default: {DEFAULT_STALE_DAYS}).",
    )
    scan.add_argument(
        "--today",
        type=_parse_today,
        default=None,
        help="Reference date for staleness, YYYY-MM-DD (default: today).",
    )
    scan.add_argument(
        "--max-section-entries",
        type=int,
        default=DEFAULT_MAX_SECTION_ENTRIES,
        help=f"Warn when a section holds more entries than this "
        f"(default: {DEFAULT_MAX_SECTION_ENTRIES}).",
    )
    scan.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Warn when a file exceeds this rough token estimate "
        f"(default: {DEFAULT_MAX_TOKENS}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        scanner = Scanner(
            stale_days=args.stale_days,
            today=args.today,
            max_section_entries=args.max_section_entries,
            max_tokens=args.max_tokens,
        )
        try:
            result = scanner.scan(args.path)
        except FileNotFoundError as exc:
            print(f"memlint: {exc}", file=sys.stderr)
            return 2
        sys.stdout.write(render(result, args.format))
        # CI-friendly: warn-level findings fail the run.
        return 1 if result.warn_count else 0

    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
