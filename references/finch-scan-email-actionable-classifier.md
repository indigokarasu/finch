# finch:scan — Email Actionable Classifier

Reusable noise-domain list + tag scheme for triaging a `newer_than:2d` Gmail
pull inside `finch:scan`. Derived from the 2026-07-22 run (6 pages / 113 unique
messages → 4 new actionable + 2 carried-forward security signals).

The mailbox noise floor is ~100 messages per 2-day window. Without a classifier,
real signals (double-charges, OAuth adds, invites, action-required notices) get
lost. Run this AFTER fetching + parsing all pages (see
`finch-scan-email-batch-parsing.md` for the parse recipe — do NOT re-implement
parsing here).

## Step 1 — Parse all pages first
Loop `search_gmail_messages` with `page_token` until a page returns < `page_size`.
Fetch each page's content via `get_gmail_messages_content_batch`. Normalize the
persisted JSON file with `raw.replace('\\n','\n')` before splitting on
`(?m)^Message ID: ` (the literal-backslash-n trap). Dedupe by Message ID.
113 unique from 6 pages in the reference run; page-1-only would have missed ~60%.

## Step 2 — Noise-domain regex (message is NON-actionable if ANY matches)
Applied to BOTH `From:` and `Subject:` (lower-cased):

```
noreply@, no-reply@, info@, donotreply@, notification@,
@notify, @mailer, @alpaca, capitalone@notification, @amazon,
@compass, @collective2, lululemon, modernismweek, nobull,
impulselabs, flyingblue, @inform.theladders, @recruiting.block,
@myworkday, @hawaiianelectric, @mail.zillow, @g.sh, @openrouter,
@moonshot, @linkedin, @alphasights, @secfi, @maybaum, @jersey,
amazon business, @greenhouse, @workable, @candidates.workable,
@proxyvot, @cloudplatform, @google, doordash, @us.greenhouse,
@hsbc, @venmo, @capitalone, sparkpost, @behive, chatgpt openai,
@email.openai, @store+, @welcome.openrouter, fable, subscription,
promotional credit, birthday sub, scheduled maintenance, password,
security code, one-time password, otp
```

INLINE-SCRIPTING NOTE (from 2026-07-23 scan): if you script this classifier in
`terminal` python (parsing the persisted batch file) rather than reading the MCP
result object directly, capture the **`From:`** header AND `Subject:` before
applying the noise-domain regex — a Subject-only parse misflags sender-noise
threads (Alpaca order-execs, Wealthfront passkeys, GitHub OAuth, Docusign) as
"actionable" and inflates the actionable count ~10x (this scan: 107 false
"actionable" from a Subject-only scan vs the true ~4). The noise-domain list
below keys on sender DOMAINS; without `From:` the filter cannot fire. Always split
on `(?m)^Message ID: ` and regex `From:` + `Subject:` per block.

Note: `capitalone@notification` and `venmo@` are sender-NOISE for their routine
notices, but a Capital One **"charged twice"** subject is still actionable —
handle subject exceptions in Step 3, not by dropping the domain.

## Step 3 — Tag scheme for items that survive Step 2
A message may be sender-noise yet subject-actionable. Apply tags by subject:

| Tag | Trigger (subject contains) | Example |
|-----|----------------------------|---------|
| `SECURITY` | `new sign-in`, `third-party oauth`, `oauth application` | OpenAI sign-in, GitHub OAuth add |
| `FINANCE-REVIEW` | `charged twice`, `double charge`, `unusual charge` | <bank> double-charge |
| `ACTION` | `[action required]`, `transition your` | <service> deprecation notice |
| `INVITE` | `invite`, `dinner`, `private dinner` | <event invite> |
| `CALL` | `tried giving you a call`, `just called` | <callback> |
| `<OWNER>-SENT` | sender is `<user-google-email>` (outbound) | <outbound reply> |
| `REPLY-THREAD` | `re:` + known thread | — |

## Step 4 — Route
- `SECURITY` → update/verify `email-security-verify-*` task (GitHub OAuth needs
  <operator> verify/revoke; OpenAI sign-ins cross-check device/location = legit).
- `FINANCE-REVIEW` / `ACTION` / `INVITE` / `CALL` → NEW task, priority by impact
  (finance = P2, others P3), `status: open`, `blocked_on: <operator>` (agent cannot
  log into banks/calendars/decide engagements).
- `<OWNER>-SENT` / `REPLY-THREAD` outbound → NOT actionable; exclude from tasks.

## Reference run result (illustrative)
- ~100 unique messages per 2-day window across 6 pages; page-1-only would miss ~60%.
- New actionable: <bank> double-charge (P2); <service> deprecation (P4 advisory);
  <event invite> (P3); <callback> (P3).
- Carried forward: <security> OAuth (<operator> verify); <provider> sign-ins
  (<operator>'s own device, legit).
- Excluded as noise: ~20 <broker> order-executed, ~5 <broker>, ~4 <broker>,
  plus generic promotional/social/notification senders (see noise-domain list above).
