#!/usr/bin/env python3
"""test_ucsf_mychart_invites.py — fixture tests for the patient-portal watcher.

Fixtures reproduce the *structure* of the real notices (label order, bold-value
markup, trailing boilerplate, ZIP-terminated address) with every name, address,
street, and person genericised. The repo is PUBLIC — a fixture pinning a real
clinic, street address, or calendar entry would publish a fact about someone's
healthcare and schedule. Real-corpus fidelity and the privacy boundary are
compatible: what makes the tests work is the markup shape and field order, not
the values. (Field-order fidelity still matters — see the <strong> defect below.)

Every assertion here pins a defect that was live in the script on 2026-09-26:

  1. A trailing `|` in CARE_CUES (from concatenating an empty $CARE_CUES_EXTRA)
     is an EMPTY ALTERNATIVE and matches every string. The script therefore
     reported unrelated calendar entries ("Coffee Shop, Beach Vacation",
     "Friend's birthday") as booked care. Pin: unrelated events must not match.
  2. The placeholder example.com defaults made the watcher's central query
     return nothing while it printed "Outstanding invites: NONE" and exited 0.
     Pin: unconfigured invocation must exit non-zero.
  3. body_text() harvested only text/plain, so the HTML-only notices decoded to
     ''. Pin: an HTML-only confirmation still yields its Provider field.
  4. The confirmation parser was anchored on raw <strong> tags, which the
     fixed decoder strips. Pin: provider parses from tag-stripped text.
  5. The Location field is ZIP-terminated and followed by cancel/reschedule
     boilerplate that no label delimits. Pin: the field stops at the ZIP.
  6. finch:work #202 (2026-09-27): the fail-loud guard was UNSATISFIABLE. It
     fired on a placeholder sender address that no job, env file, or config ever
     supplied, so the script exited 4 on every invocation -- including the exact
     environment a scheduler gives it. A guard nobody can satisfy is a wall, not
     a guard. Pin: unset scope exits 4, a configured scope exits 0 on a real
     mailbox, and one domain vs several produce the same shape of query.

Run: python3 test_ucsf_mychart_invites.py     (exit 0 = all pass)
"""
import base64
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "ucsf_mychart_invites.py"

FAILS = []
PASSES = []


def check(cond, label):
    if cond:
        PASSES.append(label)
    else:
        FAILS.append(label)
    print("  %s  %s" % ("PASS" if cond else "FAIL", label))


def load(env):
    """Import the watcher fresh under a specific $CARE_CUES_EXTRA."""
    e = {k: v for k, v in os.environ.items()}
    e.update(env)
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(e)
    try:
        spec = importlib.util.spec_from_file_location("portal_inv", SCRIPT)
        assert spec is not None and spec.loader is not None
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        os.environ.clear()
        os.environ.update(old)


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode()


# Genericised stand-ins for the real portal sender and its notices.
PORTAL = "example-portal.org"

print("=" * 78)
print("1. CARE_CUES: the trailing-alternation defect")
print("=" * 78)
m = load({})
check(not m.CARE_CUES.pattern.endswith("|"),
      "pattern has no trailing empty alternative")
for s in ["Coffee Shop, Beach Vacation", "Friend's birthday",
          "Team lunch", "Coffee with a friend"]:
    check(m.CARE_CUES.search(s) is None, "no false match on %r" % s)
for s in ["Riverside Foot & Ankle Center", "One Medical Appointment",
          "Podiatry consult", "Physical therapy", "Orthopedic follow up"]:
    check(m.CARE_CUES.search(s) is not None, "true match on %r" % s)
check(m.CARE_CUES.search("Twofoot Run Club") is None, "'foot' is word-bounded (Twofoot)")

print()
print("=" * 78)
print("2. CARE_CUES_EXTRA: empty must be a no-op, non-empty must be honoured")
print("=" * 78)
m_empty = load({"CARE_CUES_EXTRA": ""})
check(m_empty.CARE_CUES.search("Coffee Shop, Beach Vacation") is None,
      "empty extra -> no change")
m_set = load({"CARE_CUES_EXTRA": "dermatolog|\\bphysio\\b"})
check(m_set.CARE_CUES.search("Dermatology follow up") is not None, "extra cue honoured")
check(m_set.CARE_CUES.search("Physio session") is not None, "second extra cue honoured")
check(m_set.CARE_CUES.search("Coffee Shop, Beach Vacation") is None,
      "extra did not break the base cues")

print()
print("=" * 78)
print("3. body_text: the text/plain-only defect (real notices are HTML-only)")
print("=" * 78)
m = load({"CARE_NOTIFY_DOMAINS": PORTAL})

HTML_ONLY = {
    "mimeType": "text/html",
    "body": {"data": b64(
        "<html><body><p>Date: <strong>Thursday, January 8, 2026</strong></p>"
        "<p>Time: <strong>5:40 PM</strong></p>"
        "<p>Provider: <strong>Provider Northside Urgent Care</strong></p>"
        "<p>Location: <strong>Example Urgent Care Northside</strong></p>"
        "<script>var tracking = 1;</script></body></html>")},
}
txt = m.body_text(HTML_ONLY)
check("Northside Urgent Care" in txt, "HTML-only body decodes the provider")
check("<strong>" not in txt, "tags stripped")
check("tracking" not in txt, "script content removed")
check("&nbsp;" not in txt, "entities unescaped / no literal nbsp")

