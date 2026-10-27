"""Core parsing, checks, and scoring for memlint.

memlint reads Markdown memory files: ``##``/``###`` sections containing
bullet entries. An entry may start with a date in one of these forms::

    - 2026-10-27 Went to the dentist.
    - 2026-10-27: Went to the dentist.
    - [2026-10-27] Went to the dentist.

All checks are local, deterministic, and dependency-free. The
contradiction check is a *heuristic* — it flags pairs of entries that
look like they disagree so a human can review them; it does not claim
to understand the text.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STALE_DAYS = 90
DEFAULT_MAX_SECTION_ENTRIES = 50
DEFAULT_MAX_TOKENS = 10_000
NEAR_DUPLICATE_THRESHOLD = 0.8

# Markers that suggest an entry negates or supersedes earlier information.
NEGATION_MARKERS = (
    "no longer",
    "not anymore",
    "cancelled",
    "canceled",
    "revoked",
    "deprecated",
    "obsolete",
    "superseded",
    "已取消",
    "不再",
    "取消了",
)

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*\S)\s*$")
_DATE_PREFIX_RE = re.compile(r"^\[?(\d{4})-(\d{2})-(\d{2})\]?\s*:?\s*")
_KEY_PREFIX_RE = re.compile(r"^key:\s*(\S+)\s*:?\s*", re.IGNORECASE)
_NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """Split *text* into normalized tokens.

    Lowercase, punctuation is ignored, digits are kept. Runs of CJK
    characters count as one token each.
    """
    return _TOKEN_RE.findall(text.lower())


def estimate_tokens(text: str) -> int:
    """Rough token estimate for a whole file.

    Formula (documented in the README): ``ceil(word_count / 0.75)``,
    where words are whitespace-separated runs. English prose averages
    roughly 0.75 words per token, so this is a cheap stand-in for a
    real tokenizer — good enough for a bloat warning.
    """
    words = len(text.split())
    if words == 0:
        return 0
    return math.ceil(words / 0.75)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    """One bullet entry parsed from a memory file."""

    file: str
    line: int
    section: str
    section_line: int
    raw: str  # entry text without the bullet marker
    content: str  # entry text without the leading date / key prefix
    entry_date: date | None
    evergreen: bool

    @property
    def tokens(self) -> list[str]:
        return tokenize(self.content)

    @property
    def token_set(self) -> set[str]:
        return set(self.tokens)

    @property
    def normalized(self) -> str:
        """Canonical form used for exact-duplicate detection."""
        return " ".join(self.tokens)

    @property
    def subject_key(self) -> str:
        """Grouping key for the contradiction heuristic.

        An explicit ``key:`` prefix wins; otherwise the first three
        content tokens after the date.
        """
        match = _KEY_PREFIX_RE.match(self.raw_after_date)
        if match:
            return " ".join(tokenize(match.group(1)))
        return " ".join(self.tokens[:3])

    @property
    def raw_after_date(self) -> str:
        match = _DATE_PREFIX_RE.match(self.raw)
        if match:
            return self.raw[match.end() :]
        return self.raw

    @property
    def first_number(self) -> float | None:
        match = _NUMBER_RE.search(self.content)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", ""))
        except ValueError:  # pragma: no cover - regex guarantees numeric
            return None

    @property
    def has_negation(self) -> bool:
        lowered = self.content.lower()
        return any(marker in lowered for marker in NEGATION_MARKERS)


@dataclass
class Finding:
    check: str
    severity: str  # "info" or "warn"
    file: str
    line: int
    message: str

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }


@dataclass
class ScanResult:
    files: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warn")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")

    @property
    def score(self) -> int:
        """Health score, 0-100.

        Transparent formula: start at 100, subtract 5 points per
        warn-level finding and 1 point per info-level finding, and
        never go below 0.
        """
        return max(0, 100 - 5 * self.warn_count - 1 * self.info_count)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "files_scanned": len(self.files),
            "entries": len(self.entries),
            "summary": {
                "warn": self.warn_count,
                "info": self.info_count,
                "total": len(self.findings),
            },
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_file(path: Path) -> tuple[list[Entry], str]:
    """Parse one Markdown file into entries; also return its raw text."""
    text = path.read_text(encoding="utf-8", errors="replace")
    entries: list[Entry] = []
    section = ""
    section_line = 1

    for lineno, line in enumerate(text.splitlines(), start=1):
        heading = _HEADING_RE.match(line)
        if heading:
            section = heading.group(2).strip()
            section_line = lineno
            continue

        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue

        raw = bullet.group(1).strip()
        entry_date: date | None = None
        content = raw
        date_match = _DATE_PREFIX_RE.match(raw)
        if date_match:
            try:
                entry_date = date(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3)),
                )
                content = raw[date_match.end() :]
            except ValueError:
                entry_date = None

        key_match = _KEY_PREFIX_RE.match(content)
        if key_match:
            content = content[key_match.end() :]

        entries.append(
            Entry(
                file=str(path),
                line=lineno,
                section=section,
                section_line=section_line,
                raw=raw,
                content=content.strip(),
                entry_date=entry_date,
                evergreen="evergreen" in section.lower(),
            )
        )

    return entries, text


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_duplicates(entries: list[Entry], findings: list[Finding]) -> None:
    # Exact duplicates: identical normalized token sequence.
    seen: dict[str, Entry] = {}
    exact_pairs: set[tuple[int, int]] = set()
    for entry in entries:
        if not entry.normalized:
            continue
        first = seen.get(entry.normalized)
        if first is None:
            seen[entry.normalized] = entry
        else:
            exact_pairs.add((id(first), id(entry)))
            findings.append(
                Finding(
                    check="duplicate-exact",
                    severity="warn",
                    file=entry.file,
                    line=entry.line,
                    message=(
                        f"Exact duplicate of the entry at line {first.line} "
                        f"in {first.file}."
                    ),
                )
            )

    # Near duplicates: token-set Jaccard similarity at or above the
    # threshold, excluding pairs already reported as exact duplicates.
    for i, a in enumerate(entries):
        if not a.token_set:
            continue
        for b in entries[i + 1 :]:
            if not b.token_set or (id(a), id(b)) in exact_pairs:
                continue
            if a.normalized == b.normalized:
                continue
            union = a.token_set | b.token_set
            if not union:
                continue
            similarity = len(a.token_set & b.token_set) / len(union)
            if similarity >= NEAR_DUPLICATE_THRESHOLD:
                findings.append(
                    Finding(
                        check="duplicate-near",
                        severity="warn",
                        file=b.file,
                        line=b.line,
                        message=(
                            f"Near-duplicate of the entry at line {a.line} "
                            f"in {a.file} "
                            f"(token similarity {similarity:.2f})."
                        ),
                    )
                )


def _check_stale(
    entries: list[Entry],
    findings: list[Finding],
    *,
    stale_days: int,
    today: date,
) -> None:
    for entry in entries:
        if entry.entry_date is None or entry.evergreen:
            continue
        age = (today - entry.entry_date).days
        if age > stale_days:
            findings.append(
                Finding(
                    check="stale",
                    severity="warn",
                    file=entry.file,
                    line=entry.line,
                    message=(
                        f"Entry dated {entry.entry_date.isoformat()} is "
                        f"{age} days old (stale threshold: {stale_days} "
                        f"days). Re-confirm or retire it."
                    ),
                )
            )


def _check_contradictions(entries: list[Entry], findings: list[Finding]) -> None:
    by_key: dict[str, list[Entry]] = {}
    for entry in entries:
        if entry.subject_key:
            by_key.setdefault(entry.subject_key, []).append(entry)

    for key, group in by_key.items():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                reasons: list[str] = []
                if (
                    a.first_number is not None
                    and b.first_number is not None
                    and a.first_number != b.first_number
                ):
                    reasons.append(
                        f"conflicting numbers ({a.first_number:g} vs "
                        f"{b.first_number:g})"
                    )
                if a.has_negation != b.has_negation:
                    reasons.append(
                        "one entry negates or supersedes the topic "
                        "while the other does not"
                    )
                if reasons:
                    findings.append(
                        Finding(
                            check="contradiction",
                            severity="warn",
                            file=b.file,
                            line=b.line,
                            message=(
                                f"Possible contradiction (heuristic) — "
                                f"review: entries at line {a.line} and "
                                f"line {b.line} share subject '{key}' but "
                                f"show {'; '.join(reasons)}."
                            ),
                        )
                    )


def _check_undated(entries: list[Entry], findings: list[Finding]) -> None:
    sections: dict[tuple[str, str, int], list[Entry]] = {}
    for entry in entries:
        sections.setdefault((entry.file, entry.section, entry.section_line), []).append(entry)

    for group in sections.values():
        if not any(e.entry_date is not None for e in group):
            continue  # a fully undated section is a style choice
        for entry in group:
            if entry.entry_date is None:
                findings.append(
                    Finding(
                        check="undated",
                        severity="info",
                        file=entry.file,
                        line=entry.line,
                        message=(
                            "Undated entry in a section where sibling "
                            "entries are dated. Add a date so staleness "
                            "can be tracked."
                        ),
                    )
                )


def _check_bloat(
    entries: list[Entry],
    findings: list[Finding],
    file_texts: dict[str, str],
    *,
    max_section_entries: int,
    max_tokens: int,
) -> None:
    sections: dict[tuple[str, str, int], list[Entry]] = {}
    for entry in entries:
        sections.setdefault((entry.file, entry.section, entry.section_line), []).append(entry)

    for (file, section, section_line), group in sections.items():
        if len(group) > max_section_entries:
            findings.append(
                Finding(
                    check="bloat-section",
                    severity="warn",
                    file=file,
                    line=section_line,
                    message=(
                        f"Section '{section or '(preamble)'}' has "
                        f"{len(group)} entries (limit: "
                        f"{max_section_entries}). Split or prune it."
                    ),
                )
            )

    for file, text in file_texts.items():
        tokens = estimate_tokens(text)
        if tokens > max_tokens:
            findings.append(
                Finding(
                    check="bloat-file",
                    severity="warn",
                    file=file,
                    line=1,
                    message=(
                        f"File is roughly {tokens} tokens (limit: "
                        f"{max_tokens}). Long memory files crowd the "
                        f"context window; archive older entries."
                    ),
                )
            )


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class Scanner:
    def __init__(
        self,
        *,
        stale_days: int = DEFAULT_STALE_DAYS,
        today: date | None = None,
        max_section_entries: int = DEFAULT_MAX_SECTION_ENTRIES,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.stale_days = stale_days
        self.today = today or date.today()
        self.max_section_entries = max_section_entries
        self.max_tokens = max_tokens

    def scan(self, path: str | Path) -> ScanResult:
        root = Path(path)
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = sorted(root.rglob("*.md"))
        else:
            raise FileNotFoundError(f"No such file or directory: {root}")

        result = ScanResult(files=[str(f) for f in files])
        file_texts: dict[str, str] = {}
        for file in files:
            entries, text = parse_file(file)
            result.entries.extend(entries)
            file_texts[str(file)] = text

        findings: list[Finding] = []
        _check_duplicates(result.entries, findings)
        _check_stale(
            result.entries,
            findings,
            stale_days=self.stale_days,
            today=self.today,
        )
        _check_contradictions(result.entries, findings)
        _check_undated(result.entries, findings)
        _check_bloat(
            result.entries,
            findings,
            file_texts,
            max_section_entries=self.max_section_entries,
            max_tokens=self.max_tokens,
        )

        findings.sort(key=lambda f: (f.file, f.line, f.check))
        result.findings = findings
        return result


def scan_path(path: str | Path, **kwargs) -> ScanResult:
    """Convenience wrapper around :class:`Scanner`."""
    return Scanner(**kwargs).scan(path)
