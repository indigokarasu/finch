# finch:work Execution Procedures

Step-by-step procedures moved out of `SKILL.md` so they load on demand
rather than on every invocation. Content is unchanged.

| procedure | read it when |
|---|---|
| Signal triage before execution (WORK step) | before acting on any finch:work signal |
| Repeated check-and-close anti-pattern (work execution) | when a task keeps reappearing across runs |
| Task actionability filter (cron context) | when finch:work runs without a user present |
| Pipeline task resumption (ledger/state-based) | when a task was interrupted mid-pipeline |
| Correspondence-thread monitoring (email waiting-tasks) | when verifying an email thread that is awaiting a reply |
| Notification-sender triage (do-not-reply mail) | when a task cites a portal notification as an outstanding action |

### Repeated check-and-close anti-pattern (work execution)

When a task was completed and marked `done`, then re-opened by a subsequent scan for the same unresolved issue, **do NOT run another check-and-close cycle.** After the first re-open, the correct action is decisive resolution or escalation — not re-verifying the same fact.

**Symptoms:**
- Task description says "still NXDOMAIN" / "still unresolved" / "re-opened from prior done status"
- Task was previously marked done with a "checked, found X" work log but the underlying issue persists
- The work log shows N consecutive identical checks with no fix attempted

**Procedure when you encounter a re-opened task:**
1. **Classify the task** — Is this a verification-only task (monitor, check, validate) or an action task (fix, create, configure, deploy)?
   - Verification tasks that are repeatedly re-opened for the same stable condition should be downgraded to `watching` with a note: "Stable state — not actionable." Do not mark `done`; that triggers re-open.
   - Action tasks that were marked `done` without the action being taken should be escalated: the prior closure was premature. Execute the actual fix.
2. **Identify the decisive action** — What single action would close this task permanently? For DNS: create the record. For config: apply the fix. For monitoring: leave as `watching` (not `done`).
3. **Pick decisive execution over verification** — If the task title or description implies an action (e.g., "DNS... unresolved"), invest the first tool call in actually resolving it, not re-verifying. Verification was already done by the prior finch:run or finch:scan.
4. **If genuinely stuck** — Mark the task `watching` with a `blocked_reason` field explaining what's needed to unblock it (e.g., "needs <operator> to choose IP", "requires panel access to provision"). Do NOT mark `done`.

**Rationale:** Three cycles of check-and-close for one unmet DNS record cost ~9 tool calls over 12 hours. One decisive action costs 2 tool calls. The system learns nothing from re-verification; it only learns from resolution.

#### Monitor re-evaluation discipline (work execution)

When a `monitor`/actionable task carries an explicit re-evaluation instruction ("re-evaluate after time T", "apply fix if condition X", "escalate if retry also errors"), the finch:work pass MUST execute the gate against LIVE signal, not the task note:

1. **Read the authoritative live source** (pinned `jobs.json` for cron; direct API for email/calendar) — NEVER decide from the task note's prose, which may be a prior-scan false-positive (see Scanning Gotchas: false-recovery claim).
2. **Compute the gate against current wall-clock.** For a "re-evaluate after 12:50PDT" task, confirm current time is PAST 12:50 before concluding the retry fired. If `next_run_at` is still in the future, the retry has NOT executed — the recurrence condition is UNMET. Record this explicitly; do not infer from the note.
3. **Do NOT apply a preemptive fix.** If the gate is unmet (condition not yet observable), take NO code change — applying a guard "just in case" exceeds the written task and is the same error class as acting on a false note. The correct output is "condition unmet, re-eval next cycle."
4. **Root-cause the error class before deciding.** For interpreter-shutdown, check gateway-restart timing (see Scanning Gotchas) — a pre-restart error is a teardown race, and the next tick is the real test.
5. **Close only on live recovery.** Flip monitor→done only when live signal shows the error cleared (last_status=ok on the post-T tick); never on the note's assertion alone.

**Confirmed 2026-07-24 finch:work (`dispatch-summary-interpreter-shutdown-0724`):** eval ran at 12:33PDT, 17 min before the 12:50 retry; live jobs.json showed `next_run_at` still 12:50 + `last_status` error; the task note's "12:50 retry fired and self-recovered" claim was a false-positive. Gate unmet → no guard applied; monitor retained; discrepancy flagged in the note. This is the model behavior for re-eval-gated monitor tasks.

#### Correspondence-thread monitoring (email waiting-tasks)

For email tasks in a "waiting on a reply" state ("monitor for response", "may need follow-up / scheduling"), verify against the FULL thread, not a single-message search: fetch every message (`users().threads().get(format="full")`) and read the true latest message + who owes the next reply. Crossing replies are common; only the full thread tells you whose court the ball is in. For scheduling threads, pair with a calendar probe (next 14 days) to confirm whether an invite actually exists — the operator's reply does not mean "meeting scheduled". Record the completion signal ("next message from X", "invite sent") in the task note, then STOP: do not re-verify the same stable fact on later runs. A stable user/external-blocked thread is downgraded to `watching` with a `blocked_reason` — not re-checked.

