#!/usr/bin/env python3
"""Negative control for finch_kdp_watch's BODY_CLAIMS vocabulary.

A claim that matches every notice in the corpus is not a signal, it is noise --
it would print KDP_SELECT_ENROLLED on every run forever and be ignored within a
week, which is the exact failure mode the eleven prior passes represent.

The control is therefore the OLD notices: each is fetched and scanned, and the
expected label set is asserted. If the two pre-release notices -- which were
both read in full by a work pass and demonstrably do NOT mention the exclusivity
term -- come back claiming it, the pattern is too loose and must be tightened,
not the expectation relaxed.

The corpus is addressed by SUBJECT + sender rather than by hardcoded message
ids: this repo ships publicly, the PII gate rejects literal thread ids and
host paths, and a frozen id list stops covering the corpus the moment a notice
is delivered. Resolution failure is a failure, not a skip -- a control that
cannot find its fixtures must not report PASSED.

Run:  python3 test_kdp_body_claims.py
      python3 test_kdp_body_claims.py --help
Exit: 0 control passed, 1 control failed, 2 could not measure.

The watcher under test (finch_kdp_watch.py) ships with the ocas-finch skill
repo, not this one, so it is normally ABSENT from a checkout of indigokarasu/
finch. That is an unmeasurable host, not a passing control: this script exits 2
without asserting anything rather than reporting PASSED.
"""
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = os.path.join(HERE, "finch_kdp_watch.py")

# (subject substring, expected-contains, expected-absent)
#
# The exclusivity claim must appear ONLY on the release notice. The other two
# are pre-release notices whose bodies were read in full and contain only the
# final-manuscript line, so they are the negative cases that make a positive
# case mean anything.
CASES = [
    ("available for sale in Kindle Store",
     ["KDP_SELECT_ENROLLED", "DELIVERY_NOTIFIED",
      "CONDITIONAL_RESUBMISSION_NOTICE"],
     # The release notice carries NO manuscript deadline: by then the upload
     # window has closed. If this ever claims one, the deadline pattern has
     # drifted into matching the boilerplate.
     ["MANUSCRIPT_DEADLINE"]),
    ("pre-order is ready",
     ["MANUSCRIPT_DEADLINE"],
     ["KDP_SELECT_ENROLLED", "DELIVERY_NOTIFIED"]),
    ("available for pre-order in Kindle Store",
     ["MANUSCRIPT_DEADLINE"],
     ["KDP_SELECT_ENROLLED", "DELIVERY_NOTIFIED"]),
]

EXCLUSIVITY_LABEL = "KDP_SELECT_ENROLLED"


def load_watcher():
    spec = importlib.util.spec_from_file_location("kdpwatch", WATCH)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % WATCH)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    return w


def resolve(svc, w, subject_substr):
    """Newest message from the watched sender whose subject contains the probe.

    Query-driven, matching the watcher it tests: a hardcoded id set silently
    stops covering the corpus, and a test that asserts against a dead id fails
    for a reason unrelated to the vocabulary under test.
    """
    ids, token = [], None
    while True:
        kwargs = dict(userId="me", q="from:%s" % w.SENDER, maxResults=100)
        if token:
            kwargs["pageToken"] = token
        resp = svc.users().messages().list(**kwargs).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        token = resp.get("nextPageToken")
        if not token:
            break
    for mid in ids:
        m = svc.users().messages().get(userId="me", id=mid,
                                       format="metadata").execute()
        subj = {h["name"].lower(): h["value"]
                for h in m["payload"]["headers"]}.get("subject", "")
        if subject_substr.lower() in subj.lower():
            return mid
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Negative control for finch_kdp_watch's BODY_CLAIMS "
                    "vocabulary. Exits 0 if the exclusivity claim is confined "
                    "to the release notice, 1 if it drifted, 2 if this host "
                    "cannot measure it.")
    ap.parse_args()
    if not os.path.exists(WATCH):
        print("NOT MEASURED: %s is absent from this checkout. The watcher "
              "under test ships with the ocas-finch skill repo." % WATCH)
        return 2
    try:
        w = load_watcher()
    except Exception as exc:  # noqa: BLE001 - report, never traceback
        print("NOT MEASURED: could not load %s (%s: %s)"
              % (WATCH, type(exc).__name__, exc))
        return 2
    if not os.path.exists(getattr(w, "CRED", "")):
        print("NOT MEASURED: watcher credential file absent on this host; "
              "there is no local corpus to assert against.")
        return 2
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=w.load_creds(w.CRED),
                cache_discovery=False)

    failures, seen_claims = [], []
    for probe, must, must_not in CASES:
        mid = resolve(svc, w, probe)
        if mid is None:
            print("%-40s NO FIXTURE FOUND" % probe)
            failures.append("%s: no message from the watched sender matches "
                            "this subject; the control cannot assert anything"
                            % probe)
            continue
        labels = [c[0] for c in w.scan_claims(w.body_text(svc, mid))]
        seen_claims.append(labels)
        print("%-40s %s" % (probe, ", ".join(labels) or "no claims"))
        for need in must:
            if need not in labels:
                failures.append("%s: expected %s, not found" % (probe, need))
        for bad in must_not:
            if bad in labels:
                failures.append("%s: %s SHOULD NOT be claimed (too-loose "
                                "pattern)" % (probe, bad))

    # The exclusivity claim must be confined to exactly one notice. If it is
    # absent everywhere the vocabulary is inert; if it is on two or more the
    # pattern is matching boilerplate and the single most consequential claim
    # in this corpus would be noise.
    exclusivity = [bool(EXCLUSIVITY_LABEL in c) for c in seen_claims]
    print()
    print("exclusivity claim present on %d of %d fixtures (expect exactly 1)"
          % (sum(exclusivity), len(exclusivity)))
    if sum(exclusivity) != 1:
        failures.append("exclusivity claim appears %d times; expected exactly 1"
                        % sum(exclusivity))

    print()
    if failures:
        print("CONTROL FAILED (%d):" % len(failures))
        for f in failures:
            print("  " + f)
        return 1
    print("CONTROL PASSED: the exclusivity claim is confined to the release "
          "notice and absent from both pre-release notices.")
    return 0


if __name__ == "__main__":
    sys.exit(main())