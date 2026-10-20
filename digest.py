#!/usr/bin/env python3
"""AMC Launch Console: daily digest.

Reads the six AMC Partners lists through Microsoft Graph with the console's app
registration (application permissions, no partner account involved) and emails
each partner whose Cadence row names the current Eastern hour. Runs on a schedule
from GitHub Actions; can also be run by hand with --hour and --to for testing.
"""
import argparse, json, os, sys, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TENANT = os.environ.get("AMC_TENANT_ID", "")
CLIENT = os.environ.get("AMC_CLIENT_ID", "")
SECRET = os.environ.get("AMC_CLIENT_SECRET", "")
SENDER = os.environ.get("AMC_SENDER", "jss@americanmilitarycommunities.com")
SITE_HOST, SITE_PATH = "accend1.sharepoint.com", "/sites/AMCPartners"
CONSOLE = "https://amc-wa.github.io/amc-launch-console/"
ET = ZoneInfo("America/New_York")

# Internal column names (SharePoint numbered them in import order).
F = dict(id="field_1", name="field_2", group="field_3", tier="field_4", lead="field_5", backup="field_6",
         start="field_7", due="field_8", status="field_12", pct="field_13")
O = dict(assigned="field_7", stage="field_8", next="field_10", wave1="field_11", prop="field_18",
         city="field_20", state="field_21", owner="field_33")
G = dict(id="field_1", kind="field_2", name="field_3", date="field_4", owner="field_8", status="field_9")
U = dict(kind="field_1", about="field_2", author="field_3", msg="field_4", urgent="field_5", posted="field_6")
C = dict(partner="field_1", daily="field_2", weekly="field_3", due="field_4", gate="field_5", email="Email")

# ---------------- Graph ----------------
def token():
    body = urllib.parse.urlencode({"client_id": CLIENT, "client_secret": SECRET, "grant_type": "client_credentials",
                                   "scope": "https://graph.microsoft.com/.default"}).encode()
    req = urllib.request.Request(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token", data=body)
    with urllib.request.urlopen(req) as r:
        return json.load(r)["access_token"]

def graph(tok, path, method="GET", payload=None):
    url = path if path.startswith("https://") else "https://graph.microsoft.com/v1.0" + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + tok, "Content-Type": "application/json",
        "Prefer": "HonorNonIndexedQueriesWarningMayFailRandomly"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r) if r.status != 202 else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:600]}")

def list_items(tok, site_id, name, select):
    url = f"/sites/{site_id}/lists/{urllib.parse.quote(name)}/items?$top=999&$expand=fields($select={','.join(select)})"
    out = []
    while url:
        j = graph(tok, url)
        out += [dict(v["fields"], _id=v["id"]) for v in j["value"]]
        url = j.get("@odata.nextLink")
    return out

def load(tok):
    site = graph(tok, f"/sites/{SITE_HOST}:{SITE_PATH}")["id"]
    return dict(
        cadence=list_items(tok, site, "Cadence", ["Title"] + list(C.values())),
        functions=list_items(tok, site, "Functions", ["Title"] + list(F.values())),
        owners=list_items(tok, site, "Owners", ["Title"] + list(O.values())),
        gates=list_items(tok, site, "Gates", ["Title"] + list(G.values())),
        updates=list_items(tok, site, "Updates", ["Title", "Created"] + list(U.values())),
    )

def send_mail(tok, to, subject, html):
    graph(tok, f"/users/{SENDER}/sendMail", "POST", {"message": {
        "subject": subject, "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": to}}]}, "saveToSentItems": True})

# ---------------- Digest ----------------
def day(s):  # 'YYYY-MM-DD' from an ISO value, or None
    return s[:10] if isinstance(s, str) and len(s) >= 10 else None

def when(s):
    d = day(s)
    return datetime.strptime(d, "%Y-%m-%d").strftime("%a %b %-d") if d else "no date"

def days_of(v):  # '3 days before' -> 3; 'Off'/None -> 0
    try:
        return 0 if not v or str(v).lower().startswith("off") else int(str(v).split()[0])
    except ValueError:
        return 0

