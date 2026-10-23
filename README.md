# trace-diff-visualizer

**Reviewing an agent behaviour change should look like reviewing a code change: a PR-style visual diff of what the agent actually did, step by step.**

That is how forward-deployed teams review agent regressions in practice. A prompt tweak, a tool rename, a backend change — and the agent quietly takes a different path through a customer workflow. A wall of JSONL in a terminal does not get reviewed; a side-by-side diff with per-step verdicts, highlighted changed fields, and a CI gate does. This project turns two recorded agent tool-call traces into exactly that: one self-contained HTML diff (no JavaScript, no external assets — it can be attached to a PR or dropped in a ticket as-is), a structured JSON diff for tooling, and a `check` command that fails CI on drift.

It is the visual half of the sibling [tool-call-trace-replay](../tool-call-trace-replay/) project, and it implements the piece that project's README lists as future work — *"a sequence-alignment differ"*. Where the sibling aligns steps **positionally** (so one step inserted mid-trace cascades into `tool_drift` on every downstream step), this differ aligns steps **by content** with a dynamic-programming sequence alignment: an inserted step reports as exactly one `extra`, a removed step as one `missing`, and everything downstream still matches.

Stdlib-only Python. Zero network, zero API keys, zero personal data — the fixtures are a fictional "Helios Home" smart-home support agent, so the whole thing runs offline.

## Quickstart

```bash
# 1. Render the visual diff for the bundled fixture pair
python3 cli.py render --left fixtures/baseline.jsonl --right fixtures/candidate.jsonl --out diff.html
#    -> open diff.html in any browser: verdict badge, aligned step cards, changed fields

# 2. Structured JSON diff to stdout
python3 cli.py diff --left fixtures/baseline.jsonl --right fixtures/candidate.jsonl

# 3. CI gate: exit 0 = identical, 1 = drift, 2 = usage / IO error
python3 cli.py check --left fixtures/baseline.jsonl --right fixtures/candidate.jsonl

# 4. One-command end-to-end demo (diff + HTML + exit codes + live serve round-trip)
python3 demo.py

# 5. Tiny localhost API: POST /render -> HTML, POST /diff -> JSON, GET /health
python3 cli.py serve --port 8765
```

## The fixture scenario

`fixtures/baseline.jsonl` vs `fixtures/candidate.jsonl` — a Helios Home support agent working a "thermostat not heating" case. The candidate contains, exactly:

| Change | Step | Reported as |
|---|---|---|
| Energy window `24h` → `7d` | `get_energy_usage` | `arg_drift` at `$.args.window` |
| Target set to 20.5 °C instead of 22.0 °C | `set_temperature` | `result_drift` at `$.result.target_c` |
| Tool renamed | `get_light_state` → `read_light_state` | `tool_drift` |
| Diagnostic sweep inserted mid-trace | `run_diagnostics` | one `extra` — downstream steps still `matched` |
| Firmware check dropped | `check_firmware` | one `missing` |
| New timestamps / request ids / durations everywhere | all other steps | **not drift** — volatile fields are stripped before comparison |

Pinned summary for the pair: `matched 3 · tool_drift 1 · arg_drift 1 · result_drift 1 · missing 1 · extra 1 · total 8` aligned rows, in the order `matched, matched, arg_drift, missing, extra, result_drift, tool_drift, matched`. Baseline vs itself renders the `IDENTICAL` verdict.

## How alignment works

Each candidate pairing scores: **+2** same tool, **+2** canonical args identical, **+1** same observation, **−3** if none of those hold; a one-sided step (gap) costs **−1**. A suffix dynamic-programming table finds the alignment maximising the total, with deterministic tie-breaking (pair > missing > extra). Results are deliberately *not* part of the signature — a result change must not break the alignment of the step that produced it. Aligned pairs are then classified by severity — `tool_drift` > `arg_drift` > `result_drift` > `matched` — and *all* field diffs are recorded even when a more severe drift decides the status.

Field-level diffs recursively walk args and result into `{path, kind: changed|added|removed, left, right}` entries (`$.args.window`, `$.result.checks[2]`, …). Numbers compare with relative tolerance `1e-6` (float wobble is not drift), bools never equal numbers (`True == 1` is a trap, not a match), and dict key order is ignored.

## Architecture

