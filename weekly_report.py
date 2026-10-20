#!/usr/bin/env python3
"""AMC Launch Console: weekly pipeline report (function 1.7).

Emails all partners one report for the partner meeting and saves it under
reports/ in the repository (latest.html plus a dated copy). A snapshot of the
pipeline is kept so that each report shows what moved since the last one.
"""
import argparse, json, os, collections
from datetime import datetime, timedelta, timezone
import digest as D

F, O, G, U, C = D.F, D.O, D.G, D.U, D.C
T = dict(owner="field_1", date="field_2", channel="field_3", partner="field_4", reached="field_5", response="field_6")
STAGES = ["Identified", "Contacted", "Diagnosed", "Underwritten", "LOI issued", "LOI signed", "Closed"]
PARTNERS = ["Jeff", "Ken", "Mario", "Kyle"]
REPORTS = "reports"

def load_all(tok):
    data = D.load(tok)
    site = D.graph(tok, f"/sites/{D.SITE_HOST}:{D.SITE_PATH}")["id"]
    data["touches"] = D.list_items(tok, site, "Touches", ["Title"] + list(T.values()))
    return data

def esc(s): return D.esc(s)

def table(headers, rows):
    h = "".join(f'<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #d9dfe7;font-size:12px;color:#4d5a6b">{esc(x)}</th>' for x in headers)
    b = "".join("<tr>" + "".join(f'<td style="padding:4px 8px;border-bottom:1px solid #e8ecf1">{x}</td>' for x in r) + "</tr>" for r in rows) or f'<tr><td colspan="{len(headers)}" style="padding:4px 8px;color:#7a8697">None</td></tr>'
    return f'<table style="border-collapse:collapse;width:100%;margin:4px 0 12px"><tr>{h}</tr>{b}</table>'

def h3(t): return f'<h3 style="margin:18px 0 4px;font-size:14px">{t}</h3>'

