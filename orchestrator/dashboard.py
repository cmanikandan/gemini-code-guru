"""Server-rendered dashboard: answers 'is this working?' at a glance. Refreshes every 30 s."""
from html import escape


def _fmt(v, suffix="", pct=False):
    if v is None:
        return "–"
    return f"{v * 100:.0f}%" if pct else f"{v}{suffix}"


def _tile(label, value, note=""):
    return (f'<div class="tile"><div class="lbl">{escape(label)}</div>'
            f'<div class="val">{escape(value)}</div><div class="note">{escape(note)}</div></div>')


def _bars(daily: dict) -> str:
    days, vals = list(daily), list(daily.values())
    top = max(vals + [1])
    w, h, gap = 640, 120, 6
    bw = (w - gap * (len(vals) - 1)) / len(vals)
    out = []
    for i, (d, v) in enumerate(zip(days, vals)):
        bh = 0 if v == 0 else max(3, v / top * (h - 20))
        x = i * (bw + gap)
        out.append(f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" class="bar">'
                   f'<title>{d}: {v} PRs</title></rect>')
        if v:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{h - bh - 4:.1f}" class="bv">{v}</text>')
    return (f'<svg viewBox="0 -4 {w} {h + 22}" role="img" aria-label="PRs opened per day, last 14 days">'
            + "".join(out)
            + f'<text x="0" y="{h + 16}" class="ax">{days[0][5:]}</text>'
            + f'<text x="{w}" y="{h + 16}" class="ax" text-anchor="end">{days[-1][5:]}</text></svg>')


STATUS_CLASS = {"pr_opened": "good", "running": "info", "queued": "muted", "needs_human": "warn",
                "failed": "bad", "timeout": "bad", "cancelled": "muted"}


def render(m: dict, runs: list[dict], repo: str) -> str:
    c = m["counts"]
    bt = m.get("by_task_type", {})
    task_note = f'sec {bt.get("remediate", 0)} · feat {bt.get("feature", 0)} · mod {bt.get("modernize", 0)}'
    tiles = "".join([
        _tile("In flight", f'{c["running"]} running · {c["queued"]} queued', task_note),
        _tile("PR-opened rate", _fmt(m["pr_rate"], pct=True), "of finished runs"),
        _tile("Merge rate", _fmt(m["merge_rate"], pct=True), "of agent PRs closed"),
        _tile("Escalated to humans", _fmt(m["escalation_rate"], pct=True), "agent chose to stop"),
        _tile("Time to PR (p50 / p90)",
              f'{_fmt(m["time_to_pr_minutes_p50"])} / {_fmt(m["time_to_pr_minutes_p90"])} min', "agent run time"),
        _tile("Issue → PR (p50)", _fmt(m["issue_to_pr_hours_p50"], " h"), "exposure window"),
        _tile("Tokens per PR", _fmt(m["tokens_per_pr"]),
              f'≈ ${m["usd_per_pr"]} per PR' if m.get("usd_per_pr") is not None else "set USD_PER_MTOK for cost"),
        _tile("Issues fixed", f'{m["issues_with_pr"]} of {m["issues_touched"]}', "with an open or merged PR"),
    ])
    rows = []
    for r in runs[:50]:
        st = r.get("status", "")
        sk = r.get("skill", "vuln-fix")
        pr = r.get("pr_url")
        link = f'<a href="{escape(pr)}">PR</a>' if pr else ""
        rows.append(
            f'<tr><td><a href="https://github.com/{repo}/issues/{r["issue"]}">#{r["issue"]}</a></td>'
            f'<td><span class="pill muted">{escape(sk)}</span> {escape(str(r.get("title", "")))[:70]}</td>'
            f'<td>{r.get("attempt", "")}</td>'
            f'<td><span class="pill {STATUS_CLASS.get(st, "muted")}">{escape(st)}</span></td>'
            f'<td>{escape(str(r.get("detail", "")))[:90]} {link}</td>'
            f'<td class="num">{_fmt(round(r["duration_s"] / 60, 1) if r.get("duration_s") else None)}</td>'
            f'<td class="num">{r.get("tokens") or "–"}</td></tr>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30">
<title>gemini-oss-steward · {escape(repo)}</title><style>
:root{{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--accent:#2563eb;
--good:#15803d;--warn:#b45309;--bad:#b91c1c;--info:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0c0a09;--card:#1c1917;--ink:#f5f5f4;--mute:#a8a29e;
--line:#292524;--accent:#60a5fa;--good:#4ade80;--warn:#fbbf24;--bad:#f87171;--info:#60a5fa}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}} h1{{font-size:20px;margin:0 0 4px}}
.sub{{color:var(--mute);margin-bottom:20px}} a{{color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:20px}}
.tile,.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.lbl{{color:var(--mute);font-size:12px}} .val{{font-size:22px;font-weight:600;margin:4px 0}}
.note{{color:var(--mute);font-size:12px}} .bar{{fill:var(--accent)}} .bv,.ax{{fill:var(--mute);font-size:11px}}
.bv{{text-anchor:middle}} table{{width:100%;border-collapse:collapse}} .scroll{{overflow-x:auto}}
th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mute);font-weight:500;font-size:12px}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
.pill{{padding:2px 8px;border-radius:99px;font-size:12px;border:1px solid currentColor}}
.good{{color:var(--good)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}} .info{{color:var(--info)}}
.muted{{color:var(--mute)}} h2{{font-size:15px;margin:0 0 10px}}
</style></head><body><main>
<h1>gemini-oss-steward · {escape(repo)}</h1>
<div class="sub">Gemini managed agent · as of {escape(m["as_of"])} UTC · refreshes every 30 s ·
<a href="/metrics">metrics JSON</a></div>
<div class="grid">{tiles}</div>
<div class="card" style="margin-bottom:20px"><h2>PRs opened per day, last 14 days</h2>{_bars(m["prs_per_day_14d"])}</div>
<div class="card"><h2>Runs (latest 50)</h2><div class="scroll"><table>
<tr><th>Issue</th><th>Skill &amp; Title</th><th>Try</th><th>Status</th><th>Outcome</th><th class="num">Min</th><th class="num">Tokens</th></tr>
{''.join(rows) or '<tr><td colspan="7" class="muted">No runs yet. Label an issue agent:remediate, agent:feature, or agent:modernize to start one.</td></tr>'}
</table></div></div></main></body></html>"""