| Module | Job |
|---|---|
| `trace.py` | `Step` / `Trace` model for the tool-call-trace JSONL format (compatible with tool-call-trace-replay); `normalized()` strips volatile fields (`timestamp`, `request_id`, `duration_ms`, meta `trace_id` / `created_at`) |
| `fielddiff.py` | Recursive field-level diff (`changed` / `added` / `removed` with dotted paths) plus the tolerant `values_equal` comparator (1e-6 relative tolerance, bool-vs-number trap) |
| `align.py` | Needleman–Wunsch sequence alignment over tool + canonical-args signatures — the anti-cascade piece the sibling does not have |
| `differ.py` | Alignment + classification (`matched` / `tool_drift` / `arg_drift` / `result_drift` / `missing` / `extra`) + meta diff; produces the JSON-serialisable report |
| `render.py` | One self-contained HTML file: inline CSS, no JS, no external assets; verdict badge, summary counts, meta comparison, aligned step cards, highlighted changed fields; **all trace content HTML-escaped**; byte-identical output for the same input |
| `cli.py` | `render` / `diff` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /render`, `POST /diff`, `GET /health`) |
| `demo.py` | End-to-end narrative with asserts: fixture diff, identical verdict, deterministic render, escaping, CLI exit codes, live localhost serve round-trip |
| `fixtures/` | Fictional Helios Home baseline + candidate traces described above |

## Evals

`python3 evals/run_evals.py` → **12/12 golden evals**, report committed at `evals/eval_report.json` (byte-identical across runs):

- **E1** fixture summary counts pinned (3 matched / 1 each drift type / 1 missing / 1 extra / total 8)
- **E2** aligned-pair statuses in order pinned
- **E3** field-diff paths for the drifted steps pinned (`$.args.window`, `$.result.target_c`, tool pair)
- **E4** HTML determinism (two renders byte-identical)
- **E5** identical-pair verdict (baseline vs itself)
- **E6** volatile-only differences (timestamps, request ids, durations, trace ids) are not drift
- **E7** mid-trace insert = exactly one `extra`, downstream steps matched
- **E8** numeric-tolerance boundary and bool-vs-number traps pinned
- **E9** HTML escaping of hostile trace content (`</script><b>` renders as text)
- **E10** CLI `check` exit codes 0 / 1 / 2
- **E11** serve round-trip matches the local diff and render exactly
- **E12** JSON report determinism

Unit tests: `python3 -m unittest discover -s tests` → **108 hermetic tests**, including a no-network enforcement test (sockets stubbed), alignment tests, tolerance/bool traps, escaping and determinism tests, and CLI exit-code / serve tests.

## Scope and honest limits

- **An anchorless step reads as missing + extra.** Alignment needs *something* shared — tool, args, or observation. A step that changes all three at once has no anchor and is reported as one `missing` + one `extra`, not a drift pair (pinned by `test_anchorless_step_is_missing_plus_extra`). In practice drifted steps keep the same intent (observation), so this is rare — and arguably the honest reading of a wholesale replacement.
- **No move detection.** Reordered steps surface as `missing` + `extra` around the steps that stayed put; the diff does not label a step "moved".
- **Lists are order-sensitive** in field diffs (unlike the sibling differ, which compares lists of dicts order-insensitively). Reordering a list-valued arg is reported at the affected indices.
- **The HTML is a review artifact, not an app.** No JavaScript, no filtering, no collapse/expand — deliberately, so the file is safe to attach anywhere and renders identically forever.
- **Meta drift counts.** A non-volatile meta change (e.g. a different scenario name) flips the verdict to DRIFT alongside the step diffs; volatile meta fields never do.

## Dev loop: bugs the tests actually caught

1. **The aligner refused a "tool_drift" the test expected — and the test was wrong.** The first severity test built a pair whose tool, args *and* result all changed and expected `tool_drift`; the diff returned `missing` + `extra`. Investigation showed the test helper generated each step's observation *from its tool name*, so renaming the tool had silently changed the observation too — leaving the pair with no alignment anchor at all (score −3, worse than two gaps at −2). Real drifted steps keep the same observation (same intent, different execution), so the test was fixed to hold it constant, and the anchorless behaviour is now pinned explicitly (`test_anchorless_step_is_missing_plus_extra`) and documented under Scope above.
2. **Unclosed fixture files in the serve tests and demo.** The first full-suite run passed but printed `ResourceWarning: unclosed file` for the fixture reads in `test_cli.py` and the demo's serve payload. Re-running with `python3 -W error::ResourceWarning` turned them into failures; all reads now go through context managers, and the suite is clean under `-W error::ResourceWarning`.

## Why this project

Every forward-deployed team shipping agents to customers needs a review surface for agent behaviour: the replay harness (sibling) proves a golden session still passes, and this project makes the *difference* between two sessions something a human can review in thirty seconds — in a PR, in CI, or attached to a customer ticket — instead of a JSONL dump nobody reads. Same trace format, same comparison rules, one new capability: alignment that survives real-world insertions, and a picture worth reviewing.
