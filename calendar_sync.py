#!/usr/bin/env python3
"""AMC Launch Console: Outlook calendar sync.

Keeps each partner's own Outlook calendar in step with the lists: the functions
they lead or back up (on the due date), their next owner touches, and every gate
and milestone. Items carry the category "AMC Launch" and a hidden key, so the job
can update or remove them when the lists change and never touches anything else.
"""
import argparse, json, urllib.parse
from datetime import datetime, timedelta
import digest as D

KEY_PROP = "String {66f5a359-4659-4830-9070-00047ec6ac6e} Name AmcKey"
CATEGORY = "AMC Launch"
F, O, G, C = D.F, D.O, D.G, D.C

def all_day(date):  # 'YYYY-MM-DD' -> start/end dicts for an all-day event
    nxt = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return ({"dateTime": date + "T00:00:00", "timeZone": "Eastern Standard Time"},
            {"dateTime": nxt + "T00:00:00", "timeZone": "Eastern Standard Time"})

def desired(partner, data):
    """Events this partner's calendar should hold, keyed by a stable AmcKey."""
    want = {}
    for f in data["functions"]:
        if f.get(F["status"], "Not started") == "Done" or partner not in (f.get(F["lead"]), f.get(F["backup"])):
            continue
        d = D.day(f.get(F["due"]))
        if not d: continue
        role = "lead" if f.get(F["lead"]) == partner else "backup"
        want[f"amc:fn:{f['_id']}"] = dict(date=d, subject=f"[AMC] {f.get(F['id'])} {f.get(F['name'])} due ({role})",
            body=f"Status: {f.get(F['status'], 'Not started')} · {int(f.get(F['pct']) or 0)}%\nLead {f.get(F['lead'])}, backup {f.get(F['backup'])}\n{D.CONSOLE}")
    for o in data["owners"]:
        d = D.day(o.get(O["next"]))
        if o.get(O["assigned"]) != partner or not d: continue
        want[f"amc:touch:{o['_id']}"] = dict(date=d, subject=f"[AMC] Touch: {o.get(O['owner'])} · {o.get(O['prop'])}, {o.get(O['state'])}",
            body=f"Stage: {o.get(O['stage'], 'Identified')}\n{D.CONSOLE}")
    for g in data["gates"]:
        d = D.day(g.get(G["date"]))
        if not d: continue
        kind = (g.get(G["kind"]) or "Gate").lower()
        want[f"amc:gate:{g['_id']}"] = dict(date=d, subject=f"[AMC] {g.get(G['id'])} {g.get(G['name'])} ({kind})",
            body=f"Owner: {g.get(G['owner'])} · {g.get(G['status'], 'Scheduled')}\n{D.CONSOLE}")
    return want

def existing(tok, user):
    """Events on this calendar that carry an AmcKey, as {key: {id, date, subject}}."""
    flt = urllib.parse.quote(f"singleValueExtendedProperties/Any(ep: ep/id eq '{KEY_PROP}' and ep/value ne null)")
    exp = urllib.parse.quote(f"singleValueExtendedProperties($filter=id eq '{KEY_PROP}')")
    url = f"/users/{user}/events?$filter={flt}&$expand={exp}&$select=id,subject,start,isAllDay&$top=200"
    out = {}
    while url:
        j = D.graph(tok, url)
        for e in j["value"]:
            props = e.get("singleValueExtendedProperties") or []
            key = next((p["value"] for p in props if p.get("value", "").startswith("amc:")), None)
            if key: out[key] = dict(id=e["id"], date=(e.get("start") or {}).get("dateTime", "")[:10], subject=e.get("subject", ""))
        url = j.get("@odata.nextLink")
    return out

def payload(key, w):
    start, end = all_day(w["date"])
    return {"subject": w["subject"], "body": {"contentType": "text", "content": w["body"]}, "start": start, "end": end,
            "isAllDay": True, "isReminderOn": False, "showAs": "free", "categories": [CATEGORY],
            "singleValueExtendedProperties": [{"id": KEY_PROP, "value": key}]}

def reconcile(have, want):
    """Return (create, update, delete) lists from what the calendar has and should have."""
    create = [k for k in want if k not in have]
    update = [k for k in want if k in have and (have[k]["date"] != want[k]["date"] or have[k]["subject"] != want[k]["subject"])]
    delete = [k for k in have if k not in want]
    return create, update, delete

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--partner"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--data")
    a = ap.parse_args()
    if a.data:
        data, tok = json.load(open(a.data)), None
    else:
        tok = D.token(); data = D.load(tok)
    for row in data["cadence"]:
        partner, email = row.get(C["partner"]), row.get(C["email"])
        if a.partner and partner != a.partner: continue
        if not email: print(f"{partner}: no email, skipped"); continue
        want = desired(partner, data)
        have = existing(tok, email) if tok else {}
        create, update, delete = reconcile(have, want)
        print(f"{partner} ({email}): {len(want)} wanted, {len(have)} present -> create {len(create)}, update {len(update)}, remove {len(delete)}")
        if a.dry_run or tok is None:
            for k in create[:5]: print("   +", want[k]["date"], want[k]["subject"])
            continue
        for k in create: D.graph(tok, f"/users/{email}/events", "POST", payload(k, want[k]))
        for k in update: D.graph(tok, f"/users/{email}/events/{have[k]['id']}", "PATCH", payload(k, want[k]))
        for k in delete: D.graph(tok, f"/users/{email}/events/{have[k]['id']}", "DELETE")
    print("done")

if __name__ == "__main__":
    main()