nested = {"mimeType": "multipart/alternative", "parts": [
    {"mimeType": "text/plain", "body": {"data": b64("plain flavour")}},
    {"mimeType": "text/html", "body": {"data": b64("<p>html flavour &amp; more</p>")}}]}
check("plain flavour" in m.body_text(nested) and "html flavour & more" in m.body_text(nested),
      "multipart yields BOTH flavours")
check(m.body_text({"mimeType": "text/plain", "body": {"data": b64("")}}) == "",
      "genuinely empty body is still empty (not a crash)")

print()
print("=" * 78)
print("4. Confirmation field parsing from tag-stripped text")
print("=" * 78)
flat = re.sub(r"\s+", " ", m.body_text(HTML_ONLY))


def field(name, text):
    """Mirror of the watcher's parser, so the fixture pins the real logic."""
    if name == "Location":
        z = re.search(r"Location:\s*(.+?\b\d{5})(?!\d)", text)
        if z:
            return z.group(1).strip()
    m2 = re.search(rf"{name}:\s*(.+?)(?=\s+[A-Z][A-Za-z]+:|\s*$)", text)
    return m2.group(1).strip() if m2 else None


check(field("Provider", flat) == "Provider Northside Urgent Care",
      "provider parsed: %r" % field("Provider", flat))
check(field("Time", flat) == "5:40 PM", "time parsed: %r" % field("Time", flat))
check(field("Date", flat) == "Thursday, January 8, 2026", "date parsed")
check(field("Location", flat) == "Example Urgent Care Northside",
      "location parsed: %r" % field("Location", flat))

BOILERPLATE = b64(
    "<html><body><p>Location: <strong>Example Urgent Care Northside 100 Example "
    "Ave Fl2 Sample City, CA 94158</strong></p><p>If you wish to cancel or "
    "reschedule your appointment, please click here .</p></body></html>")
flat_bp = re.sub(r"\s+", " ", m.body_text({"mimeType": "text/html", "body": {"data": BOILERPLATE}}))
got = field("Location", flat_bp)
check(got == "Example Urgent Care Northside 100 Example Ave Fl2 Sample City, CA 94158",
      "location stops at the ZIP, excludes boilerplate: %r" % got)

print()
print("=" * 78)
print("5. Portal-scope guard: unconfigured must NOT report a clean mailbox")
print("=" * 78)
env = {k: v for k, v in os.environ.items() if not k.startswith("CARE_")}
env["PATH"] = os.environ.get("PATH", "")
p = subprocess.run([sys.executable, str(SCRIPT), "--acct", "nobody@example.invalid"],
                   env=env, capture_output=True, text=True, timeout=120)
check(p.returncode == 4, "unconfigured run exits 4, got %s" % p.returncode)
check("CARE_NOTIFY_DOMAINS" in p.stderr, "stderr names the variable to set")
check("Outstanding invites: NONE" not in p.stdout,
      "unconfigured run does NOT print a clean-mailbox verdict")

# A placeholder domain that is still in the list is the same defect wearing a
# configured hat -- it must not be treated as a real scope.
p2 = subprocess.run([sys.executable, str(SCRIPT), "--acct", "nobody@example.invalid"],
                    env={**env, "CARE_NOTIFY_DOMAINS": "portal.example.com"},
                    capture_output=True, text=True, timeout=120)
check(p2.returncode == 4, "placeholder domain still exits 4, got %s" % p2.returncode)

print()
print("=" * 78)
print("6. from_clause: one domain and several are the same shape")
print("=" * 78)
m1 = load({"CARE_NOTIFY_DOMAINS": "alpha.health"})
check(m1.NOTIFY_DOMAINS == ["alpha.health"], "single domain parsed")
check(m1.from_clause() == "from:{alpha.health}", "single-domain query: %r" % m1.from_clause())
m2d = load({"CARE_NOTIFY_DOMAINS": "alpha.health, beta.health ,"})
check(m2d.NOTIFY_DOMAINS == ["alpha.health", "beta.health"], "list parsed + trimmed: %r" % m2d.NOTIFY_DOMAINS)
check("OR" in m2d.from_clause() and "beta.health" in m2d.from_clause(),
      "multi-domain query is an explicit alternation: %r" % m2d.from_clause())
m3 = load({})
check(m3.NOTIFY_DOMAINS == [], "unset scope is empty, not a placeholder address")
check("" not in m3.from_clause() or m3.from_clause() == "from:{}",
      "unset scope cannot produce a bare from: (%r)" % m3.from_clause())

print()
print("=" * 78)
print("RESULT: %d passed, %d failed" % (len(PASSES), len(FAILS)))
for f in FAILS:
    print("   FAILED: %s" % f)
sys.exit(1 if FAILS else 0)
