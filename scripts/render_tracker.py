#!/usr/bin/env python3
"""Render the in-flight tracker for people (tracker.md) from Finch's record and Mentor's tags.

No LLM. Finch's tracker.json holds what is in flight; Mentor's project-status.json holds each
project's status. This joins them into one phone-readable page, so the page always shows
Mentor's current tags (an agent run asked to do the join ignored them).

Paths: OCAS_COMMONS (default ~/.hermes/commons). Usage: render_tracker.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

COMMONS = os.environ.get("OCAS_COMMONS", os.path.expanduser("~/.hermes/commons"))
TRACKER = os.path.join(COMMONS, "data/ocas-finch/tracker.json")
STATUS = os.path.join(COMMONS, "data/ocas-mentor/project-status.json")
OUT = os.path.join(COMMONS, "data/ocas-finch/tracker.md")
WORDS = {"in-progress": "In progress", "active": "Active", "maintenance": "In maintenance",
         "waiting-on-external": "Waiting on someone else", "complete": "Finished", "abandoned": "Dropped"}
ORDER = ["waiting-on-owner", "in-progress", "waiting-on-external", "active", "maintenance", "complete", "abandoned"]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


GOOD = TRACKER + ".last-good"


def valid(t):
    return isinstance(t, dict) and all(isinstance(t.get(k), list) for k in ("projects", "inflight", "todos"))


def unwrap(t):
    """An agent once saved a read_file result ({"content": "1|{...", ...}) instead of the record."""
    import re
    if isinstance(t, dict) and isinstance(t.get("content"), str) and "projects" not in t:
        body = "\n".join(re.sub(r"^\s*\d+\|", "", line) for line in t["content"].splitlines())
        try:
            return json.loads(body)
        except ValueError:
            return None
    return None


def guarded_tracker():
    """Return a valid tracker; repair or restore the last good copy when the file is malformed."""
    t = load(TRACKER)
    if not valid(t):
        fixed = unwrap(t)
        if not valid(fixed):
            fixed = load(GOOD)
        if valid(fixed):
            for path in (TRACKER,):
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(fixed, f, indent=1)
                os.replace(path + ".tmp", path)
            print("repaired tracker.json (%s)" % ("unwrapped" if unwrap(t) else "restored last good"))
            t = fixed
        else:
            print("tracker.json invalid and no good copy; rendering projects only")
            return {"projects": [], "inflight": [], "todos": []}
    with open(GOOD + ".tmp", "w", encoding="utf-8") as f:
        json.dump(t, f, indent=1)
    os.replace(GOOD + ".tmp", GOOD)
    return t


def day(ts):
    return (ts or "")[:10] or "?"


def is_waiting_owner(status):
    return status.startswith("waiting-on-") and status != "waiting-on-external"


def recent(ts, days):
    try:
        t = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - t <= timedelta(days=days)


def main():
    tr, st = guarded_tracker(), (load(STATUS).get("projects") or {})
    names = {p.get("id"): p.get("name") for p in tr.get("projects") or []}
    out = ["# In flight", ""]
    waiting = [(pid, s) for pid, s in st.items() if is_waiting_owner(s.get("status") or "")]
    inflight = tr.get("inflight") or []
    w_items = [i for i in inflight if (i.get("state") or "").startswith("waiting_on_") and i.get("state") != "waiting_on_external"]
    if waiting or w_items:
        out += ["## Waiting on you", ""]
        out += ["- **%s**: %s" % (s.get("name") or names.get(pid) or pid, s.get("next_step") or s.get("reason") or "") for pid, s in waiting]
        out += ["- %s (%s, last %s)" % (i.get("title"), i.get("project") or "no project", day(i.get("last_seen"))) for i in w_items]
        out.append("")
    for title, states in (("In progress", ("in_progress",)), ("Blocked or stalled", ("blocked", "stalled"))):
        items = [i for i in inflight if i.get("state") in states]
        if items:
            out += ["## " + title, ""]
            out += ["- %s (%s, last %s)%s" % (i.get("title"), i.get("owner") or "?", day(i.get("last_seen")),
                                             (": " + i["next_step"]) if i.get("next_step") else "") for i in items]
            out.append("")
    todos = [t for t in tr.get("todos") or [] if t.get("status") == "open"]
    if todos:
        out += ["## Todos", ""] + ["- %s (%s)" % (t.get("text"), t.get("owner") or "?") for t in todos] + [""]
    if st:
        out += ["## Projects", ""]
        groups = {}
        for pid, s in st.items():
            status = s.get("status") or "active"
            key = "waiting-on-owner" if is_waiting_owner(status) else status
            if key in ("complete", "abandoned") and not recent(s.get("since"), 7):
                continue
            groups.setdefault(key, []).append((pid, s))
        for key in ORDER:
            if key not in groups:
                continue
            out += ["### " + ("Waiting on you" if key == "waiting-on-owner" else WORDS.get(key, key)), ""]
            for pid, s in sorted(groups[key], key=lambda x: x[1].get("name") or x[0]):
                line = "- **%s**: %s" % (s.get("name") or names.get(pid) or pid, s.get("reason") or "")
                if s.get("route_to") not in (None, "", "none") and not is_waiting_owner(key):
                    line += " (next: %s, with %s)" % (s.get("next_step") or "?", s["route_to"])
                out.append(line)
            out.append("")
    stamp = max(tr.get("as_of") or "", load(STATUS).get("as_of") or "")
    out.append("_Updated %s_" % (stamp[:16].replace("T", " ") or "?"))
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, OUT)
    print("rendered %d projects, %d in flight, %d todos" % (len(st), len(inflight), len(todos)))


if __name__ == "__main__":
    if any(a in ("-h", "--help", "help") for a in sys.argv[1:]):
        sys.stdout.write((__doc__ or "").strip() + "\n")
        sys.exit(0)
    main()
