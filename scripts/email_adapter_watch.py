#!/usr/bin/env python3
"""Read-only, re-runnable health probe for the <profile> gateway adapter stack.

Answers, with evidence, what a task note cannot:

  1. Is this profile being served by the host gateway at all?
  2. Are the platform adapters that SHOULD be live actually live?
  3. Is a platform factory returning None -- and is that a fault or intended?

Two readings that have each caused a false alarm here, and are handled explicitly:

  * The MULTIPLEX rescan log line "... (N adapter(s) connected)" counts NEWLY BUILT
    adapters on that rescan, not the profile's total. A served profile whose adapter
    is already up reports 0. That is the correct, expected value -- NOT a fault.
    (`gateway/run_adapters.py::_start_one_profile_adapters` skips any platform already
    in `profile_map` or already queued for reconnect, and returns that count.)

  * A platform whose `enabled: false` in config.yaml is INTENTIONALLY off. Its
    factory gate failing (missing EMAIL_* secrets) is a second, independent reason
    and is not itself a fault. Only "enabled AND requirements unmet" is a real fault.

Nothing is written, started, restarted or reconfigured. No secret VALUES are ever
read -- only whether a key is present and non-blank.

Usage:  python3 email_adapter_watch.py [--json] [--quiet]
Exit:   0 = healthy or intentionally disabled, 1 = real fault, 2 = could not measure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def _default_profile() -> str:
    """A script under profiles/<name>/... is inside that profile by construction."""
    m = re.search(r"/profiles/([^/]+)/", str(Path(__file__).resolve()))
    if m:
        return m.group(1)
    return os.environ.get("HERMES_PROFILE") or "<profile>"


PROFILE = os.environ.get("HERMES_PROFILE_NAME") or _default_profile()
HERMES_HOME = Path(os.environ.get("HERMES_HOME")
                   or Path(os.path.expanduser("~")) / ".hermes")
PROFILE_HOME = Path(os.environ.get("HERMES_PROFILE_HOME")
                    or HERMES_HOME / "profiles" / PROFILE)
# The multiplex host gateway lives at the ROOT Hermes home, not the profile home.
HOST_HOME = Path(os.environ.get("HERMES_HOST_HOME") or HERMES_HOME)
HOST_STATE = HOST_HOME / "gateway_state.json"
HOST_LOG = HOST_HOME / "logs" / "gateway.log"

NOT_MEASURED = "NOT MEASURED"


# ── collectors ───────────────────────────────────────────────────────────────
def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return {"__error__": f"could not read {path}: {exc}"}


def load_profile_config() -> dict:
    import yaml
    try:
        return yaml.safe_load((PROFILE_HOME / "config.yaml").read_text()) or {}
    except Exception as exc:  # noqa: BLE001
        return {"__error__": f"could not read config.yaml: {exc}"}


def dotenv_key_presence(env_path: Path) -> dict:
    """Key NAME -> is it set and non-blank. Never returns a value."""
    out: dict = {}
    try:
        for line in env_path.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                key, val = s.split("=", 1)
                out[key.strip()] = bool(val.strip())
    except Exception:  # noqa: BLE001
        pass
    return out


def log_lines(pat: str, tail_bytes: int = 600_000) -> list:
    rx = re.compile(pat)
    try:
        with HOST_LOG.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - tail_bytes))
            data = fh.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return []
    return [ln for ln in data.splitlines() if rx.search(ln)]


# ── checks ───────────────────────────────────────────────────────────────────
def check_serving(cfg: dict) -> dict:
    st = read_json(HOST_STATE)
    if "__error__" in st:
        return {"ok": False, "measured": False, "reason": st["__error__"]}
    served = st.get("served_profiles") or []
    plats = st.get("platforms") or {}

    def state_of(name: str):
        entry = plats.get(f"{PROFILE}:{name}") or plats.get(name) or {}
        return entry.get("state") if isinstance(entry, dict) else entry

    return {
        "ok": PROFILE in served,
        "measured": True,
        "gateway_pid": st.get("pid"),
        "gateway_state": st.get("gateway_state"),
        "served_profiles": served,
        "profile_served": PROFILE in served,
        "adapter_states": {name: state_of(name) for name in ("telegram", "email")},
    }


def check_enabled_platforms_live(cfg: dict) -> dict:
    if "__error__" in cfg:
        return {"ok": False, "measured": False, "reason": cfg["__error__"]}
    want = [k for k, v in ((cfg.get("platforms") or {}).items())
            if isinstance(v, dict) and v.get("enabled")]
    served = check_serving(cfg)
    live = served.get("adapter_states", {})
    missing = [{"platform": n, "state": live.get(n)} for n in want if live.get(n) != "connected"]
    return {
        "ok": not missing,
        "measured": True,
        "enabled_in_config": want,
        "not_connected": missing,
    }


def check_platform_gate(platform: str, required_env) -> dict:
    """Why a factory would return None, and whether that is a fault."""
    if "__error__" in cfg_global:
        return {"ok": True, "measured": False, "reason": cfg_global["__error__"]}
    pc = (cfg_global.get("platforms") or {}).get(platform)
    pc = pc if isinstance(pc, dict) else {}
    enabled = bool(pc.get("enabled"))
    keys = dotenv_key_presence(PROFILE_HOME / ".env")
    present = {k: keys.get(k, False) for k in required_env}
    met = all(present.values())
    if not enabled:
        verdict, ok = "intentionally disabled in config -- NOT a fault", True
    elif not met:
        verdict, ok = "enabled but requirements unmet -- REAL FAULT", False
    else:
        verdict, ok = "enabled and requirements met -- no factory gate blocking", True
    return {"ok": ok, "measured": True, "enabled_in_config": enabled,
            "requirements_met": met, "required_env_present": present, "verdict": verdict}


def check_rescan_reading() -> dict:
    lines = log_lines(r"\[MULTIPLEX\].*adapter\(s\) connected")
    if not lines:
        return {"ok": True, "measured": False,
                "reason": f"no MULTIPLEX rescan lines in the log tail -- {NOT_MEASURED}"}
    zeros = [ln for ln in lines if "(0 adapter(s) connected)" in ln]
    healthy = check_enabled_platforms_live(cfg_global).get("ok")
    return {
        "ok": bool(healthy),
        "measured": True,
        "rescan_lines_in_tail": len(lines),
        "zero_lines": len(zeros),
        "zero_counts": "adapters NEWLY BUILT on that rescan, not the profile's total",
        "verdict": ("0 is the correct expected value -- the enabled adapter is already up"
                    if healthy else
                    "0 may be genuine -- see check_enabled_platforms_live"),
    }


def check_delivery_failures() -> dict:
    """Jobs whose LAST DELIVERY failed. Registry field, not a restatement."""
    try:
        jobs = json.loads((PROFILE_HOME / "cron" / "jobs.json").read_text())
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "measured": False, "reason": f"jobs.json unreadable: {exc}"}
    jobs = jobs.get("jobs", jobs) if isinstance(jobs, dict) else jobs
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    bad = [{"id": j.get("id"), "name": j.get("name"),
            "error": j.get("last_delivery_error"), "next_run_at": j.get("next_run_at")}
           for j in jobs if j.get("last_delivery_error")]
    return {"ok": not bad, "measured": True, "total_jobs": len(jobs),
            "with_delivery_error": bad}


# ── main ─────────────────────────────────────────────────────────────────────
cfg_global: dict = {}

def main() -> int:
    global cfg_global
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg_global = load_profile_config()
    checks = {
        "serving": check_serving(cfg_global),
        "enabled_platforms_live": check_enabled_platforms_live(cfg_global),
        "email_platform_gate": check_platform_gate(
            "email", ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_IMAP_HOST", "EMAIL_SMTP_HOST")),
        "multiplex_rescan_reading": check_rescan_reading(),
        "delivery_failures": check_delivery_failures(),
    }
    # NOT MEASURED must never be reported as PASS -- it is its own state.
    rc = 2 if any(c.get("measured") is False for c in checks.values()) else (
        0 if all(c.get("ok") for c in checks.values()) else 1)
    result = {"profile": PROFILE, "rc": rc, "checks": checks,
              "all_ok": all(c.get("ok") for c in checks.values())}

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return rc
    if not args.quiet:
        print(f"email_adapter_watch: profile={PROFILE}  rc={rc}  "
              f"({'healthy / intentionally disabled' if rc == 0 else 'check checks'})")
        for name, c in checks.items():
            flag = "ok " if c.get("ok") else ("SKIP" if c.get("measured") is False else "FAIL")
            print(f"  [{flag}] {name}: {c.get('verdict') or c.get('reason') or ''}")
            for k, v in c.items():
                if k in ("ok", "verdict", "reason", "measured"):
                    continue
                if v not in (None, [], {}, 0, ""):
                    print(f"         {k} = {json.dumps(v, default=str)[:200]}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