**Timestamp hygiene:** stamp task/journal/decision times from live clock output (`date -u` / `datetime.now(timezone.utc)`) — never compute UTC mentally; mis-stamped reviews (hours in the future) distort freshness ordering and decay logic.

**Draft-authoring gotchas (staging a thread-attached reply; confirmed 2026-09-26):** three distinct failures, each with a different HTTP error — check which one you actually hit before debugging the token.

- **The puller's `id` is a MESSAGE id, not a thread id.** `gws_direct_puller.py` prints `messages.list` ids. Passing one straight into `users().drafts().create(body={"message": {"threadId": <that id>}})` returns HTTP 404 `Requested entity was not found`. Resolve first: `svc.users().messages().get(userId="me", id=MSG_ID, format="metadata").execute()["threadId"]`.
- **Do NOT call `Credentials.from_authorized_user_file()` on the operator token file.** It raises `AttributeError: 'float' object has no attribute 'rstrip'` because `expiry` is persisted as a float epoch rather than an RFC3339 string. Build `Credentials(token=..., refresh_token=..., token_uri=..., client_id=..., client_secret=..., scopes=d.get("scopes"))` from the raw JSON dict — the same shape `gws_direct_puller.py::load_creds` already uses.
- **A draft id is not a message id.** Calling `users().messages().get()` with a draft id (which carries an `r-` prefix) returns HTTP 400 `Invalid id value`. To read draft headers use `users().drafts().get(userId="me", id=<draft id>, format=...)` and read `["message"]["payload"]["headers"]`.

**DRAFT vs SENT label check (mandatory before recording 'reply sent'):** A message from the user's address inside an email thread may be an UNSENT DRAFT — its content can read like a delivered reply. Check `labelIds` on the candidate message: `DRAFT` (or presence in `drafts.list()`) = never sent; `SENT` = sent. Record 'reply sent' only on `SENT`. Confirmed 2026-09-24 (BJAK thread): a work pass logged 'acceptance reply confirmed sent' from draft content; the next ground-truth check (threads.get + drafts.list + label check) found it unsent, corrected the record, and reclassified the task as user-blocked (book + send) rather than awaiting the external party.

**A draft can propagate a FALSE PREMISE across many scans — the misreport compounds, so check it every time.** Confirmed twice more, 2026-09-26:

- A vendor refund ticket: three prior scans recorded "the operator threatened a chargeback if there was no resolution by EOD Friday" as a fact the vendor was defying. The threat was `labelIds=[DRAFT]` only. Because the note asserted it, each later scan re-copied the assertion and added a *reasoning* layer on top ("the deadline passed with the vendor never acknowledging resolution" — implying the vendor ignored an ultimatum). The real state was an unopened draft and a vendor that never saw it. Scan-after-scan compounding turns one label error into a coherent but false story.
- A hiring thread had the same shape at smaller scale: a reply read as `SENT` from draft content.

Rule: when a task's *conclusion* depends on someone having received or sent something, `labelIds` on the specific message is load-bearing — never inherit the assertion from the note. Also sanity-check the *scale* of a complaint: that note said "3 days past the reply" while the thread's first ask was nearly two years earlier. Scans see a 2-day mail window; the underlying dispute is often far older. Pull the full thread or all-time sweep before characterizing a dispute as recent, and before naming a deadline as the decisive one.

#### Notification-sender triage (do-not-reply mail)

A task citing a portal notification (healthcare, banking, scheduling) as an "outstanding action needing a reply" is usually wrong twice over. Before treating one as actionable, run all four checks — each is one API call and each can independently refute the task premise:

1. **Is the sender answerable at all?** `donotreply*`, `no-reply*`, `noreply*` = no reply path exists. Booking/claiming happens in the portal (web/app) or by phone. Any brief that says such a message "needs a reply" is stating a falsehood, and an agent that composes a reply is writing into a black hole. The correct disposition is portal-only, and it is login-walled — never agent-actionable.
2. **Is it still visible, or already dismissed?** Read `labelIds` on the message. `INBOX`/`UNREAD` = outstanding. Neither = the operator already triaged it; the task's "action required" framing is stale. A notification with no `INBOX` label is not a missed item, it is a handled one.
3. **Did a rule hide it, or did the operator clear it?** Enumerate Gmail filters and search for the sender/domain. No matching filter + no `INBOX` label = a deliberate client-side dismissal by the operator. This distinction decides the whole disposition: "operator dismissed it" → routine, downgrade; "a filter hid it" → a real defect worth fixing.
4. **How often does it fire, and is it ever left uncleared?** Query all history for the subject, not just the last 30 days. If every prior instance is also dismissed, the pattern is routine and the priority is misclassified. One unanswered instance is a lead; a 100%-cleared pattern is not.

**If the notice body names no clinic, specialty, or reason** (typical of MyChart-style notices: "you have a new invitation to schedule"), then the request content exists ONLY inside the portal. State this limit explicitly in the work log: an email-side check can report that something is outstanding, never what it is. Inferring a plausible clinical reason from surrounding context and recording it as fact is the failure mode — mark it as an unconfirmed reading, and name the calendar/portal check that would confirm it. Pair with a calendar probe to see whether the care is already booked through another channel, which often makes the invite moot.

