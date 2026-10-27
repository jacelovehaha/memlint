"""memlint — a hygiene linter for AI-agent memory files."""

from .core import Entry, Finding, ScanResult, Scanner, scan_path

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Entry",
    "Finding",
    "ScanResult",
    "Scanner",
    "scan_path",
]
