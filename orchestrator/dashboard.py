"""Server-rendered dashboard: answers 'is this working?' at a glance. Refreshes every 30 s."""
from html import escape


def _fmt(v, suffix="", pct=False):
    if v is None:
        return "–"
    return f"{v * 100:.0f}%" if pct else f"{v}{suffix}"


def _fmt_duration(sec) -> str:
    if sec is None:
        return "–"
    sec = float(sec)
    if sec == 0:
        return "0s (gate)"
    if sec < 60:
        return f"{sec:.1f}s"
    m = int(sec // 60)
    s = int(round(sec % 60))
    return f"{m}m {s:02d}s ({sec / 60:.1f}m)"


def _fmt_cost(cost, preflight_blocked=False) -> str:
    if preflight_blocked:
        return "$0.00 (gate)"
    if cost is None:
        return "–"
    cost = float(cost)
    if cost == 0:
        return "$0.00"
    return f"${cost:.3f}" if cost < 1.0 else f"${cost:.2f}"


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


def render_login(repo: str, error: str = "") -> str:
    err_html = f'<div class="err">{escape(error)}</div>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · gemini-code-guru ({escape(repo)})</title><style>
:root{{--bg:#0c0a09;--card:#1c1917;--ink:#f5f5f4;--mute:#a8a29e;--line:#292524;--accent:#3b82f6;--bad:#f87171}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;padding:16px}}
.box{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:28px 24px;width:100%;max-width:380px;
box-shadow:0 12px 32px rgba(0,0,0,0.4)}}
h1{{font-size:18px;margin:0 0 4px}} .sub{{color:var(--mute);font-size:13px;margin-bottom:20px}}
label{{display:block;font-size:12px;color:var(--mute);margin-bottom:4px;font-weight:500}}
input{{width:100%;box-sizing:border-box;padding:10px 12px;margin-bottom:14px;border-radius:8px;
border:1px solid var(--line);background:#141210;color:var(--ink);font-size:14px}}
input:focus{{outline:2px solid var(--accent);border-color:transparent}}
button{{width:100%;padding:10px 14px;border:none;border-radius:8px;background:var(--accent);color:#fff;
font-weight:600;font-size:14px;cursor:pointer}}
button:hover{{opacity:0.92}}
.err{{background:rgba(248,113,113,0.12);border:1px solid var(--bad);color:var(--bad);padding:8px 10px;
border-radius:8px;font-size:13px;margin-bottom:14px}}
.foot{{margin-top:16px;font-size:11px;color:var(--mute);text-align:center}}
</style></head><body>
<form class="box" method="post" action="/login">
<h1>gemini-code-guru</h1>
<div class="sub">Protected Observability Dashboard · <strong>{escape(repo)}</strong></div>
{err_html}
<label for="username">Username</label>
<input id="username" name="username" type="text" value="admin" required autocomplete="username">
<label for="password">Password</label>
<input id="password" name="password" type="password" placeholder="Enter dashboard password" required autofocus autocomplete="current-password">
<button type="submit">Sign in to Dashboard</button>
<div class="foot">Supports Session Cookie, HTTP Basic Auth, or Bearer Token</div>
</form></body></html>"""


def render(m: dict, runs: list[dict], repo: str, auth_enabled: bool = False) -> str:
    c = m["counts"]
    bt = m.get("by_task_type", {})
    pf = m.get("preflight_blocked", 0)
    task_note = f'sec {bt.get("remediate", 0)} · feat {bt.get("feature", 0)} · mod {bt.get("modernize", 0)}'
    esc_note = f"agent chose to stop ({pf} pre-flight)" if pf else "agent chose to stop"

    sbx_p50 = m.get("sandbox_minutes_p50")
    sbx_p90 = m.get("sandbox_minutes_p90")
    sbx_tot = m.get("sandbox_minutes_total", 0.0)
    sbx_note = f"{sbx_tot:.1f} min cumulative Linux sandbox time"

    usd_run = m.get("usd_per_run_avg")
    usd_pr = m.get("usd_per_pr")
    usd_tot = m.get("usd_total", 0.0)
    cache_rate = m.get("cache_hit_rate")
    cache_str = f" · {cache_rate * 100:.0f}% cached" if cache_rate is not None else ""
    cost_val = f"${usd_run:.3f}" if usd_run is not None else "$0.00"
    cost_note = f"≈ ${usd_pr:.3f}/PR · ${usd_tot:.2f} total{cache_str}" if usd_pr is not None else f"${usd_tot:.2f} total{cache_str}"

    tiles = "".join([
        _tile("In flight", f'{c["running"]} running · {c["queued"]} queued', task_note),
        _tile("PR-opened rate", _fmt(m["pr_rate"], pct=True), "of finished runs"),
        _tile("Merge rate", _fmt(m["merge_rate"], pct=True), "of agent PRs closed"),
        _tile("Escalated to humans", _fmt(m["escalation_rate"], pct=True), esc_note),
        _tile("Sandbox Runtime (p50 / p90)",
              f'{_fmt(sbx_p50)} / {_fmt(sbx_p90)} min', sbx_note),
        _tile("Issue → PR (p50)", _fmt(m["issue_to_pr_hours_p50"], " h"), "exposure window"),
        _tile("Tokens per PR", f'{m["tokens_per_pr"]:,}' if m.get("tokens_per_pr") else "–",
              f'avg {m["tokens_per_run_avg"]:,}/run' if m.get("tokens_per_run_avg") else "no token runs yet"),
        _tile("Est. Cost per Sandbox Run", cost_val, cost_note),
        _tile("Issues fixed", f'{m["issues_with_pr"]} of {m["issues_touched"]}', "with an open or merged PR"),
    ])
    rows = []
    for r in runs[:50]:
        st = r.get("status", "")
        sk = r.get("skill", "vuln-fix")
        pr = r.get("pr_url")
        link = f'<a href="{escape(pr)}">PR</a>' if pr else ""
        sbx_s = r.get("sandbox_s") if r.get("sandbox_s") is not None else r.get("duration_s")
        tok = r.get("tokens")
        inp = r.get("input_tokens")
        cached = r.get("cached_tokens")
        if tok:
            if inp and cached:
                tok_str = f"{int(tok):,} ({int(round(cached / inp * 100))}% cached)"
            else:
                tok_str = f"{int(tok):,}"
        else:
            tok_str = "0" if r.get("preflight_blocked") else "–"
        cost_str = _fmt_cost(r.get("cost_usd"), preflight_blocked=bool(r.get("preflight_blocked")))
        rows.append(
            f'<tr><td><a href="https://github.com/{repo}/issues/{r["issue"]}">#{r["issue"]}</a></td>'
            f'<td><span class="pill muted">{escape(sk)}</span> {escape(str(r.get("title", "")))[:65]}</td>'
            f'<td>{r.get("attempt", "")}</td>'
            f'<td><span class="pill {STATUS_CLASS.get(st, "muted")}">{escape(st)}</span></td>'
            f'<td>{escape(str(r.get("detail", "")))[:80]} {link}</td>'
            f'<td class="num">{escape(_fmt_duration(sbx_s))}</td>'
            f'<td class="num">{escape(tok_str)}</td>'
            f'<td class="num"><strong>{escape(cost_str)}</strong></td></tr>')
    logout_link = ' · <a href="/logout">sign out</a>' if auth_enabled else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30">
<title>gemini-code-guru · {escape(repo)}</title><style>
:root{{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--accent:#2563eb;
--good:#15803d;--warn:#b45309;--bad:#b91c1c;--info:#2563eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0c0a09;--card:#1c1917;--ink:#f5f5f4;--mute:#a8a29e;
--line:#292524;--accent:#60a5fa;--good:#4ade80;--warn:#fbbf24;--bad:#f87171;--info:#60a5fa}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 16px}} h1{{font-size:20px;margin:0 0 4px}}
.sub{{color:var(--mute);margin-bottom:20px}} a{{color:var(--accent)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-bottom:20px}}
.tile,.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.lbl{{color:var(--mute);font-size:12px}} .val{{font-size:22px;font-weight:600;margin:4px 0}}
.note{{color:var(--mute);font-size:12px}} .bar{{fill:var(--accent)}} .bv,.ax{{fill:var(--mute);font-size:11px}}
.bv{{text-anchor:middle}} table{{width:100%;border-collapse:collapse}} .scroll{{overflow-x:auto}}
th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mute);font-weight:500;font-size:12px}} .num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.pill{{padding:2px 8px;border-radius:99px;font-size:12px;border:1px solid currentColor}}
.good{{color:var(--good)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}} .info{{color:var(--info)}}
.muted{{color:var(--mute)}} h2{{font-size:15px;margin:0 0 10px}}
</style></head><body><main>
<h1>gemini-code-guru · {escape(repo)}</h1>
<div class="sub">Gemini managed agent · as of {escape(m["as_of"])} UTC · refreshes every 30 s ·
<a href="/metrics">metrics JSON</a> · <a href="/runs">runs JSON</a> · <a href="/compatibility">compatibility JSON</a>{logout_link}</div>
<div class="grid">{tiles}</div>
<div class="card" style="margin-bottom:20px"><h2>PRs opened per day, last 14 days</h2>{_bars(m["prs_per_day_14d"])}</div>
<div class="card"><h2>Runs (latest 50)</h2><div class="scroll"><table>
<tr><th>Issue</th><th>Skill &amp; Title</th><th>Try</th><th>Status</th><th>Outcome</th><th class="num">Sandbox Time</th><th class="num">Tokens (Cache)</th><th class="num">Est. Cost</th></tr>
{''.join(rows) or '<tr><td colspan="8" class="muted">No runs yet. Label an issue agent:remediate, agent:feature, or agent:modernize to start one.</td></tr>'}
</table></div></div></main></body></html>"""