def build(data, prev, now_et):
    today = now_et.strftime("%Y-%m-%d"); week_ago = (now_et - timedelta(days=7)).strftime("%Y-%m-%d")
    ahead60 = (now_et + timedelta(days=60)).strftime("%Y-%m-%d"); ahead14 = (now_et + timedelta(days=14)).strftime("%Y-%m-%d")
    owners, fns, gates, touches, posts = data["owners"], data["functions"], data["gates"], data["touches"], data["updates"]
    stage = lambda o: o.get(O["stage"]) or "Identified"
    conv = [o for o in owners if stage(o) != "Identified"]
    wave1 = [o for o in owners if o.get(O["wave1"]) == "Yes"]
    week_t = [t for t in touches if (D.day(t.get(T["date"])) or "") >= week_ago and not str(t.get("Title", "")).startswith("Example touch")]
    week_p = [u for u in posts if (D.day(u.get(U["posted"])) or D.day(u.get("Created")) or "") >= week_ago]
    snap = {o["_id"]: stage(o) for o in owners}
    moved = [(o, prev["stages"].get(o["_id"], "Identified"), stage(o)) for o in owners
             if prev and prev.get("stages") and prev["stages"].get(o["_id"], "Identified") != stage(o)]
    fsnap = {f["_id"]: (f.get(F["status"], "Not started"), int(f.get(F["pct"]) or 0)) for f in fns}
    fmoved = [(f, prev["functions"].get(f["_id"]), fsnap[f["_id"]]) for f in fns
              if prev and prev.get("functions") and tuple(prev["functions"].get(f["_id"], ("Not started", 0))) != fsnap[f["_id"]]]
    by_status = collections.Counter(f.get(F["status"], "Not started") for f in fns)
    risk = [f for f in fns if f.get(F["status"]) in ("At risk", "Blocked")]
    overdue = sorted([f for f in fns if f.get(F["status"]) != "Done" and D.day(f.get(F["due"])) and D.day(f[F["due"]]) < today], key=lambda f: f[F["due"]])
    due14 = sorted([f for f in fns if f.get(F["status"]) != "Done" and D.day(f.get(F["due"])) and today <= D.day(f[F["due"]]) <= ahead14], key=lambda f: f[F["due"]])
    gates_ahead = sorted([g for g in gates if D.day(g.get(G["date"])) and today <= D.day(g[G["date"]]) <= ahead60], key=lambda g: g[G["date"]])
    since = prev.get("date", "the start") if prev else "the start"

    H = (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#17212e;max-width:760px">'
         f'<p style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#7a8697;margin:0">AMC Launch Console · weekly pipeline report</p>'
         f'<h2 style="margin:4px 0 14px;font-weight:600">Week of {now_et.strftime("%B %-d, %Y")}</h2>'
         f'<p style="margin:0 0 10px">Owners in conversation <b>{len(conv)}</b> · Wave 1 named <b>{len(wave1)} of 30</b> (Gate G1) · touches this week <b>{len(week_t)}</b> · stage changes since {since} <b>{len(moved)}</b> · functions done <b>{by_status.get("Done",0)}</b>, in progress <b>{by_status.get("In progress",0)}</b>, at risk or blocked <b>{len(risk)}</b> of {len(fns)}</p>')
    # pipeline by stage x partner
    rows = []
    for s in STAGES:
        cnt = [sum(1 for o in owners if stage(o) == s and o.get(O["assigned"]) == p) for p in PARTNERS]
        rows.append([f"<b>{s}</b>"] + [str(c) if c else '<span style="color:#aab4c1">0</span>' for c in cnt] + [f"<b>{sum(cnt)}</b>"])
    H += h3("Pipeline by stage and partner") + table(["Stage"] + PARTNERS + ["Total"], rows)
    H += h3(f"Stage changes since {since} ({len(moved)})") + table(["Owner", "Property", "Partner", "From", "To"],
        [[esc(o.get(O["owner"])), f'{esc(o.get(O["prop"]))}, {esc(o.get(O["state"]))}', esc(o.get(O["assigned"])), esc(a), f"<b>{esc(b)}</b>"] for o, a, b in moved])
    bych = collections.Counter(t.get(T["channel"]) or "?" for t in week_t); byp = collections.Counter(t.get(T["partner"]) or "?" for t in week_t)
    H += h3(f"Touches logged this week ({len(week_t)})") + f'<p style="margin:0 0 6px;font-size:13px;color:#4d5a6b">By partner: {", ".join(f"{p} {n}" for p, n in byp.most_common()) or "none"} · by channel: {", ".join(f"{c} {n}" for c, n in bych.most_common()) or "none"}</p>'
    H += table(["Date", "Owner", "Partner", "Channel", "Reached", "Response"],
        [[D.when(t.get(T["date"])), esc(t.get(T["owner"])), esc(t.get(T["partner"])), esc(t.get(T["channel"])), esc(t.get(T["reached"])), esc(t.get(T["response"]))] for t in sorted(week_t, key=lambda t: t.get(T["date"]) or "", reverse=True)])
    H += h3(f"Wave 1 ({len(wave1)} of 30)") + table(["Owner", "Property", "Partner", "Stage", "Next touch"],
        [[esc(o.get(O["owner"])), f'{esc(o.get(O["prop"]))}, {esc(o.get(O["state"]))}', esc(o.get(O["assigned"])), esc(stage(o)), D.when(o.get(O["next"])) if o.get(O["next"]) else "—"] for o in sorted(wave1, key=lambda o: (STAGES.index(stage(o)) if stage(o) in STAGES else 0), reverse=True)])
    H += h3(f"Functions at risk or blocked ({len(risk)})") + table(["ID", "Function", "Lead", "Status", "Due"],
        [[esc(f.get(F["id"])), esc(f.get(F["name"])), esc(f.get(F["lead"])), esc(f.get(F["status"])), D.when(f.get(F["due"]))] for f in risk])
    H += h3(f"Functions overdue ({len(overdue)})") + table(["ID", "Function", "Lead", "Status", "%", "Was due"],
        [[esc(f.get(F["id"])), esc(f.get(F["name"])), esc(f.get(F["lead"])), esc(f.get(F["status"], "Not started")), int(f.get(F["pct"]) or 0), D.when(f.get(F["due"]))] for f in overdue])
    H += h3(f"Functions due in the next 14 days ({len(due14)})") + table(["ID", "Function", "Lead", "Status", "%", "Due"],
        [[esc(f.get(F["id"])), esc(f.get(F["name"])), esc(f.get(F["lead"])), esc(f.get(F["status"], "Not started")), int(f.get(F["pct"]) or 0), D.when(f.get(F["due"]))] for f in due14])
    H += h3(f"Function changes since {since} ({len(fmoved)})") + table(["ID", "Function", "Lead", "From", "To"],
        [[esc(f.get(F["id"])), esc(f.get(F["name"])), esc(f.get(F["lead"])), f"{esc((a or ['Not started',0])[0])} {(a or [0,0])[1]}%", f"<b>{esc(b[0])} {b[1]}%</b>"] for f, a, b in fmoved])
    H += h3(f"Gates and milestones in the next 60 days ({len(gates_ahead)})") + table(["ID", "Name", "Date", "Owner", "Status"],
        [[esc(g.get(G["id"])), esc(g.get(G["name"])), D.when(g.get(G["date"])), esc(g.get(G["owner"])), esc(g.get(G["status"], "Scheduled"))] for g in gates_ahead])
    H += h3(f"Posts this week ({len(week_p)}, {sum(1 for u in week_p if u.get(U['urgent']) == 'Yes')} urgent)") + table(["When", "Who", "About", "Message"],
        [[(u.get(U["posted"]) or u.get("Created") or "")[:16].replace("T", " "), esc(u.get(U["author"])), esc(u.get(U["about"])), ('<b style="color:#b3261e">URGENT</b> ' if u.get(U["urgent"]) == "Yes" else "") + esc(u.get(U["msg"]))] for u in sorted(week_p, key=lambda u: u.get(U["posted"]) or u.get("Created") or "", reverse=True)])
    H += f'<p style="margin:18px 0 0"><a href="{D.CONSOLE}" style="color:#1d4e7a">Open the Launch Console</a></p></div>'
    subject = f"AMC weekly pipeline report · {now_et.strftime('%b %-d')} · {len(conv)} in conversation, {len(wave1)}/30 Wave 1, {len(week_t)} touches, {len(risk)} at risk"
    snapshot = {"date": today, "stages": snap, "functions": {k: list(v) for k, v in fsnap.items()}}
    return subject, H, snapshot

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", help="send only to this address (test)"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--data"); ap.add_argument("--force", action="store_true", help="send regardless of the Cadence schedule")
    a = ap.parse_args()
    now_et = datetime.now(D.ET); slot = now_et.strftime("%A %H:00")
    data, tok = (json.load(open(a.data)), None) if a.data else (None, D.token())
    if tok: data = load_all(tok)
    prev = json.load(open(f"{REPORTS}/snapshot.json")) if os.path.exists(f"{REPORTS}/snapshot.json") else None
    subject, html, snapshot = build(data, prev, now_et)
    recipients = [a.to] if a.to else [r.get(C["email"]) for r in data["cadence"]
                  if r.get(C["email"]) and (a.force or str(r.get(C["weekly"]) or "").startswith(slot))]
    print(subject); print("recipients:", recipients or "none at this slot", "| slot", slot)
    os.makedirs(REPORTS, exist_ok=True)
    open(f"{REPORTS}/latest.html", "w").write(html); open(f"{REPORTS}/{now_et.strftime('%Y-%m-%d')}.html", "w").write(html)
    if not (a.dry_run or tok is None) and recipients:
        D.graph(tok, f"/users/{D.SENDER}/sendMail", "POST", {"message": {"subject": subject, "body": {"contentType": "HTML", "content": html},
                 "toRecipients": [{"emailAddress": {"address": r}} for r in recipients]}, "saveToSentItems": True})
        print("sent")
    if not a.dry_run and recipients and not a.to:
        json.dump(snapshot, open(f"{REPORTS}/snapshot.json", "w"), indent=0); print("snapshot updated")
    print("done")

if __name__ == "__main__":
    main()
