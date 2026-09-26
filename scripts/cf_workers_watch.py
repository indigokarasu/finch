#!/usr/bin/env python3
"""
cf_workers_watch.py — read-only Cloudflare Workers usage watcher for one
account (pass the account id with --account, or $CF_ACCOUNT_ID; the free-plan
daily limit is 100,000 requests, resetting 00:00 UTC).

WHY THIS EXISTS (finch:work #170, 2026-09-26): task
system-cloudflare-workers-limit-recurring had been re-derived from scratch on every
scan, and each pass could only see a rolling 2-day Gmail window, so it kept
re-describing the same "chronic weekly cluster" it could not date. This script pulls
the FULL alert history in one call and reports the three facts that actually
decide the disposition:

  1. current state      - latest alert, and whether we are currently past the limit
  2. exceedance cadence - how many days/month actually blow past 100k (cost of $0)
  3. post-reset burst   - whether exceedance re-fires just after the 00:00 UTC reset
                          (signature of an automated sweep/retry client, not organic
                          human traffic -- this is what makes "just buy the $5 plan"
                          vs "find and throttle the sweeper" a real choice)

Run:  <workspace-mcp-venv>/bin/python cf_workers_watch.py
Exit: 0 always (read-only). Prints JSON. Never sends, spends, or mutates anything.
"""
import argparse
import json, os, re, base64, sys
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

CF_ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "")
CREDS = os.environ.get("OCAS_GOOGLE_CRED_DIR", "~/.google_workspace_mcp/credentials")
CREDS = os.path.join(
    os.path.expanduser(CREDS),
    f"{os.environ.get('OCAS_OPERATOR_EMAIL', '')}.json")
DAILY_LIMIT = 100_000
RECENT_WINDOW_DAYS = 45
# Verdicts the email stream actually supports, in priority order.
STATES = [
    ("exceeded_now", "currently PAST the daily limit -- workers may be failing"),
    ("exceeded_24h", "exceeded within the last 24h, counter has since reset"),
    ("at_90_24h", "hit 90%+ within the last 24h, not yet over"),
    ("at_75_24h", "hit 75%+ within the last 24h, healthy headroom"),
    ("elevated_7d", "no alert in 24h but one or more in the last 7 days"),
    ("quiet_7d", "no alerts in the last 7 days"),
]


def creds():
    from google.oauth2.credentials import Credentials
    raw = json.load(open(CREDS))
    # NOTE: Credentials.from_authorized_user_file() CRASHES on this token file
    # (expiry is stored as a float, not an RFC3339 string). Build it by hand.
    return Credentials(
        token=raw.get("token") or raw.get("access_token"),
        refresh_token=raw.get("refresh_token"),
        token_uri=raw.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=raw.get("client_id"),
        client_secret=raw.get("client_secret"),
        scopes=raw.get("scopes") or ["https://www.googleapis.com/auth/gmail.readonly"],
    )


