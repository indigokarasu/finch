# The honesty label must describe the rate you publish

Measured 2026-10-01 (finch:work #1086) on `finch_disk_watch.py`. General rule:
**a label, a note, or a justification that quotes its own numbers must be
derived from the same window the headline is computed over.** A label over a
narrower window is not a partial label; it is a certificate for a number nobody
was shown.

## The shape

`_pick_anchor()` analysed the sample ring alone:

```
analysis / growth_trend_note : [oldest ring sample ... newest ring sample]
published growth_mb_24h      : [anchor.ts ... now]
```

The gap is the tail between the last saved sample and this reading. Nothing
looked at it. On the real ring the note said:

```
endpoints 18:21:21Z..22:03:05Z (3.70h, +880.6 MB, 13 samples)
```

+880.6 MB over 3.70h normalises to **+5,712.4 MB/24h — MET** against the 5,120
trigger. The headline published **+4,245.4 — UNMET**. Same run, same reading,
two opposite verdicts on whether the gate had fired, and the field a reader
would trust to arbitrate (`growth_window_spans_step=false`) was computed without
the tail.

Two things made it survive review, and both are general:

- **The tail grows with cadence.** A ~30min job on a 4h retention window skips
  samples between runs, so the tail is not a rounding gap — at 30min it is up to
  a quarter of the window. The ring is sparse precisely where the runs are, and
  sparsity is what made the omission look harmless.
- **The tail is where the numerator is decided.** The rate's magnitude is
  `current - anchor` over `now - anchor.ts`; the newest sample contributes
  nothing to the numerator at all. So the one segment not examined is the one
  that sets the number.

The same class as the retired `df -h` rule: never diff or annotate a value
computed over a different window than the one being described.

## What to check, on any instrument with a label and a headline

1. Write the headline's arithmetic down as an interval. If the label's interval
   is not identical, the label cannot verify the headline.
2. Ask what the label *cannot see*. A label over "the data on disk" is blind to
   the gap between the data and the measurement.
3. Quote the derived number inside the note. A note that lets a reader
   recompute the headline is self-checking; one that quotes only a span and a
   delta is not, and that is why the disagreement stayed invisible.
4. The test must be built so it **fails against the old behaviour**, not merely
   against the old signature — see below.

## Mutation-testing the regression (the reusable half)

The first attempt at proving the tests were real was wrong and it is worth
recording. Reverting the whole file made the new tests fail with
`TypeError: _pick_anchor() got an unexpected keyword argument 'current_mb'`.
Five tests errored — and that proves only that the **API changed**, not that the
**behaviour** was wrong. A signature break is a mutant that kills by crashing.

The check that distinguishes them: keep the signature, restore the old
behaviour. One line:

```python
if False:  # MUTANT: signature kept, ring-only analysis restored
    samples = samples + [{"ts": now, "used_mb": float(current_mb)}]
```

That mutant fails 3 of the 5 — the three that assert on *what was measured*.
The two survivors assert on things the pre-fix code already did correctly
(anchor identity, the `current_mb=None` back-compat path), which is why they
pass in both worlds; a suite where every new test dies on a signature change is
not measuring the fix.

Also worth keeping: each fixture asserts a **premise about the old code** in
its own body (`self.assertFalse(spans_ring, "fixture premise: the ring alone
must look clean")`). If someone edits the fixture, the premise assertion fails
loudly instead of the suite quietly measuring nothing.

## Corroboration is a second wording of the SAME question

The ring was read directly, independently of the script, and produced
+4,080.3 MB/24h against the script's published +4,084.0 — a 3.7 MB difference
being the seconds between the last ring sample and the reading. Before the fix
the same two readings were +4,080 vs a published +4,245 with a note implying
+5,712: three numbers, no agreement. **Two metrics that disagree are not
corroboration failing; they are two metrics.** The independent read has to be
the same quantity measured a different way.