**Disposition:** build a re-runnable read-only watcher (invite count + per-invite visibility + filter shadowing + conversion-to-confirmation + care events already on calendar), mark the task `watching` + `anti_churn` with a `re_verify_trigger` naming the specific condition that should re-open it, and hand the login-walled residual to the operator in one line. Do not mark it `done` — that re-opens on the next scan.

**A 100%-cleared pattern means the PRIORITY is misclassified, not that the item is urgent.** Check 4 is the one that decides disposition, and it runs against ALL history, not a 2-day window. Measured 2026-09-26 (`email-edd-ui-inbox-message`): 38 `UI Online Inbox Message Alert`s ever received since 2021, **all 38 dismissed, 0 in INBOX**, 0 of 19 filters touching EDD. The task had sat as an open P3 across 8+ scans, each of which could only restate "still unread" — but it was not unread, and the underlying condition had been stable for five years. A pattern with a 100% dismissal rate is the notification equivalent of a vendor template loop: escalate to `watching` + anti_churn, and let a watcher carry it. Before that, check the *money* risk class from the same sender — EDD also sends certification notices, which have a real consequence if missed, whereas the inbox-message stub names nothing. Distinguish the two by consequence, not by frequency: 25 `Certify` notices, all dismissed, 0 outstanding.

**The alert body may contain ZERO content — record that as a hard limit.** The 09-26 check found the full decoded body of a `UI Online Inbox Message Alert` is verbatim: *"You have a new message in UI Online. Log in to UI Online to view your message."* No subject, no case number, no sender name, no action. So email cannot answer *what* is pending, only *that* something is — and no amount of body-parsing will change that. State the limit; do not infer a plausible subject from surrounding context (e.g. RESEA, benefits) and record the inference as fact.

**Check the ACCOUNT-ORIGIN grant before treating a vendor drip as an inbound invitation.** Confirmed 2026-09-26 (`email-maven-welcome-session`): a task read a marketing drip as a "booking invite" and framed the residual as "the operator's decision whether to participate" — which implies someone invited him. A `from:noreply-accounts@google.com` sweep proved the opposite: he had self-opened the account days earlier via Sign in with Google. The disposition inverts with that one fact: a self-opened account plus a Customer.io bulk broadcast (note the `track.customer.io` unsubscribe token in the body) is a self-service onboarding sequence, not a counterparty waiting on a reply, and "should he use a free onboarding call" is a business judgement rather than an action item. Check origin first; it is one query and it decides the disposition.

**A long-dead vendor relationship in the same domain manufactures false 'engagement'.** The same mailbox held a separate 2022 thread with a senior contact at the same vendor ("Interested in teaching a course?"). A naive `to:<vendor-domain>` sweep returned `OUTBOUND=1` and made it look as though the operator had engaged with the current drip — he never wrote to it. Exclude pre-existing relationship threads by subject from any conversion/outbound counter, or the number reports engagement that does not exist. This is the outbound-side twin of the GMAQL alternation bug below: both produce a confident, wrong count.

**A partially-configured mock makes `.get("nextPageToken")` truthy and hangs the paging loop forever.** Found by fixture-testing a watcher that pages to completion: a bare `MagicMock` hands `.execute()` a truthy mock, so `while True: ... if not tok: break` never breaks — the symptom is a test that times out with NO output, which reads like a hung network call rather than a test defect. Configure the full chain (`svc.users().messages().list.return_value.execute.return_value = {"messages": [], "nextPageToken": None}`) and the same for the calendar service.

**NEVER concatenate a Python regex onto a Gmail query string — scope the sender in GMAQL and filter the subject in Python.** This is the highest-consequence query bug in this file, because a watcher that *under-counts the thing it watches* is worse than no watcher: it manufactures false confidence. Measured 2026-09-26 (`email-elcamino-new-app-linked`): the watcher built `{from:health.org OR from:health.com} <python-regex>`, where the regex contained its own `|`. Gmail's search grammar has no regex — a bare `|` is OR — so the intersection dissolved. The query returned 4 messages, 3 of them from 2022, and **missed the very notice under investigation** (a 2026-09-23 "a new app was linked to your account"). The report was confidently, structurally wrong.

Procedure: query `from:<domain>` (exact, server-side, cheap), then apply `re.search(pattern, row["subject"])` over the subjects you already fetched. The same lesson applies to any alternation in a query — `to:X` plus an OR-term is an additive union, not a filter.

**…and when the `from:` clause already scopes the sender, do NOT ALSO gate on subject keywords.** Confirmed 2026-09-26 (`email-officehours-research-projects`): a watcher for a vendor's research-panel drip gated rows on a keyword tuple (`office hours project`, `paid survey`, …) and, on fixture rows drawn from the real corpus, MISSED genuine panel mail carrying none of the keywords — "Re-connecting on AI Compute Hardware Selection research" (2026-09-21) among them. The subject gate was redundant with a clause that was already exact, and redundancy in a filter is not safety: it is a second way to be wrong. Subject matching is a *disambiguation* tool for broad queries (`subject:"X" newer_than:2d`), never a *narrowing* tool stacked on top of `from:<domain>`. Test the gate's two directions separately — the miss direction is the dangerous one (silent under-count → false confidence) and it is invisible unless the fixtures are built from the real corpus rather than from the pattern.

