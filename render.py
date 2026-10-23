"""Self-contained HTML rendering of a :class:`differ.DiffReport`.

One HTML file, inline CSS, no external assets, no JavaScript. Every
piece of trace content is HTML-escaped before interpolation, so a tool
argument containing ``</script>`` or ``<b>`` renders as literal text.

Rendering is deterministic: the same report always produces
byte-identical HTML (sorted keys everywhere, no timestamps, no random
ids, fixed status ordering).
"""

from __future__ import annotations

import html
import json
from typing import Any, Dict, Optional

from differ import STATUS_ORDER, DiffReport

_CSS = """
body{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:2rem;color:#1a1a2e;background:#f7f7fa}
h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem}
.badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;font-weight:700;font-size:.8rem;letter-spacing:.04em}
.badge-identical{background:#d3f8df;color:#087443}
.badge-drift{background:#ffe3e3;color:#b42318}
.badge-matched{background:#d3f8df;color:#087443}
.badge-tool_drift,.badge-arg_drift,.badge-result_drift{background:#ffe3e3;color:#b42318}
.badge-missing,.badge-extra{background:#fef0c7;color:#93370d}
.counts{display:flex;gap:.5rem;flex-wrap:wrap;margin:1rem 0}
.count{background:#fff;border:1px solid #ddd;border-radius:.5rem;padding:.4rem .7rem}
.meta{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.row{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}
.card{background:#fff;border:1px solid #ddd;border-left:6px solid #aaa;border-radius:.5rem;padding:1rem;overflow-wrap:anywhere}
.card-matched{border-left-color:#12b76a}
.card-tool_drift,.card-arg_drift,.card-result_drift{border-left-color:#f04438}
.card-missing,.card-extra{border-left-color:#f79009}
.card-empty{background:transparent;border-style:dashed;color:#888;display:flex;align-items:center;justify-content:center}
pre{background:#f2f2f7;border-radius:.4rem;padding:.6rem;white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}
.diffs{background:#fff4f0;border:1px solid #ffd6cc;border-radius:.4rem;padding:.6rem 1rem;margin:1rem 0}
.diffs li{margin:.3rem 0}
.path{font-weight:700}
.val-left{background:#ffe3e3;padding:0 .3rem}
.val-right{background:#d3f8df;padding:0 .3rem}
.tool{font-weight:700}
""".strip()


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _pretty(obj: Any) -> str:
    return _esc(json.dumps(obj, sort_keys=True, indent=2, default=str))


def _value(obj: Any) -> str:
    return _esc(json.dumps(obj, sort_keys=True, default=str))


def _step_card(step: Optional[Dict[str, Any]], status: str, side: str) -> str:
    if step is None:
        return '<div class="card card-empty">no step on this side</div>'
    return (
        f'<div class="card card-{_esc(status)}">'
        f'<div><span class="badge badge-{_esc(status)}">{_esc(status.upper())}</span> '
        f'seq {_esc(step["seq"])} &middot; <span class="tool">{_esc(step["tool"])}</span></div>'
        f'<p>{_esc(step["observation"])}</p>'
        f'<h3>args</h3><pre>{_pretty(step["args"])}</pre>'
        f'<h3>result</h3><pre>{_pretty(step["result"])}</pre>'
        f'</div>'
    )


def _diffs_block(report: DiffReport, pair) -> str:
    items = []
    if pair.left_tool != pair.right_tool and pair.left_step and pair.right_step:
        items.append(
            f'<li><span class="path">$.tool</span>: '
            f'<span class="val-left">{_esc(pair.left_tool)}</span> &rarr; '
            f'<span class="val-right">{_esc(pair.right_tool)}</span></li>')
    for d in pair.field_diffs:
        items.append(
            f'<li><span class="path">{_esc(d["path"])}</span> ({_esc(d["kind"])}): '
            f'<span class="val-left">{_value(d["left"])}</span> &rarr; '
            f'<span class="val-right">{_value(d["right"])}</span></li>')
    if not items:
        return ""
    return '<ul class="diffs">' + "".join(items) + "</ul>"


def render_html(report: DiffReport) -> str:
    verdict = report.verdict
    badge_cls = "identical" if verdict == "IDENTICAL" else "drift"
    counts = report.counts
    count_chips = "".join(
        f'<span class="count">{_esc(s)}: {_esc(counts[s])}</span>'
        for s in STATUS_ORDER)
    count_chips += f'<span class="count">total: {_esc(len(report.pairs))}</span>'

    if report.meta_diffs:
        meta_items = "".join(
            f'<li><span class="path">{_esc(d["path"])}</span> ({_esc(d["kind"])}): '
            f'<span class="val-left">{_value(d["left"])}</span> &rarr; '
            f'<span class="val-right">{_value(d["right"])}</span></li>'
            for d in report.meta_diffs)
        meta_diffs_html = f'<ul class="diffs">{meta_items}</ul>'
    else:
        meta_diffs_html = "<p>Meta identical (volatile fields stripped).</p>"

    rows = []
    for pair in report.pairs:
        rows.append(
            '<div class="row">'
            + _step_card(pair.left_step, pair.status, "left")
            + _step_card(pair.right_step, pair.status, "right")
            + "</div>"
            + _diffs_block(report, pair))

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Trace Diff</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>Agent Trace Diff</h1>",
        f'<p>Verdict: <span class="badge badge-{badge_cls}">{_esc(verdict)}</span></p>',
        f'<div class="counts">{count_chips}</div>',
        "<h2>Meta comparison</h2>",
        '<div class="meta">'
        f'<div class="card"><h3>left meta</h3><pre>{_pretty(report.left_meta)}</pre></div>'
        f'<div class="card"><h3>right meta</h3><pre>{_pretty(report.right_meta)}</pre></div>'
        "</div>",
        meta_diffs_html,
        "<h2>Steps (aligned)</h2>",
        "".join(rows),
        "</body></html>",
        "",
    ]
    return "\n".join(parts)
