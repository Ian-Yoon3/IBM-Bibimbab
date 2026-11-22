# ADR 0004. One wide worlds file with parameter draws (stage 2)

- **Status:** Accepted
- **Date:** 2026-11-13
- **Branch:** `feature/extension-stage2-ian`
- **Decision owner:** Sunghyuk (Ian) Yoon
- **Design document:** `docs/montecarlo-engine.md`

## Context

Stage 1 stored the worlds in two files.
`data/worlds.csv` held `world_id,weight`.
`data/world_overrides.csv` held one row per changed value, `world_id,target_type,target_id,field,value`.
That long layout suited a file written by hand with a single variable.

Stage 2 changes three things.

1. A program writes the file. The Monte Carlo engine produces every row, so the number of columns no longer costs anyone effort.
2. Each world sets four values at once. These are the receipt date of PO01 and the lead times of OF02, LN01 and LN02 (design document, section 4.1).
3. Every summary number needs an interval. The interval comes from two-level sampling. The outer level draws parameter sets and the inner level draws worlds (design document, section 7.2). Each world must therefore say which parameter draw produced it.

Two files that must agree row by row can also drift apart. One file cannot.

## Options considered

| Option | Layout | Result |
|---|---|---|
| A. Keep two files, add a draw column to `worlds.csv` | Long overrides as today | Rejected. Two files still have to agree, and one world becomes four override rows. |
| B. One wide file with a `draw` column | `world_id, draw, weight, <variable columns>` | Chosen |
| C. One wide file with one weight column per draw | `weight_000, weight_001, ...` | Rejected. Over a hundred columns, mostly zero. |
| D. Wide `worlds.csv` plus a separate `draws.csv` | Two files | Rejected. Brings back the agreement problem. |

## Decision

`data/worlds.csv` is the only world file.

```
world_id,draw,weight,purchase_order.PO01.receipt_date
W001,0,14,2026-11-11
```

Rules enforced by `engine/loader.py`. Every error is a `ValueError` that names the file and, where it applies, the world.

1. No `worlds.csv` means one world at the announced date with weight 1, as before.
2. A leftover `world_overrides.csv` is an error. It is never silently ignored.
3. The header starts with exactly `world_id, draw, weight` and has at least one variable column. Duplicate column names are an error.
4. A variable column is named `<target_type>.<target_id>.<field>`. The pair (`target_type`, `field`) must be an open kind in `_OPEN_KINDS`. A purchase order must be one named in `disruptions.csv`.
5. `world_id` is non-empty and unique. `draw` is an integer of at least 0. `weight` is an integer of at least 1. No cell is empty.
6. Values are parsed by kind. A receipt date keeps the stage 1 bounds.
7. Every draw has the same total weight. The point value pools all rows, and pooling equals the equal-weight average over draws only when the totals are equal.
8. Rows with identical values are allowed. Their weights add up. No code assumes that rows are collapsed.

Inside the engine each world keeps the stage 1 shape plus its draw, `{"world_id", "draw", "weight", "overrides"}`.
`engine/worlds.py` needs no change in logic.

## Also decided for stage 2. No neural acceleration

Neural importance sampling (Müller et al. 2019) was considered for the Monte Carlo engine and rejected.
One evaluation of a world takes about 0.1 ms, and samples collapse into a few hundred distinct worlds.
There is nothing to accelerate at this scale.
Stage 2-1 revisits sample efficiency only if a much larger data set is built (design document, section 9).

## Consequences

- Stage 1 data in the new format gives exactly the ADR 0002 results. WAIT 6.53, TRANSFER 3.73, ALT_BUY 2.99 and HYBRID 1.36 expected late orders, with the same 90th percentiles, worst cases and chances of no late order.
- A test with two draws checks pooling. Draw 0 holds 11-11 and 11-17 with weight 1 each. Draw 1 holds 11-21 with weight 2. The pooled expected late orders are WAIT 7.25, TRANSFER 5.0, ALT_BUY 4.25 and HYBRID 2.75, computed by hand from the per-date table.
- The temporary stage 1 script writes the new format with `draw = 0`.
- The test suite grows from 476 to 498 tests.
- Known gaps, to be closed in step 3. A row with more cells than the header is accepted and the extra cells are dropped. A row with fewer cells is rejected, but the message reports an invalid date instead of a missing cell.
- Intervals per draw are not reported yet. The view computes them in step 6. Until then `evaluate_worlds` reports pooled values only.

## References

- T. Müller, B. McWilliams, F. Rousselle, M. Gross, J. Novák, "Neural Importance Sampling," *ACM Transactions on Graphics* 38(5), 145, 2019. [doi:10.1145/3341156](https://doi.org/10.1145/3341156)
  Peer-reviewed graphics journal, widely cited. Cited only for the option not adopted.
- Two-level sampling and its references are in `docs/montecarlo-engine.md`, section 7.