**Corroborate a watcher's count against a second, differently-constructed query before reporting it.** The under-count was only visible because an unrelated sweep (a plain date-windowed `after:/before:` search) surfaced the missed message. Cheap rule: if a watcher's headline number cannot be reproduced by an independently-worded query, the watcher is wrong, not the corpus.

**A fixture assertion can be wrong even when the code is right — read the failure before patching either one.** Same pass: after fixing the subject gate, an assertion I had written that `is_panel` over-matches still failed. The code was correct; the *assertion* was false — `is_panel` has exactly one defect (missing rows), not two. The fix belonged in the test, and the comment now records that the only defect is the miss direction. Distinguishing the two costs one read of the function. Patching working code to satisfy a wrong assertion is how a correct gate becomes a wrong one, and it would then ship under the banner of a fix.

**Two more live API-shape traps, both hard errors rather than silent no-ops** (confirmed on the same pass):
- `users.settings.filters.list()` takes **no `pageToken`** — it is a single unpaginated call, and it **does** require `userId="me"`; passing either wrong raises a `TypeError` (unexpected keyword, or missing required parameter) at `.execute()`.
- Calendar `events.list()` pagination **cannot** re-derive a cursor from `items[-1]["start"]`: all-day events carry a `"date"` key, not a `"dateTime"`, so `fromisoformat()` on it raises `TypeError: argument must be str`. Use the returned `pageToken`.

**Build the fixture corpus from REAL subject strings, not from the pattern.** Writing tests against the corpus the watcher actually saw caught a second live defect in the same run: the subject regex was missing an entire year of notices ("New Link to your myCare Account", 2022), and the watcher's count moved 4 → 22 the moment it was fixed. A fixture set written from the pattern under test only ever proves the pattern matches itself.

**A security notice class may be routine — check the CADENCE before escalating a single instance.** Two account-link notices in one day reads like a compromise; against the all-time corpus it was ordinary. This task's verdict came from 22 notices spanning 2020–2026, all dismissed, where same-day clusters of 3 had already occurred twice. One instance is not a signal; the question is whether it breaks the established rate.

**When you build a watcher over a mail corpus, sort on the PARSED timestamp — never the raw Date header string.** Confirmed 2026-09-26: `_meta()` returned the header verbatim and `max(rows, key=...)` compared strings, so `'8 Jan 2024 22:15:38 -0800'` beat `'22 Sep 2026 06:24:27 -0700'` lexicographically (`'8' > '2'`). The watcher named a 2024 message as newest while the real newest was 4 days old, i.e. it manufactured a false "stale for years" signal from a healthy mailbox. Use `email.utils.parsedate_to_datetime()`, fall back to `datetime.min` (tz-aware) on unparseable input, and attach UTC to naive headers so the subtraction against `now()` cannot raise. This is the same class as comparing a `df -h` display string for growth (see `finch-scan-pitfalls.md`): **never diff a formatted string where a typed value exists.** Validate against the real corpus before trusting the output — the bug was only visible because the independent MCP pull was compared against the script's answer.


#**A trailing `|` in a compiled alternation matches EVERYTHING — and a placeholder default makes a watcher report a clean mailbox.**

Two defects in the SAME watcher, found on one pass (`scripts/ucsf_mychart_invites.py`, 2026-09-26). They belong together because each produces output that is *plausible, well-formatted, and wrong*, which is the exact condition under which a false negative survives review:

1. **Concatenating a possibly-empty string into a regex alternation.** The pattern ended `...|physical ?therapy" + os.environ.get("CARE_CUES_EXTRA", "")`, so with the variable unset the compiled regex ended in `|`. A trailing `|` is an **empty alternative**, and an empty alternative matches every string. The watcher's `booked_care_events` therefore listed **every** calendar event in the window — "Tokyo Tea Room, Beach Vacation" and "Patrick Leahy's birthday" were reported as booked care — with a sensible-looking count and EXIT 0. Join only non-empty sources; assert the compiled pattern has no dangling `|`.

2. **Placeholder config values produce a confident false clean.** The sender defaulted to `donotreply+mychart@example.com`. Run with the defaults, the watcher's central query matches nothing, and it prints "Outstanding invites: NONE" + EXIT 0 — *while two real invites were open and one real confirmation existed*. Nothing in the output distinguished a misconfigured run from a healthy mailbox. Rule: a tool whose correctness depends on configuration must **fail loud on the unconfigured state** (non-zero exit naming the missing value), never degrade to an empty result. A default value that is a known-unroutable placeholder is a bug, not a convenience.

