# memlint

A hygiene linter for AI-agent memory files.

AI agents that keep long-term memory in Markdown — a `MEMORY.md`, daily
notes, sectioned bullet lists — slowly accumulate the same kinds of rot
as any hand-kept notebook: the same fact written down twice, facts that
went stale months ago, two entries that quietly disagree, and sections
that grew until they crowd everything else out of the context window.

memlint scans those files and reports the rot, with a 0–100 health
score you can track over time or gate in CI. It is a single-purpose,
zero-dependency Python tool: everything runs locally, nothing is sent
anywhere.

## Install

```console
$ pip install .
$ memlint --version
```

Or run it straight from a checkout, no install needed:

```console
$ PYTHONPATH=src python -m memlint scan path/to/memory.md
```

Requires Python 3.10+. No third-party dependencies.

## Usage

```console
$ memlint scan MEMORY.md
$ memlint scan ~/memory/                      # a directory: all *.md, recursively
$ memlint scan MEMORY.md --format md          # Markdown report
$ memlint scan MEMORY.md --format json        # machine-readable report
$ memlint scan MEMORY.md --stale-days 30      # stricter staleness
$ memlint scan MEMORY.md --today 2026-10-27   # pin the reference date
```

Exit codes: `0` when there are no warn-level findings, `1` when at
least one warn-level finding exists (so CI can fail the run), `2` for
usage errors such as a missing path.

## Input model

Memory files are Markdown. Entries are bullet lines (`-`, `*`, or `+`)
inside `##` or `###` sections. An entry may start with a date:

```markdown
## Projects

- 2026-10-27 Project Alpha budget is 5000 dollars for marketing campaign
- 2026-10-27: Booked the venue for the winter offsite
- [2026-10-27] Renewed the domain name for two more years
```

An entry may also carry an explicit grouping key for the contradiction
check:

```markdown
- 2026-10-27 key: deploy-freeze Release freeze starts on Friday
```

Sections whose heading contains the word `evergreen` (any case) are
exempt from the staleness check — that is where timeless principles
belong:

```markdown
## Evergreen Principles

- 2025-01-01 Always verify backups before starting any major upgrade
```

## Checks

| Check | Severity | What it flags |
| --- | --- | --- |
| `duplicate-exact` | warn | Two entries with identical normalized text (dates and punctuation ignored). |
| `duplicate-near` | warn | Two entries whose token sets have Jaccard similarity ≥ 0.80. |
| `stale` | warn | A dated entry older than `--stale-days` (default 90), outside evergreen sections. |
| `contradiction` | warn | Two entries sharing a subject that disagree — see below. |
| `undated` | info | An undated bullet in a section where sibling entries are dated. |
| `bloat-section` | warn | A section with more than `--max-section-entries` entries (default 50). |
| `bloat-file` | warn | A file over `--max-tokens` rough tokens (default 10,000). |

### Contradictions are a heuristic

memlint does not understand your notes. The contradiction check is a
deliberately simple heuristic, and findings are labelled
"Possible contradiction (heuristic) — review":

- Entries are grouped by a *subject key*: an explicit `key:` prefix if
  present, otherwise the first three content tokens after the date.
- Inside a group, a pair is flagged when their first numbers differ,
  or when exactly one of them contains a negation/update marker such
  as `no longer`, `cancelled`, `已取消`, or `不再`.

Expect false positives. The point is to surface pairs worth a human
glance, not to pass judgement.

## Health score

The score is intentionally transparent:

```
score = max(0, 100 - 5 * (warn findings) - 1 * (info findings))
```

A clean file scores 100. Every warning costs five points, every info
note one point. No hidden weighting.

## Token estimate

The `bloat-file` check needs a token count without a tokenizer
dependency, so memlint estimates:

```
estimated_tokens = ceil(word_count / 0.75)
```

where words are whitespace-separated runs. English prose averages
roughly 0.75 words per token, which makes this a reasonable stand-in
for deciding "this file is getting too big", and nothing more.

## Examples

`examples/messy_memory.md` is a small memory file with planted
problems — an exact duplicate, a near-duplicate, a stale entry, a
possible contradiction, and an undated entry among dated ones:

```console
$ memlint scan examples/messy_memory.md --today 2026-10-27
```

`examples/clean_memory.md` shows the tidy counterpart, including an
evergreen section, and scores 100.

## Development

```console
$ PYTHONPATH=src python -m unittest discover -s tests
```

## License

MIT — see [LICENSE](LICENSE).
