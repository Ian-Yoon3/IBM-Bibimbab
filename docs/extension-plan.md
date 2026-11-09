# Extension plan: uncertain receipt date

Status: planned. Nothing here is implemented yet.
This file lives on `feature/extension-trial-ian` and is merged into `main` together with stage 1.
It is updated as each stage is finished.

## Why

The demo fixes the revised receipt date of PO01 at 11-17.
A real delay notice rarely gives one certain date.
The best option changes with the date, so a single date can hide the risk of a choice.

The table below was computed with the current engine (commit 5f1bd9b).
It uses equal weights for every receipt date from 11-11 to 11-21.

| Option | Extra cost | Expected late orders | Worst case | Late orders at 11-17 |
|---|---|---|---|---|
| WAIT | $0 | 6.0 | 11 | 7 |
| TRANSFER | $416 | 3.5 | 8 | 4 |
| ALT_BUY | $1,250 | 3.0 | 7 | 3 |
| HYBRID | $1,306 | 1.5 | 5 | 1 |

At 11-11 even WAIT gives zero late orders.
At 11-12 TRANSFER is the cheapest option with zero late orders.
From 11-13 to 11-15 only HYBRID gives zero late orders.
The equal weights are an assumption. The worst-case column does not depend on them.

## Design rules

1. **The engine computes exactly where it can.** One simulation takes about 0.1 ms. Every receipt date can be computed, so the engine does not sample.
2. **Monte Carlo is used only where things cannot be counted.** That is the front end in stage 2, where repair and shipping times are continuous.
3. **Time and cost are never merged into one score.** The manager decides how much time is worth how much cost. The engine reports both axes side by side.
4. **The LLM never sets weights.** Weights come from a data file or from the stage 2 engine.
5. **Each stage is complete on its own.** Stopping after stage 1 is an acceptable result.

## Stage 1. Uncertain receipt date with given weights

Input
- New file `data/receipt_date_weights.csv` with columns `disruption_id,receipt_date,weight`.
- Weights are non-negative integers. The engine divides by their sum.
- Dates run from the planned receipt date of PO01 (11-11) to 11-21.
- The loader checks that each disruption exists, dates are unique and inside the range, the total weight is positive, and `revised_receipt_date` is one of the dates.
- Without the file the engine uses `revised_receipt_date` with full weight.

Engine
- Every option is simulated at every date.
- Time axis per option. Expected late orders, worst case, chance of zero late orders.
- Cost axis per option. Extra cost. In the current model it does not depend on the date.
- Trade-off steps between options are shown as they are. Example. TRANSFER to HYBRID costs $890 more and lowers expected late orders by 2.0.

Agent and UI
- A new tool and a new `view` in `agent/render.py`.
- `docs/ui-contract.md` gets the new view. Existing views stay unchanged.
- New fixtures need a real watsonx.ai run. Only Ian can run it for now.
- UI changes are agreed with the UI owner first.

Checks
- Known answer. With full weight on 11-17 every number equals the current results.
- Hand check. With two dates the expected values can be computed by hand.

## Stage 2. Weights from a Monte Carlo engine

- `data_montecarlo_engine.py` samples a repair time and a shipping time from history records. Their sum gives a receipt date.
- It writes `receipt_date_weights.csv` in the stage 1 format. Stage 1 code does not change.
- The history records are synthetic in the demo. Real records would replace them.
- Check. When both histories follow simple distributions, the exact distribution of the sum can be computed. The sampled weights must converge to it. Tests use a fixed seed and a tolerance.
- The sampled dates can fall after 11-21. The simulation window is therefore separated from the order horizon and extended, so those dates are computed instead of rejected.

## Stage 3. Model refinement

Each item removes one model assumption listed in the README.

- Daily production capacity.
- Uncertain lead time for the alternative supplier and the transfer lanes.
- Conditional options such as "wait until a date, then buy". The simulator already accepts an `action_date`, so no simulator change is needed. A first probe showed that waiting is not attractive with the current data. Due dates come early and OF02 needs 3 days. The result depends on what the manager is assumed to know on the waiting date. That assumption must be stated.

## Open decisions

- Information model for conditional options. Does the manager only learn that PO01 has not arrived, or does the manager receive an updated date?
- How the new view looks in the UI. To be agreed with the UI owner.

## References

- P. Glasserman, *Monte Carlo Methods in Financial Engineering*, Springer, 2003. Standard graduate textbook on Monte Carlo methods, widely cited.
- J. R. Birge and F. Louveaux, *Introduction to Stochastic Programming*, 2nd ed., Springer, 2011. Standard textbook for decisions with recourse under uncertainty, widely cited.
- K. Miettinen, *Nonlinear Multiobjective Optimization*, Kluwer, 1999. Standard textbook for keeping objectives separate (Pareto set, constraint method), widely cited.
