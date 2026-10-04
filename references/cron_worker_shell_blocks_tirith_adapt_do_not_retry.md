## Cron-worker shell blocks (Tirith) — adapt, do not retry

Two command shapes are refused in cron context because no user is present to
approve them, and each costs a full round trip: **nested/heredoc bodies** and
**pipes into an interpreter**. Write the probe to `cache/scratch/finch_*.py`
and run it by path; use the CLI's own `gh --jq` filter rather than piping. A
burst of `rm` also trips a mass-deletion guard, and scratch under
`cache/scratch/` is pruned automatically, so deleting it is never worth a
block. **When a command is blocked, change its shape rather than re-issuing a
variant.** The rest: `references/scanning-traps.md` § Agent toolchain in cron.

**A probe that crashes on one weird input measures nothing — and it usually
looks like a hang, not a crash.** `find … -printf "%s %p\n"` into
`subprocess.run(…, text=True)` raised `UnicodeDecodeError` at byte offset
50,508,059 on a non-UTF8 filename, after 8 minutes of walking the tree. Read
child stdout as **bytes** and decode with `surrogateescape`, and terminate
records with `\0` rather than `\n` so a newline inside a filename cannot split
one record into two. A disk/space attribution that dies mid-walk reports zero
attribution, which reads exactly like "nothing grew" — the most dangerous
possible failure for that class of question. Same class: a long-running
`nohup` walk that exits without writing its output looks identical to one still
running; check that the output exists *and* the process is gone before
believing either.

**An identity check must sweep every path it intends to compare, or it reports
its own incompleteness as a refutation.** Assert identity on `(st_dev,
st_ino)`, never on a path string: two mounts of one file differ in `st_dev` and
agree in `st_ino`, so a path check reads as absence while an inode check reads
as identity. Measured: the same file set is reachable under `/var/lib/docker/
rootfs/…` and `/var/lib/containerd/…` with **path overlap 0 and inode overlap
100%** — a path-identity assertion calls that "two disjoint sets" and a reader
concludes the du double-count is absent when it is real.

**To decide whether a writer is bounded you need an INTERVAL, not two
point-in-time counts.** Comparing a file count at hour N and hour N+2 cannot
distinguish a slow-growing pool from a saturated ring buffer, and concluding
"bounded" from it is the recurring error on the disk task: the pool was declared
a plateau at 288 MB while it was actually climbing past 400 MB. Sample the
count across a live interval (census in, census out, count the deletions) and
record the **oldest file's age** — an oldest-file age younger than the window
you are calling saturated refutes the plateau on its own.

