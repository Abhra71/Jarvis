"""The AI status page: a small web page served only on this PC (127.0.0.1), refreshed every 2 seconds."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import tasklog
from .usage import usage

log = logging.getLogger(__name__)

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis AI Status</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2129;--muted:#667085;--line:#e4e7ec;--ok:#12805c;--warn:#b54708;--bad:#c01048;--info:#175cd3;--look:#7a2ed8;--chip:#f2f4f7}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--text:#e6e8eb;--muted:#98a2b3;--line:#2a2f37;--ok:#3ccb8f;--warn:#f5a524;--bad:#f45b7a;--info:#6ea8ff;--look:#b48aff;--chip:#232830}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 "Segoe UI",system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:14px;margin:0 0 10px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.sub{color:var(--muted);margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.big{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums}.label{color:var(--muted);font-size:12px}
.now{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.dot{width:12px;height:12px;border-radius:50%;background:var(--muted);flex:none}
.dot.idle{background:var(--info)}.dot.look{background:var(--look);box-shadow:0 0 0 4px color-mix(in srgb,var(--look) 25%,transparent)}.dot.busy{background:var(--warn)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;font-size:12px}
.wrap{overflow-x:auto}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:var(--chip);white-space:nowrap}
.b-ok{color:var(--ok)}.b-warn{color:var(--warn)}.b-bad{color:var(--bad)}.b-look{color:var(--look)}.b-info{color:var(--info)}
.muted{color:var(--muted)}.said{max-width:340px}
.note{color:var(--muted);font-size:12px;margin-top:8px}
section{margin-bottom:16px}
</style></head><body><main>
<h1>Jarvis AI status</h1><div class="sub" id="sub">Loading…</div>

<section class="card now"><span class="dot" id="dot"></span>
  <div><div class="label">Right now</div><div id="activity" style="font-weight:600">…</div></div>
  <div style="margin-left:auto;text-align:right"><div class="label">Next AI request goes to</div><div id="next" style="font-weight:600">…</div></div>
</section>

<div class="grid">
  <div class="card"><div class="label">AI requests today</div><div class="big" id="req">0</div></div>
  <div class="card"><div class="label">Handled offline</div><div class="big" id="off">0</div></div>
  <div class="card"><div class="label">Answered by Gemini</div><div class="big" id="gem">0</div></div>
  <div class="card"><div class="label">Answered by Groq (backup)</div><div class="big" id="groq">0</div></div>
  <div class="card"><div class="label">Screenshots today</div><div class="big" id="shots">0</div><div class="label" id="lastshot"></div></div>
  <div class="card"><div class="label">Failed</div><div class="big" id="fail">0</div></div>
</div>

<section class="card"><h2>Today's review</h2>
<div class="grid" style="margin-bottom:8px">
  <div><div class="label">Requests</div><div class="big" id="t-total">0</div></div>
  <div><div class="label">Worked (seen done)</div><div class="big" id="t-ok">—</div></div>
  <div><div class="label">Needed you</div><div class="big" id="t-asked">0</div></div>
  <div><div class="label">Went wrong</div><div class="big" id="t-wrong">0</div></div>
  <div><div class="label">Usual time</div><div class="big" id="t-time">—</div><div class="label" id="t-slow"></div></div>
</div>
<div class="wrap"><table>
<thead><tr><th>Time</th><th>You said</th><th>Result</th><th>Why</th><th>Took</th><th>Heard by</th></tr></thead>
<tbody id="wrong"></tbody></table></div>
<div class="note">Every request is also saved, one line each, in logs/tasks-&lt;date&gt;.jsonl for the review after the trial.</div>
</section>

<section class="card"><h2>Models (in the order Jarvis tries them)</h2><div class="wrap"><table>
<thead><tr><th>Model</th><th>State</th><th>Requests</th><th>OK</th><th>Limit hit</th><th>Busy / slow</th><th>Avg time</th><th>Tokens in / out</th><th>Allowance left</th><th>Last used</th></tr></thead>
<tbody id="models"></tbody></table></div>
<div class="note">Groq reports how much is left with every answer. Gemini doesn't report remaining free usage;
check your limits in Google AI Studio. "Limit hit" means Google or Groq said "too many requests"; Jarvis then skips
that model for about a minute.</div></section>

<section class="card"><h2>Recent requests</h2><div class="wrap"><table>
<thead><tr><th>Time</th><th>You said</th><th>Handled by</th><th>Screen</th><th>Models tried</th><th>Took</th><th>Reply</th></tr></thead>
<tbody id="turns"></tbody></table></div></section>
</main>
<script>
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function stateBadge(s){let c="b-info";if(s.startsWith("working"))c="b-ok";else if(s.startsWith("limit"))c="b-bad";else if(/busy|slow|error/.test(s))c="b-warn";return `<span class="badge ${c}">${esc(s)}</span>`}
function routeBadge(r){const c={"gemini":"b-ok","groq":"b-warn","offline rules":"b-info","failed":"b-bad"}[r]||"";return `<span class="badge ${c}">${esc(r)}</span>`}
async function tick(){
  try{
    const s=await (await fetch("status.json",{cache:"no-store"})).json();
    document.getElementById("sub").textContent=`${s.day} · updated ${s.now} · only visible on this PC`;
    const act=s.activity||"idle";document.getElementById("activity").textContent=act==="idle"?"Idle (waiting for “Hi Jarvis”)":act[0].toUpperCase()+act.slice(1);
    const dot=document.getElementById("dot");dot.className="dot "+(act==="idle"?"idle":act.includes("screen")?"look":"busy");
    const next=s.order.find(k=>{const m=s.models.find(x=>x.key===k);return !m||!m.state.startsWith("limit")});
    document.getElementById("next").textContent=next?next.replace(":"," · "):"all models at their limit";
    const r=s.routes;document.getElementById("req").textContent=s.ai_requests;
    document.getElementById("off").textContent=r["offline rules"]||0;document.getElementById("gem").textContent=r.gemini||0;
    document.getElementById("groq").textContent=r.groq||0;document.getElementById("fail").textContent=r.failed||0;
    document.getElementById("shots").textContent=s.screenshots.count;
    document.getElementById("lastshot").textContent=s.screenshots.last?`last at ${s.screenshots.last}`:"none yet";
    const byKey=Object.fromEntries(s.models.map(m=>[m.key,m]));
    const keys=[...s.order,...s.models.map(m=>m.key).filter(k=>!s.order.includes(k))];
    document.getElementById("models").innerHTML=keys.map(k=>{const m=byKey[k]||{state:"not used yet"};const L=m.limits||{};
      const left=L["remaining-requests"]?`${esc(L["remaining-requests"])}/${esc(L["limit-requests"])} req today · ${esc(L["remaining-tokens"])}/${esc(L["limit-tokens"])} tokens/min`:(k.startsWith("gemini")?'<span class="muted">not reported</span>':'<span class="muted">—</span>');
      return `<tr><td><b>${esc(k.split(":")[1])}</b><div class="muted">${esc(k.split(":")[0])}${k===s.order[0]?" · main":""}</div></td><td>${stateBadge(m.state)}</td>
      <td>${m.requests??0}</td><td>${m.ok??0}</td><td>${m.limited??0}</td><td>${(m.busy??0)+(m.timeouts??0)}</td>
      <td>${m.avg_seconds!=null?m.avg_seconds+"s":"—"}</td><td>${m.tokens_in??0} / ${m.tokens_out??0}</td><td>${left}</td><td>${esc(m.last_used||"—")}</td></tr>`}).join("");
    document.getElementById("turns").innerHTML=s.turns.map(t=>`<tr><td>${esc(t.time)}</td><td class="said">${esc(t.said)}</td><td>${routeBadge(t.route)}</td>
      <td>${t.screenshots?`<span class="badge b-look">📷 ${t.screenshots}</span>`:'<span class="muted">—</span>'}</td>
      <td class="muted">${esc((t.models||[]).join(", "))||"—"}</td><td>${t.seconds??"…"}s</td><td class="said muted">${esc(t.reply)}</td></tr>`).join("")
      ||'<tr><td colspan="7" class="muted">Nothing yet today.</td></tr>';
  }catch(e){document.getElementById("sub").textContent="Jarvis isn't running (or restarting)…"}
}
async function review(){
  try{
    const t=await (await fetch("tasks.json",{cache:"no-store"})).json();const c=t.counts||{};
    document.getElementById("t-total").textContent=t.total;
    document.getElementById("t-ok").textContent=t.worked_percent==null?"—":t.worked_percent+"%";
    document.getElementById("t-asked").textContent=c.asked||0;
    document.getElementById("t-wrong").textContent=(c.stuck||0)+(c.failed||0)+(c.unconfirmed||0);
    document.getElementById("t-time").textContent=t.median_seconds==null?"—":t.median_seconds.toFixed(1)+"s";
    document.getElementById("t-slow").textContent=t.slow?`${t.slow} took 6 s or more`:"";
    const cls={stuck:"b-bad",failed:"b-bad",unconfirmed:"b-warn"};
    document.getElementById("wrong").innerHTML=t.wrong.map(e=>`<tr><td>${esc(e.time)}</td><td class="said">${esc(e.said)}</td>
      <td><span class="badge ${cls[e.result]||""}">${esc(e.result)}</span></td><td class="said muted">${esc(e.why||e.reply)}</td>
      <td>${(e.seconds??0).toFixed(1)}s</td><td class="muted">${esc(e.hearing?e.hearing.source+(e.hearing.unsure?" (unsure)":""):"—")}</td></tr>`).join("")
      ||'<tr><td colspan="6" class="muted">Nothing went wrong today.</td></tr>';
  }catch(e){}
}
tick();setInterval(tick,2000);review();setInterval(review,5000);
</script></body></html>"""


def start(order_fn, port: int = 8765) -> str | None:
    """Serve the page in the background. `order_fn()` gives model keys in the order Jarvis tries them."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] == "/status.json":
                body = json.dumps({**usage.snapshot(), "order": order_fn()}).encode()
                ctype = "application/json"
            elif self.path.split("?")[0] == "/tasks.json":
                body = json.dumps(tasklog.summary(tasklog.read())).encode()
                ctype = "application/json"
            elif self.path in ("/", "/index.html"):
                body, ctype = PAGE.encode(), "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # keep the Jarvis log clean

    for p in range(port, port + 10):  # next free port if something else uses 8765
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
        threading.Thread(target=server.serve_forever, name="dashboard", daemon=True).start()
        url = f"http://127.0.0.1:{p}/"
        log.info("AI status page: %s", url)
        return url
    log.warning("Couldn't start the status page")
    return None