**…and the fix for that was itself a wall, not a guard (finch:work #202, 2026-09-27).** The obvious repair is a non-zero exit on the placeholder — which is what #199 shipped. It made the *misconfigured* run honest and left the script **completely unrunnable**, because the placeholder was a required value that nothing ever supplied: no cron job in any profile referenced the watcher, and `$CARE_NOTIFY_ADDR` was absent from both `.env` files and both `config.yaml`s. Every invocation returned exit 4, including the exact environment a scheduler supplies. Verified by running it with cron-shaped env (`PATH`/`HOME`/`OCAS_OPERATOR_EMAIL` only): rc=4, empty stdout. Two lessons, both about the guard rather than the defect:

- **A guard that cannot be satisfied is a wall.** Test the unconfigured path *and* the configured path against a real mailbox in the same pass. #199's tests pinned only the unconfigured exit, which is why the wall passed 29 green tests.
- **A placeholder ADDRESS is the wrong shape for a portal.** One health system publishes from several senders — portal notices and billing notices differ in local-part — so an address-shaped variable can only ever cover the mailbox that happens to match. Scope by **domain** (`$CARE_NOTIFY_DOMAINS`, comma-separated, `from:{a OR b}`) as the sibling watchers already do (`$ELCAMINO_DOMAINS`, `$VENDOR_DOMAINS`). Default it to **empty** and let the guard key on "no scope configured": there is no wrong value to type, so the misconfiguration is expressible and therefore fixable. This also deleted `$CARE_BILLING_ADDR`, which was defined, named in the fatal message, and read by **no query at all** — a variable that looked load-bearing and was decorative.

**Corollary, and it bit twice in one pass:** a variable demanded by an error message is not thereby *reachable*. Before shipping a fail-loud guard, grep for who sets the variable it demands (jobs, `.env`, `config.yaml`, systemd timers) and, if nothing does, the guard is a wall. Test the happy path against the real corpus in the same run, not in a later one.

**The related decoder defect, same class as the metadata-only read:** `body_text()` harvested only `text/plain`, but the notices in question are **`text/html`-only**. Every body decoded to `''`, so a content search over them reported "names no clinic / no provider" — a *vacuous* result (nothing was fetched) presented as *evidence* (nothing was found). Always decode both flavours, and when a search over a corpus returns nothing, confirm the corpus was actually populated before recording the negative. A fix that makes a decoder strip tags **breaks parsers that were anchored on those tags** — the confirmation parser here matched `Provider:\s*<strong>([^<]+)` and would have silently returned `None` for every field while still exiting 0. Re-anchor dependent parsers when you change an upstream decode step, and emit an explicit note when a parser finds nothing (`"a confirmation was found but no Provider field parsed"`) so a layout change cannot be read as a content fact.

**Word-boundary nuance when tightening a cue list.** Wrapping every cue in `\b` fixes the empty-alternative class of false match but silently *drops real ones*: `\bpodiatr\b` does not match "Podiatry". Split cues into whole words (`\bclinic\b`) and **stems** (`\bpodiatr`, `\bortho`, which legitimately continue), anchoring stems on the left only. Test the tightening against both directions — an unrelated event must not match AND a real specialty must still match.

### Constructive progress while blocked (work execution)

When a task is blocked on an external party (<operator> login, third-party OAuth, a human decision) but has an the agent-owned executable sub-component, **build that component now** rather than re-verifying the block. This converts a no-op check into durable, reusable tooling.

**Confirmed 2026-07-17 (finch:work, `relay-shutdown`):** The task was blocked on <operator>'s Relay login (actual export needed his credentials). Instead of another "still blocked" check, finch:work authored `verify.py` — a self-contained stdlib verifier that checks every `workflows/*.json` parses as JSON and every `tables/*.csv` has ≥1 data row, exiting non-zero on any failure. It was validated against fixtures (broken JSON / empty CSV / header-only CSV all FAIL; valid data PASSes) and wired into the runbook's step 8. The verifier is reusable the moment <operator> exports — no re-derivation needed.

**Procedure when a task is blocked but has an executable sub-component:**
1. Decompose the task into the blocked part (needs external actor) vs. the autonomous part (the agent can build now).
2. Build the autonomous part as a real, re-runnable artifact (script, fixture, template) — not a status note.
3. Validate it actually works (run it against fixtures / a dry target) before reporting done. A "created script" claim with no execution is the naming-without-fixing anti-pattern.
4. Wire it into the task's runbook/steps so the eventual unblock is one command, not re-analysis.
5. Report the block honestly — the verifier existing does NOT mean the underlying task is complete.

This is the inverse of the check-and-close anti-pattern: instead of burning tool calls re-confirming a stable block, invest them in tooling that makes the eventual execution one-shot.

### Task actionability filter (cron context)

When running as a cron job with no user present, **filter for autonomous actionability** before applying the priority selection. A task is autonomously actionable if it passes ALL of:

- [ ] **No external response required** — doesn't depend on someone else replying (e.g., "track response from X" is NOT actionable; "check if X responded" IS actionable as a monitoring check)
- [ ] **No business decision required** — doesn't require accepting/declining engagements, making commitments, or choosing between options with capital implications (e.g., "respond to consulting inquiry — accept or decline" is NOT actionable)
- [ ] **No authentication required** — doesn't need app login, OAuth, or credentials the agent doesn't have (e.g., "check One Medical app" is NOT actionable)
- [ ] **No user input required** — doesn't need the user to clarify, confirm, or choose

**When all pending tasks fail the actionability filter:** Pick the highest-priority task that CAN be executed (even if low-priority), execute it as a monitoring/validation check, and mark it done with a resolution note. Report that higher-priority tasks are blocked pending user input. This is preferable to returning "no tasks" — at minimum, validate system health signals.

#### Equal-priority tie-break: prefer autonomously-fixable over user-blocked (confirmed 2026-07-26 finch:work)

When several pending tasks share the SAME priority but differ in actionability, the highest-priority rule alone is ambiguous. Break the tie by autonomous-actionability, not by list order:

1. Among same-priority tasks, **prefer one that is autonomously fixable** (a code defect, a path fix, a config correction) over one that is blocked on user action (interactive OAuth, email accept/decline decisions, business commitments). Fix the fixable one this run.
2. **Do NOT mark the user-blocked tasks `done`** and do not silently skip them. Leave them `pending` (or `watching` with a `blocked_reason`) and report them explicitly as blocked pending user input. A `done` status triggers re-open churn; a silent skip hides a real outstanding action from the operator.
3. Report the split clearly: "Executed <fixable task>. Skipped <N> P2 tasks blocked on user action (OAuth, email decisions) — require the operator."

**Confirmed 2026-07-26 finch:work (`cron-praxis-review-filenotfound`):** Task list had FOUR P2 tasks. Three were blocked on user action (Spotify OAuth, Collective2 upgrade decision, GLG/email responses) and ONE was an autonomously-fixable code defect (`praxis:review` FileNotFoundError from a literal `~` in a path). Correct move: execute the code fix now; leave the three user-action tasks pending and name them in the report. Returning "no tasks" would have been wrong — a fixable defect was in scope.

**When a task becomes actionable later** (e.g., <contact-name> replies, <operator> provides input), finch:scan will create a new task or re-activate the existing one. The blocked status is not permanent — it's a reflection of current actionability, not importance.

#### Cascading dependency awareness (confirmed 2026-06-29)

When a critical infrastructure dependency fails, it blocks MANY tasks simultaneously — not just the task that names the failure. Before iterating through each pending task individually, check for cascading blockers:

1. **Identify infrastructure-level blockers first** — If any `critical` task names an infrastructure failure (OAuth revoked, disk full, gateway down, provider outage), assume ALL tasks depending on that infrastructure are blocked until it's resolved.
2. **Map the dependency graph mentally** — OAuth revocation blocks: email tasks, calendar tasks, Drive tasks, Takeout tasks, any task requiring Gmail API. Provider outages block: all LLM-dependent tasks. Disk full blocks: all write operations.
3. **Skip the blocked bulk** — Don't waste time evaluating each email task individually when OAuth is known-dead. Skip the entire dependency cluster in one decision.
4. **Find the first non-dependent task** — Look for tasks that don't depend on the broken infrastructure: cron health monitoring (uses `hermes cron list`, not Gmail), disk checks (`df -h`), system stats, web lookups, non-Google API calls.
5. **Execute the first actionable task** — Even if it's low-priority, a monitoring check that produces a useful signal (e.g., "provider errors recovered") is better than returning "no tasks."

**Confirmed 2026-06-29 (this session):** OAuth revoked (task_019) blocked 6+ email/Gmail tasks simultaneously (task_004, task_005, task_006, task_021, task_012, plus the OAuth task itself). Rather than evaluating each one, the correct move was to recognize the cascade, skip the entire cluster, and pick task_014 (cron provider error monitoring) which only needed `hermes cron list` — no Gmail dependency. **Total impact**: 8/140 cron jobs failed from one OAuth revocation event.

**Key insight:** The actionability filter's 4 conditions are per-task checks. Cascading dependency awareness is a pre-filter that eliminates entire clusters before per-task evaluation. It saves 5-10 tool calls per blocked cluster.

### Pipeline task resumption (ledger/state-based)

When an `in_progress` task involves a data pipeline that uses an idempotency ledger or state file (e.g., Chronicle ingest ledger, corpus processing), the original background process may have died while the pipeline was partially complete. Do NOT re-run from scratch — the ledger tracks completed windows.

**Resumption pattern:**
1. **Verify the process is dead** — `ps -p <PID>` or `ps aux | grep <script_name>`. Confirm the process is actually terminated, not still running silently.
2. **Check the ledger/state** — Read the pipeline's idempotency ledger (SQLite, JSONL, or similar) to determine which work units are already complete.
3. **Compare ledger to source data** — Identify which work units (months, files, batches) from the source data are NOT yet in the ledger.
4. **Run without limits** — The pipeline's ledger-based dedup will skip already-complete units automatically. Running `run_ingest.py --source X --file Y --apply` without `--limit` is safe — it processes only what's missing.
5. **Update task to done** — Once the ledger shows all units processed, mark the task `done` with a resolution noting the final completion timestamp.

**Confirmed 2026-06-29 (task_023):** Background PID 1663225 (Timeline ingest) was dead. Ledger showed 8/10 months complete (through 2026-04). Source data had 10 months (2025-09 through 2026-06). Ran `run_ingest.py --source timeline --file location-history.json --apply` without `--limit` — ledger correctly skipped the 8 completed months, processed 2026-05 and 2026-06 (2 documents written at 07:33Z). Task marked done.

**Key insight:** Pipeline tasks with idempotency ledgers are ALWAYS resumable. The `--limit N` parameter is only needed for initial testing. Once confirmed working, subsequent runs should omit `--limit` so the ledger handles dedup.

**Premature-interruption verification (confirmed 2026-09-11 finch:work):** A task flagged "batch POST never ran / nothing queued" because its CLIENT-SIDE log was empty may actually be fully complete SERVER-SIDE — the client process can die before flushing its log while the server already accepted and processed every batch. Before re-running a resumption pipeline (and especially before incurring a long re-resolution that a resource-constrained environment will kill mid-run), query the SERVER's authoritative store for coverage of the full item set (e.g. by the pipeline's stable key). If every item is present, the task is already done: stop re-POSTing (redundant work), close it with the coverage evidence, and correct the false premise rather than re-running the whole pipeline.