def esc(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def build(partner, row, data, now_et):
    today = now_et.strftime("%Y-%m-%d")
    warn, gate = days_of(row.get(C["due"])), days_of(row.get(C["gate"]))
    due_limit = (now_et + timedelta(days=warn)).strftime("%Y-%m-%d")
    gate_limit = (now_et + timedelta(days=gate)).strftime("%Y-%m-%d")
    touch_limit = (now_et + timedelta(days=1)).strftime("%Y-%m-%d")
    since = (now_et.astimezone(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

    mine = [f for f in data["functions"] if f.get(F["status"], "Not started") != "Done"
            and partner in (f.get(F["lead"]), f.get(F["backup"]))]
    overdue = sorted([f for f in mine if day(f.get(F["due"])) and day(f[F["due"]]) < today], key=lambda f: f[F["due"]])
    due = sorted([f for f in mine if day(f.get(F["due"])) and today <= day(f[F["due"]]) <= due_limit], key=lambda f: f[F["due"]])
    touches = sorted([o for o in data["owners"] if o.get(O["assigned"]) == partner and day(o.get(O["next"]))
                      and day(o[O["next"]]) <= touch_limit], key=lambda o: o[O["next"]])
    gates = sorted([g for g in data["gates"] if g.get(G["status"], "Scheduled") == "Scheduled" and day(g.get(G["date"]))
                    and today <= day(g[G["date"]]) <= gate_limit], key=lambda g: g[G["date"]])
    posts = sorted([u for u in data["updates"] if (u.get(U["posted"]) or u.get("Created") or "") >= since],
                   key=lambda u: u.get(U["posted"]) or u.get("Created") or "", reverse=True)

    def li(items, fmt):
        return "".join(fmt(i) for i in items) if items else "<li>None</li>"
    role = lambda f: "lead" if f.get(F["lead"]) == partner else "backup"
    H = (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#17212e;max-width:680px">'
         f'<p style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#7a8697;margin:0">AMC Launch Console · daily digest</p>'
         f'<h2 style="margin:4px 0 14px;font-weight:600">{esc(partner)} · {now_et.strftime("%A, %B %-d")}</h2>')
    H += f'<h3 style="margin:14px 0 4px;font-size:14px">Overdue ({len(overdue)})</h3><ul style="margin:0;padding-left:18px">' + li(overdue, lambda f:
        f'<li><b>{esc(f.get(F["id"]))}</b> {esc(f.get(F["name"]))} · was due {when(f.get(F["due"]))} · {esc(f.get(F["status"], "Not started"))} {int(f.get(F["pct"]) or 0)}% · {role(f)}</li>') + "</ul>"
    H += f'<h3 style="margin:14px 0 4px;font-size:14px">Due within {warn} days ({len(due)})</h3><ul style="margin:0;padding-left:18px">' + li(due, lambda f:
        f'<li><b>{esc(f.get(F["id"]))}</b> {esc(f.get(F["name"]))} · due {when(f.get(F["due"]))} · {esc(f.get(F["status"], "Not started"))} {int(f.get(F["pct"]) or 0)}% · {role(f)}</li>') + "</ul>"
    H += f'<h3 style="margin:14px 0 4px;font-size:14px">Owner touches due today or tomorrow ({len(touches)})</h3><ul style="margin:0;padding-left:18px">' + li(touches, lambda o:
        f'<li><b>{esc(o.get(O["owner"]))}</b> · {esc(o.get(O["prop"]))}, {esc(o.get(O["state"]))} · {esc(o.get(O["stage"], "Identified"))} · next touch {when(o.get(O["next"]))}'
        + (' <b style="color:#b3261e">overdue</b>' if day(o[O["next"]]) < today else "") + "</li>") + "</ul>"
    H += f'<h3 style="margin:14px 0 4px;font-size:14px">Gates and milestones within {gate} days ({len(gates)})</h3><ul style="margin:0;padding-left:18px">' + li(gates, lambda g:
        f'<li><b>{esc(g.get(G["id"]))}</b> {esc(g.get(G["name"]))} · {when(g.get(G["date"]))} · owner {esc(g.get(G["owner"]))}</li>') + "</ul>"
    H += f'<h3 style="margin:14px 0 4px;font-size:14px">Posts in the last 24 hours ({len(posts)})</h3><ul style="margin:0;padding-left:18px">' + li(posts, lambda u:
        "<li>" + ('<b style="color:#b3261e">URGENT</b> ' if u.get(U["urgent"]) == "Yes" else "") +
        f'<b>{esc(u.get(U["author"]))}</b> on {esc(u.get(U["about"]))}: {esc(u.get(U["msg"]))}</li>') + "</ul>"
    H += (f'<p style="margin:18px 0 0"><a href="{CONSOLE}" style="color:#1d4e7a">Open the Launch Console</a></p>'
          f'<p style="font-size:12px;color:#7a8697">Cadence and warning windows are set per partner in the console under Notifications.</p></div>')
    subject = (f"AMC daily digest · {partner} · {now_et.strftime('%a %b %-d')} · "
               f"{len(overdue)} overdue, {len(due)} due, {len(touches)} touches")
    return subject, H

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hour", help="Eastern hour to act as, e.g. 07:00 (default: now)")
    ap.add_argument("--to", help="send every digest to this address instead of the partners (test)")
    ap.add_argument("--partner", help="only this partner")
    ap.add_argument("--dry-run", action="store_true", help="print subjects, send nothing")
    ap.add_argument("--data", help="JSON file with the five lists (offline test)")
    a = ap.parse_args()
    now_et = datetime.now(ET)
    hour = a.hour or now_et.strftime("%H:00")
    if a.data:
        data, tok = json.load(open(a.data)), None
    else:
        if not (TENANT and CLIENT and SECRET):
            raise SystemExit("AMC_TENANT_ID, AMC_CLIENT_ID and AMC_CLIENT_SECRET must be set")
        tok = token(); data = load(tok)
    sent = 0
    for row in data["cadence"]:
        partner, cad, email = row.get(C["partner"]), str(row.get(C["daily"]) or "Off"), row.get(C["email"])
        if a.partner and partner != a.partner:
            continue
        if not (a.to or a.hour) and not cad.startswith(hour):
            continue
        if cad.lower().startswith("off") and not a.to:
            continue
        if a.hour and not a.to and not cad.startswith(hour):
            continue
        to = a.to or email
        if not to:
            print(f"{partner}: no email in Cadence row, skipped"); continue
        subject, html = build(partner, row, data, now_et)
        print(f"{partner} -> {to}: {subject}")
        if a.dry_run or tok is None:
            if a.dry_run: open(f"digest_{partner}.html", "w").write(html)
            continue
        send_mail(tok, to, subject, html); sent += 1
    print(f"done, {sent} sent, hour {hour} ET")

if __name__ == "__main__":
    main()
