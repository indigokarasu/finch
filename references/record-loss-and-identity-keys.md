# Two ways a sanctioned writer destroys or mis-reads the ledger

Both found live on 2026-10-01 against the real 203-record ledger, while
executing `ledger-scan-notes-overwritten-by-full-doc-write-1058`. They are
written down together because the second one was only findable once the
first was understood: a control that can be silently bypassed is worth less
than one that cannot, and the bypass path was in a different direction than
the defect.

---

## 1. `--doc` is a full replacement, and the clean verdict was the misreport

`finch_ledger_write.py --doc FILE` replaces the entire ledger. Anything the
staged document does not carry is gone.

**Reproduced, not argued.** A `--doc` holding only the header keys:

```
exit=0   tasks 203 -> 0   scan_notes 6 -> 6
VERDICT: WRITTEN CLEAN -- 0 forward, 0 laundered
```

That is the #1058 loss shape (17 scan_notes destroyed on 2026-09-30) at 203
records wide, reachable in one command. Same document after the fix:

```
exit=6   VERDICT: REFUSED -- this --doc would DELETE 203 task record(s) and
         0 scan_note(s) that are on disk right now.
```

**Why no detector found it, which is the part worth keeping.** `forward_count`
and `laundered_count` measure **clock** defects. A destroyed record is not a
clock defect: it leaves no forward stamp and no self-contradiction behind. So
the writer reported clean on a file it had gutted, and every later pass
reading that file would have reported clean too. A destroyed record is
*unfindable after the fact* — the only place to stop it is before the write.
"A clean verdict on a file I just rewrote" is not evidence the content
survived.

### The control: identity, never count

`find_record_loss(incoming, on_disk)` compares:

- **tasks** by `id` — an identity, not a position;
- **scan_notes** by their `(#N)` pass number, falling back to full text for a
  note carrying no pass number.

A count is not a substitute. Measured: dropping one id and adding a different
one holds the count at 203, so a count predicate reads it as a legal write
while a finished task record has been destroyed. Test 30 pins that swap.

A reworded note is the **same** note (identity is the pass number, not the
prose) — test 29 pins both directions. A control that cannot tell a reworded
note from a deleted one would refuse every scan that rewrites its own note,
which is a control that fires constantly and is therefore ignored.

**Refusal, not merge-back.** A document that dropped 203 records has diverged
from the ledger in ways nobody has read; stitching them back would author
prose the tool cannot write. The write stops and a human sees the names.

**Scope: `--doc` only.** `--set tasks` is refused outright and `--task --set`
touches one addressed record, so neither can lose a record. Refusing them here
would fix a `--doc` defect by stopping the ledger (test 31).

---

## 2. The exit-5 control keyed its debt on a LIST INDEX

`find_stale_review_claims` returned hits keyed on `("tasks[i]", id, ...)`. An
index is a *position*, not an identity — and `finch_scan_tasklist_rerank.py`,
a sanctioned writer, calls `tasks.sort(key=rank)` on every invocation.

Measured live (203 tasks, 11 pre-existing self-contradictions):

| mutation | pre-existing hits re-keyed as NEW | writer |
|---|---|---|
| drop one record at index 0 | **11 of 11** | exit 5, refused |
| the sanctioned sort alone | **2 of 11** | exit 5, refused |
| append a new record at the end | 0 | exit 0, written |

The control was refusing legitimate writes over debt it did not author, and
the refusal looked exactly like the honest one. This is the laundering test 25
pins for *reworded prose*, reached through *position* instead — and no care at
the caller prevents it, because sorting is what a re-ranker is for.

**Fix:** the trail is the task id. 0 of 203 live records lack one, and an
id-less record is already unaddressable by `--task`, so it was unkeyed rather
than merely mis-keyed.

**Note the direction.** The shrink guard *adds* a refusal; this *removes* a
false one. Both were needed, and they are not the same kind of change — a
pass that only ever adds controls will eventually refuse correct writes.

---

## Method notes (the parts that cost time)

**Confirm the shape of the bypass before fixing the bug.** The obvious guess —
"reordering alone re-keys the debt" — was **false**: a two-element swap moved
0 keys, exit 0. The shape needed a re-key that actually moves the index, i.e. a
drop or a sort. A cheap two-element probe cost less than patching the wrong
thing.

**A revert that crashes is not a red test.** Reverting the loss check to a
count comparison produced a **syntax error**, so the suite reported 17
failures that were all one crash. `py_compile` is now asserted before any
result from a revert is reported.

**A proof whose failure you cannot read proves nothing.** The discrimination
check itself misfired: `check()` prints `FAIL <name> <detail>`, and I compared
the whole line, so a correct control reported as a mismatch. The controls were
behaving as designed; my extraction was wrong. Compare on prefix, and keep the
detail in the output — it is the evidence.

**In the verifier, three consecutive errors in three lines of timestamp
handling** — a `[:19]` slice that dropped the trailing `Z`, then a regex group
that stripped it while the strptime format still expected it. This is the
class #1058 exists to catch, committed in a throwaway verifier inside the same
session. Read the field with the *writer's* regex rather than re-deriving a
parse; if the value has a suffix, a fixed-width slice is a guess.