2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Before selecting, check for duplicate task IDs and clean up if found (see `references/duplicate-task-detection.md`). Route findings to MEMORY.md, skill patches, or reference files.
2a. **Sessions scan — correct pattern**: When scanning recent sessions in finch:scan, call `session_search(limit=10, sort='newest')` WITHOUT `query` (FTS5 treats query as literal text, not a time filter — `query="last 24h"` matches sessions containing those words, not recent sessions). Manually check result timestamps. For finch:daily/weekly mining, follow the cron-skew filtering procedure in SKILL.md § "Session source filtering".
3. **Mine** (`finch:daily` / `finch:weekly`) — Process session JSONL files for signals: corrections, directives (Always/Never), course changes, breakthroughs, methodologies, stop signals. See `references/mining_methodology.md` for the full methodology.
4. **Route** — Direct each finding to the optimal storage tier: MEMORY.md (Tier 1: corrections, directives), skill SKILL.md/references/ (Tier 2: tool-usage, service gotchas), reference files (Tier 3: guides, paths, URLs), or Chronicle KG (Tier 4: entity facts). See `references/file-governance.md` for routing criteria and the tier model.
5. **Journal** — Every run emits Action Journal + DecisionRecord to `decisions.jsonl`.

### Signal triage before execution (WORK step)

