"""Render a ScanResult as text, Markdown, or JSON."""

from __future__ import annotations

import json

from .core import ScanResult

SCORE_FORMULA = "100 - 5 per warn finding - 1 per info finding (floor 0)"


def render_text(result: ScanResult) -> str:
    lines = [
        "memlint report",
        f"  files scanned : {len(result.files)}",
        f"  entries       : {len(result.entries)}",
        f"  health score  : {result.score}/100  ({SCORE_FORMULA})",
        f"  findings      : {len(result.findings)} "
        f"({result.warn_count} warn, {result.info_count} info)",
        "",
    ]
    if not result.findings:
        lines.append("No findings. Memory looks clean.")
    for finding in result.findings:
        lines.append(
            f"[{finding.severity}] {finding.check} "
            f"{finding.file}:{finding.line}"
        )
        lines.append(f"    {finding.message}")
    return "\n".join(lines) + "\n"


def render_markdown(result: ScanResult) -> str:
    lines = [
        "# memlint report",
        "",
        f"- **Health score:** {result.score}/100 ({SCORE_FORMULA})",
        f"- **Files scanned:** {len(result.files)}",
        f"- **Entries:** {len(result.entries)}",
        f"- **Findings:** {len(result.findings)} "
        f"({result.warn_count} warn, {result.info_count} info)",
        "",
    ]
    if not result.findings:
        lines.append("No findings. Memory looks clean.")
        lines.append("")
        return "\n".join(lines)

    lines += [
        "| Severity | Check | File | Line | Message |",
        "| --- | --- | --- | --- | --- |",
    ]
    for finding in result.findings:
        message = finding.message.replace("|", "\\|")
        lines.append(
            f"| {finding.severity} | {finding.check} | {finding.file} "
            f"| {finding.line} | {message} |"
        )
    lines.append("")
    lines.append(
        "_The contradiction check is a heuristic: it flags entry pairs "
        "that share a subject but disagree on a number or a negation "
        "marker, for human review._"
    )
    lines.append("")
    return "\n".join(lines)


def render_json(result: ScanResult) -> str:
    return json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n"


def render(result: ScanResult, fmt: str) -> str:
    if fmt == "md":
        return render_markdown(result)
    if fmt == "json":
        return render_json(result)
    return render_text(result)
