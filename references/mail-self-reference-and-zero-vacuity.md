# Mail watchers: self-reference, and proving a zero

Two rules from a 2026-10-02 `finch:work` pass on
`email-wealthfront-routing-number-cutover-oct1`. Neither is specific to that
task; both are defects a watcher over ANY mailbox in this system can have.

## 1. A keyword probe over this mailbox matches FINCH'S OWN OUTPUT

Probing for bank payment declines after a deadline —

    (decline OR declined OR "payment failed" OR "could not be processed"
     OR "payment not processed") after:2026/10/01

— returned **15 rows, every one of them this system's own mail**: finch
briefings, Workday wraps, and an unrelated water-heater thread. A sender
census over the newest 300 messages put finch-authored mail at **41/300**,
with the agent's own sending address the **second most frequent sender (34)**
behind the operator (37).

So a keyword watcher over this mailbox can match **its own self-report about
the thing it is watching**. That inflates every downstream count in the
direction that looks like a live problem — the most expensive direction to be
wrong in.

This is the same evidence class `cron-blocked-config-registry-blind` found in
`cron/output` (a bare grep census whose population **grows as scans talk about
the blocks**), one layer over and in mail.

- **Scope every keyword search by sender**, and exclude self-authored senders
  (the agent's own mailbox address, and the operator's own address).
- **Never quote a bare keyword count** over this mailbox. It names no
  population, and its population includes the instrument.
- Before reporting "N signals" from a keyword search, print the **senders** of
  the hits. One call, and it is the same call that exposes the self-reference.

## 2. A zero must be proved non-vacuous before it is quoted

`from:chase.com after:2026/10/01` returned **0**. Chase is a live sender — 7
messages in the newest 300. An absent sender plus an absent result is exactly
the vacuous negative: "no bank decline notice" is indistinguishable from "the
query matched nothing."

**Run the control first:**

| control | result | meaning |
|---|---|---|
| `from:chase.com` (no date) | 201 | sender term is correct |
| `from:chase.com after:2026/09/15` | 201 | date term is correct |
| `from:chase.com after:2026/10/01` | **0** | **true absence** |

The same triple on `from:wealthfront.com` (201 / 201 / 0). Only after the
control does the 0 become quotable — and only then is "0 confirmed failed" a
measurement rather than an unexamined query result.

This is what the prior pass on that task lacked: it recorded "0 confirmed
failed" from a single query, which was not yet licensed to be called a
measurement. Adding the control is one extra API call and it is the difference
between an absence and a broken query.

**Generalise:** any negative that will appear in a report as a NUMBER
("0 failures", "0 contradictions", "no missed messages") gets a positive
control in the same pass — a wider or differently-worded query that is known
to return rows. If the control returns nothing, the negative is not reportable.

## 3. A subject filter blind to a sibling class hides a contradicting fact

The wealthfront watcher's subject regex matches 8 of 43 rows. The other 35 are
structurally invisible to it, and among them:

    "Your monthly Green Dot statement is available for your Individual Cash
     Account"  — 06-17, 07-17, 08-17, 09-17, then STOPS

The last notice said "2 transactions" on 09-28. A tracker-count watcher reads
a falling count as progress. Monthly account statements — the one class a
payee-level cleanup does **not** affect — still named the OLD bank fifteen
days later. The count answers "did the payee cleanup progress"; the statement
answers "which bank is this account at"; **no single subject filter answers
both.**

- When a watcher filters by subject, **enumerate and name the rows it
  discards.** A corpus of 43 returning 8 is a filter, and the 35 are a
  population somebody should look at at least once.
- Report a disappearing *periodic* class as a finding in its own right: a
  recurring statement that stops is a different signal from a counter that
  stops.
- Recorded honestly: the statement class stopping is **equally consistent**
  with the account having moved to the new bank with its own statements. Mail
  cannot distinguish that from a lapsed notice. Recorded as unverified rather
  than resolved by choosing the likelier reading.