A task on the list may aggregate multiple distinct failure modes under one title (e.g., "cron 429 errors" that actually mix transient rate limits, script timeouts, and path blocks). Before committing to a fix:

1. **Decompose the task** — List the distinct error signatures from logs/jobs.json. Group by root cause, not by symptom label.
2. **Classify each group** — Transient (will self-resolve), persistent (needs intervention), or already-fixed (mitigation in place).
3. **Handle each group appropriately** — Transient groups get "monitoring" with a 24h recheck. Persistent groups get fixes. Already-fixed groups get a note that the Tier 1 was already applied.
4. **Journal the decomposition** — Record the group counts so the next finch:scan can check recovery per group, not just per task.

Do NOT assume a task with N affected jobs has one root cause. The task title is a scan heuristic, not a diagnosis.

#### Already-fixed verification (resumed investigations)

When a task asks to "resume" or "complete" an interrupted investigation (e.g., "Session identified systemic issues but did not complete fixes"), do NOT assume the fixes are missing. The prior session may have produced findings that were already implemented, or the features may have existed under different names.

**Procedure:** Read the actual code at the relevant file:line locations. Map each claimed-missing feature to a function/class. Check for detection → classification → response → guard completeness. Run existing tests for those features. If all checks pass, mark the task `done` with specific file:line references and test counts as evidence. See `references/already-fixed-verification.md` for the full procedure and an example. For CI-failure tasks on a repo PR/branch, remember a failing run is point-in-time and may already be superseded by a green run on the same head SHA — check the latest run for that SHA before treating it as broken.

#### Cron code-crash fix: the repair may already be uncommitted
When finch:scan flags a cron `last_status=error` with a Python traceback message (e.g. `'tuple' object has no attribute 'get'`), it's a genuine code defect, not transient. The committed (HEAD) version is what failed, BUT a working-tree modification may already repair it (`git status` shows ` M <file>`) — common when an interactive/sibling run patched the file but didn't commit, while the prior cron tick still ran broken HEAD. Procedure:
1. `git status --short` + `git diff HEAD -- <file>` — confirm whether the fix is already present uncommitted before assuming the crash is live.
2. Reproduce against the CURRENT working-tree code with a traceback harness (import `main()`, call inside `try/except: traceback.print_exc()`). OCAS scripts catch `Exception` at the top level and print only `FAIL: ...: <msg>` with NO line number, so `jobs.json` stderr alone won't name the broken line — the harness will.
3. If verified, COMMIT the fix (the fix file only; leave unrelated working-tree modifications uncommitted — they belong to other tasks). An uncommitted patch is fragile under cron: these repos carry many local commits ahead of upstream and get rebased/pulled, which discards or conflicts uncommitted changes, so the next scheduled tick would crash again. Committing makes it durable.
4. Clean verification side-effects: running `main()` appends a row to any append-only log it writes — dedupe to one deterministic row per key (e.g. per date; for mixed-type logs key on `(decision_type, date)`) so the data stays honest.