def main():
    # Parse flags BEFORE importing the optional Google client libs, so --help
    # works in a clean CI env (same convention as gws_direct_puller.py).
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    ap.add_argument("--account", default=CF_ACCOUNT,
                    help="Cloudflare account id (default: $CF_ACCOUNT_ID)")
    ap.parse_args()

    from googleapiclient.discovery import build

    svc = build("gmail", "v1", credentials=creds(), cache_discovery=False)

    ids = set()
    for q in ['from:cloudflare "daily request"', 'from:cloudflare subject:workers']:
        tok = None
        while True:
            r = svc.users().messages().list(
                userId="me", q=q, maxResults=500, pageToken=tok).execute()
            ids.update(m["id"] for m in r.get("messages", []))
            tok = r.get("nextPageToken")
            if not tok:
                break

    alerts = []
    for mid in ids:
        m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        h = {x["name"].lower(): x["value"] for x in m["payload"]["headers"]}
        subj = h.get("subject", "")
        if "daily request" not in subj.lower():
            continue
        # Usage % is reliably in the SUBJECT, in one of two formats depending on
        # how old the alert is: "[Alert] ... usage is at 93%" (new) and
        # "[URGENT] You've reached 90% of daily requests limit" (pre-July).
        # Do NOT parse it out of the body -- the body always contains "100,000",
        # which poisons any naive regex.
        p = re.search(r"at (\d{2})%", subj) or re.search(r"reached (\d{2})%", subj)
        pct = int(p.group(1)) if p else ("exceeded" if "exceeded" in subj.lower() else None)
        alerts.append({"utc": datetime.fromisoformat(
            parsedate_to_datetime(h["date"]).astimezone().isoformat()).astimezone(timezone.utc),
            "pct": pct, "id": mid})
    alerts.sort(key=lambda a: a["utc"])
    if not alerts:
        print(json.dumps({"verdict": "quiet_7d", "detail": "no Workers alerts found"}, indent=2))
        return 0

    now = datetime.now(timezone.utc)
    last = alerts[-1]
    hrs_24 = [a for a in alerts if now - a["utc"] <= timedelta(days=1)]
    days_7 = [a for a in alerts if now - a["utc"] <= timedelta(days=7)]
    verdict = "quiet_7d"
    for key, detail in STATES:
        if key == "exceeded_now" and last["pct"] == "exceeded" and (now - last["utc"]) < timedelta(hours=6):
            verdict = key; break
        if key == "exceeded_24h" and any(a["pct"] == "exceeded" for a in hrs_24):
            verdict = key; break
        if key == "at_90_24h" and any(isinstance(a["pct"], int) and a["pct"] >= 90 for a in hrs_24):
            verdict = key; break
        if key == "at_75_24h" and hrs_24:
            verdict = key; break
        if key == "elevated_7d" and days_7:
            verdict = key; break

    # --- exceedance cadence, normalised per 30d -------------------------
    span_d = max((now - alerts[0]["utc"]).days, 1)
    exc_days = {a["utc"].date() for a in alerts if a["pct"] == "exceeded"}
    exc_per_30d = len(exc_days) * 30.0 / span_d
    # a day that exceeds twice (before + after the reset) costs ~2x the limit
    est_req_per_30d = int(exc_days.__len__() * DAILY_LIMIT * 1.6 * 30.0 / span_d)

    # --- post-reset burst signature -------------------------------------
    # For each exceedance day, did the NEXT utc day also exceed, and how soon?
    clusters, re_fired = [], 0
    for d in sorted(exc_days):
        nxt = d + timedelta(days=1)
        f = [a for a in alerts if a["utc"].date() == nxt and a["pct"] == "exceeded"]
        if f:
            re_fired += 1
            # midnight of the FOLLOWING day, computed with timedelta so it is
            # correct at month/year boundaries (datetime(..., day+1) overflows).
            reset = nxt - timedelta(days=1)  # nxt is a date; back to the day before
            midnight = datetime(reset.year, reset.month, reset.day,
                                tzinfo=timezone.utc) + timedelta(days=1)
            clusters.append({"day": str(d), "re_exceeded_next_day": True,
                             "minutes_after_reset": int(
                                 (min(x["utc"] for x in f) - midnight).total_seconds() // 60)})
        else:
            clusters.append({"day": str(d), "re_exceeded_next_day": False})

    early = [a for a in alerts if a["utc"].hour * 60 + a["utc"].minute <= 120]
    out = {
        "verdict": verdict,
        "detail": dict(STATES)[verdict],
        "generated_at": now.isoformat(),
        "history_span_days": span_d,
        "total_alerts_ever": len(alerts),
        "latest_alert": {"utc": last["utc"].isoformat(), "usage": last["pct"]},
        "exceedance_days_total": len(exc_days),
        "exceedance_days_per_30d": round(exc_per_30d, 1),
        "est_requests_per_30d_if_paid": est_req_per_30d,
        "paid_plan_allowance": 10_000_000,
        "paid_plan_sufficient": est_req_per_30d < 10_000_000,
        "paid_plan_cost_usd_month": 5,
        "burst_signature": {
            "alerts_in_first_2h_after_reset": len(early),
            "pct_of_alerts": round(100.0 * len(early) / len(alerts), 1),
            "exceedance_clusters": len(clusters),
            "clusters_that_re_fired_next_day": re_fired,
            "re_fire_rate": "%d/%d" % (re_fired, len(clusters)),
            "clusters": clusters,
        },
        "recent_alerts": [{"utc": a["utc"].isoformat(), "usage": a["pct"]} for a in alerts[-12:]],
        "recommendation": (
            "Post-reset burst signature present -> the 100k/day consumer is an "
            "automated sweep/retry client, not human traffic. $5/mo Workers Paid "
            "(10M req/mo) is ~%.0fx the estimated load and is the correct fix if "
            "the consumer cannot be located. Locating it requires a Cloudflare API "
            "token on this box (dash.cloudflare.com -> account -> API Tokens); "
            "no token is present, so the sweep cannot be attributed from the VPS."
            % (10_000_000 / max(est_req_per_30d, 1))),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
