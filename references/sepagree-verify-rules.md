# EMAIL-SEPAGREE verify rules (Docusign separation agreement)

`scripts/verify_sepagree_signature.py` is the canonical, maintained verifier for the
EMAIL-SEPAGREE task (separation agreement sign-off). Run it via `terminal` python3 —
NOT `execute_code` (blocked in cron). It counts Docusign "Completed"/signed notices
and cross-checks the negotiation thread, then prints `VERDICT`.

## Canonical copy only

- The maintained script is `skills/ocas-finch/scripts/verify_sepagree_signature.py`.
- STALE DUPLICATE copies may exist at `<fs-root>/sepagree_verify.py` and
  `~/.hermes/profiles/<profile>/commons/data/ocas-finch/sepagree_verify.py`.
  Do NOT run either — they may diverge from the maintained script. If found, delete
  them (they are the stale-drift class this rule exists to prevent).
- **PROHIBITION:** never hand-roll a new `verify-docusign-*.py` into
  `commons/data/ocas-finch/`. A past violation duplicated the canonical script's
  `--since` probe and created exactly the stale-drift risk above. If the probe needs
  a new case, EXTEND the canonical script (add the case + wire `--since`) — never
  author a sibling.

## The load-bearing check

1 Docusign "begin signing" + 0 "Completed" = proof of non-signature. Re-running that
check is the correct finch:work action for the task — do NOT re-derive the script.

## Block-clearance probe

Pass `--since <RFC3339>` to enumerate all Docusign/Kim envelopes in the last 5 days
and report any with `internalDate` AFTER that timestamp (a potential corrected /
Section-3-15 envelope). If none, the external-party blocker is unchanged. The probe
is the canonical replacement for the inline Gmail re-derivation historically done on
the `docusign-separation-agreement` task.

## Locator pattern

To find the verifier (or any skill script) reliably in profile cron context, use
`terminal find /root -iname 'verify_sepagree*' 2>/dev/null` rather than
`search_files`, which returns transient `DaemonThreadPoolExecutor` framework errors.
The same error hits `read_file` in bursts — fall back to `terminal` (`python3` /
`stat`) when it does. `find` is the dependable fallback.