#### Verify the ACTUAL cron target path before patching (confirmed 2026-07-26 finch:work)

A task description that names a script (e.g. "fix praxis_review.py") is a hint, NOT an authoritative pointer. Multiple copies of the same script can exist across repos, and only ONE is the live cron target. Patching the wrong copy wastes a cycle and leaves the real defect live.

Procedure:
1. **Find the job's real script path from `jobs.json`** — read the job entry (`id`, `name`) and inspect its `last_error` traceback. The traceback's `File ".../scripts/praxis_review.py", line N` is the authoritative target. The `data/scripts/` path or the `prompt`'s `python3 <path>` line can be STALE or point at a nonexistent path.
2. **Grep for all copies** (e.g. `search_files` for `praxis_review.py` under the agent home) — confirm the broken copy is the cron target, and that other copies (e.g. `indigokarasu-*/scripts/`, `gentube-output/` clones) are NOT the ones invoked.
3. **Read the actual target's offending lines** before editing — the description may describe the bug inaccurately (e.g. it may claim line 38, or attribute the tilde to the wrong constant). Trust the live traceback over the task prose.
4. **Patch only the confirmed target**, then verify the constant resolves (see below). Do not "fix" the sibling copies unless they share the identical defect — in the 07-26 case, the two repo copies already used absolute `<fs-root>/.hermes/...` paths and were fine; only the `skills/` copy had the literal `~`.

**Verification (cron-safe):** `execute_code` is BLOCKED under `<profile>` cron (arbitrary-subprocess guard) — use `terminal python3 -c "..."` instead. Resolve the constant and assert: path exists, dir is writable, no literal `~` remains. Do NOT run `main()` to "test" — it appends a real decision row; verification of the constant's resolution is sufficient evidence of the fix.

**Confirmed 2026-07-26 finch:work (`cron-praxis-review-filenotfound`):** The task prescribed "expanduser() DATA_DIR in praxis_review.py." Three copies existed; the cron traceback pinned the live target to `<fs-root>/.hermes/profiles/<profile>/skills/ocas-praxis/scripts/praxis_review.py` (literal `~` at lines 17-18). The two `indigokarasu-*` repo copies already used full paths. Patching the skill copy with `os.path.expanduser()` and verifying via `terminal python3` resolved the FileNotFoundError; next run expected ok.

#### All-transient resolution (no fix needed)

When investigation reveals that ALL errors in a task are transient (provider errors with `consecutive_failures: 0`, missing-module errors where the package is actually installed, interpreter-shutdown errors), the correct action is:

1. **Verify** — Read `jobs.json`, check `last_status`, `last_error`, `consecutive_failures` for each affected job. Do NOT trust the task description alone.
2. **Mark task done** — Set `status: "done"`, add `resolved` timestamp, write `outcome` explaining what was checked and why no fix is needed.
3. **Downgrade priority if misclassified** — If a task was marked HIGH for interpreter-shutdown or provider errors, downgrade to LOW per the error taxonomy.
4. **Journal** — Record the resolution so finch:scan doesn't re-create the task on next scan.

**Confirmed 2026-06-28:** task_019 (provider errors + missing-module) — all jobs showed `consecutive_failures: 0` and `last_status: ok`. googleapiclient was already installed. No intervention required. task_014 (interpreter-shutdown) — also transient, downgraded HIGH→LOW.

MEMORY.md entries decay without reinforcement. During compaction:

1. **Reinforcement check**: For each existing entry, check if it was reinforced (re-encountered or re-applied) since last compaction. Entries reinforced within their expected half-life get a `§` durability marker.
2. **Concept classification**: Classify each entry by storage tier (see `references/forgetting_curve.md` § Storage Tier Model). Is this entry in the right tier?
3. **Tier routing**: Entries in the wrong tier get moved — tool-usage facts to skills (Tier 2), reference details to reference files (Tier 3), entity facts to Chronicle (Tier 4). Only evict if truly stale.
4. **Decay candidates**: Entries not reinforced in 3+ compaction cycles that cannot be routed to another tier are candidates for eviction.
5. **Priority for retention** (Tier 1 only): Directives (Always/Never) > Corrections with causal grounding > Bare corrections > Breakthroughs > Methodologies > Pointers to Tier 2/3 knowledge
6. **Consolidation**: Merge entries that share the same underlying principle into a single entry with multiple contexts. Within-tier only.

See `references/forgetting_curve.md` for the full compaction algorithm including the tier routing procedure.

See `references/scan-work-architecture.md` for signal source details and governance rules.
