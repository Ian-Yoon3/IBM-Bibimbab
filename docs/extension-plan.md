# Extension plan: uncertain receipt date

Status: stage 1 in progress on `feature/extension-trial-ian`.
The data step is done (commit fbacd91). Loader, worlds module, tool, view and docs follow in that order.
This file is merged into `main` together with stage 1. It is updated as each step is finished.

## Why

The demo fixes the revised receipt date of PO01 at 11-17.
A real delay notice rarely gives one certain date.
The best option changes with the date, so a single date can hide the risk of a choice.

Late orders per receipt date, computed with the current engine (commit f9d5989).

| Option | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | Extra cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WAIT | 0 | 1 | 3 | 4 | 5 | 7 | 7 | 8 | 10 | 10 | 11 | $0 |
| TRANSFER | 0 | 0 | 1 | 1 | 2 | 4 | 4 | 5 | 7 | 7 | 8 | $416 |
| ALT_BUY | 0 | 1 | 1 | 1 | 1 | 3 | 3 | 4 | 6 | 6 | 7 | $1,250 |
| HYBRID | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 2 | 4 | 4 | 5 | $1,306 |

At 11-11 even WAIT gives zero late orders. It then equals the undisrupted NORMAL scenario exactly.
At 11-12 TRANSFER is the cheapest option with zero late orders.
From 11-13 to 11-15 only HYBRID gives zero late orders.
This table needs no weights.

Summary numbers need weights. Two weightings are used.

| Option | Equal weights: expected late / worst / chance of no late order | Triangular weights (ADR 0002): expected late / worst / chance of no late order |
|---|---|---|
| WAIT | 6.0 / 11 / 9.1% | 6.53 / 11 / 1.4% |
| TRANSFER | 3.55 / 8 / 18.2% | 3.73 / 8 / 5.6% |
| ALT_BUY | 3.0 / 7 / 9.1% | 2.99 / 7 / 1.4% |
| HYBRID | 1.55 / 5 / 45.5% | 1.36 / 5 / 35.0% |

Equal weights are the maximum entropy choice when only the range is known.
Triangular weights also use the announced date. They are the stage 1 data. See `docs/decisions/0002-receipt-date-weights.md`.

## Design rules

1. **The engine computes exactly where it can.** One simulation takes about 0.1 ms. Every world is simulated. The engine does not sample.
2. **Monte Carlo is used only where things cannot be counted.** In stage 2 it creates the worlds. It does not run inside the engine.
3. **Time and cost are never merged into one score.** The manager decides how much time is worth how much cost. The engine reports both axes side by side.
4. **The LLM never sets weights.** Weights come from data files.
5. **Each stage is complete on its own.** Stopping after stage 1 is an acceptable result.
6. **Zero probability only for the impossible.** A date that can happen gets a small positive weight, never zero (Cromwell's rule, Lindley 1985).
7. **Belief and what-if are kept apart.** Worlds carry belief. The what-if table covers every date in the simulation window, whatever the worlds are.

## Worlds: the data format shared by all stages

A world is one possible situation. It is a set of overrides on the base data, with a weight.
The base data in `data/*.csv` stays as it is. A value a world does not list keeps its base value.

Two files hold the worlds.

| File | Columns |
|---|---|
| `data/worlds.csv` | `world_id,weight` |
| `data/world_overrides.csv` | `world_id,target_type,target_id,field,value` |

- Weights are positive integers. The engine divides each weight by the total.
- The total has no meaning of its own in stage 1. It is a chosen scale (1000). In stage 2 it is the Monte Carlo sample count. The engine never reads it as a sample size.
- New variables add rows to `world_overrides.csv`, never columns.
- Values inside one world come from one situation. Variables are therefore not assumed independent. A shared cause can move several values together.
- The number of variables is free. The kinds of variables are opened one by one in the engine. A kind that is not open raises an error, so nothing is silently ignored.

| Kind (`target_type`, `field`) | Meaning | Opened in |
|---|---|---|
| `purchase_order`, `receipt_date` | Receipt date of a delayed PO | Stage 1 |
| `offer`, `lead_days` | Lead time of an alternative supplier offer | Stage 3 (planned) |
| `lane`, `lead_days` | Lead time of a transfer lane | Stage 3 (planned) |

Without both files the engine uses one world. That world has the announced `revised_receipt_date` and weight 1. Every result then equals the current result.

## Stage 1. Uncertain receipt date with given weights

### Data (done, fbacd91)

- `data/worlds.csv` and `data/world_overrides.csv`. 11 worlds, one per date from 11-11 to 11-21.
- Weights from a triangular three-point estimate. Earliest 11-11, most likely 11-17, latest 11-21. Reasons and references in ADR 0002.
- `scripts/stage1_triangular_worlds.py` writes the two files. It is temporary. Nothing imports it. It and `tests/test_stage1_triangular_worlds.py` are deleted when stage 2 writes the files.

### Loader

`engine/loader.py` reads the two files, checks them and stores them in `db["worlds"]`. It does not apply them.

- Both files missing gives `db["worlds"] = None`. Only one file present is an error.
- Exact headers.
- `world_id` is non-empty and unique in `worlds.csv`.
- `weight` is an integer of at least 1.
- At least one world.
- Every `world_id` in `world_overrides.csv` exists in `worlds.csv`.
- Every world has at least one override.
- (`target_type`, `field`) must be an open kind. In stage 1 only `purchase_order`, `receipt_date`.
- `target_id` must be a PO named in `disruptions.csv`. The engine reads that PO's receipt date from the disruption.
- No world lists the same target and field twice.
- `value` is read by kind. `receipt_date` is an ISO date.
- A receipt date lies between the PO's planned receipt date and the end of the simulation window. Both come from the data. A later date raises an error that points to stage 2.
- The announced date need not be one of the worlds.
- Errors are `ValueError` and name the file and the `world_id`.

### Worlds module

New module `engine/worlds.py`.

- Applies a world to a copy of `db`. A `receipt_date` override sets `revised_receipt_date` of the disruption on that PO. `db` itself is never changed.
- Simulates every disrupted option in every world with the existing `simulate()` and `evaluate()`. The NORMAL baseline gets no worlds.
- Per option. Extra cost, expected late orders, worst case, chance of no late order. A quantile such as "late orders at or below this number with 90% chance" is under consideration (see open decisions).
- What-if table. Late orders of every option for every date in the simulation window, independent of the worlds.
- Trade-off steps between options in order of cost. Shown as they are, never merged into one score.
- Arithmetic is exact (integers or `Fraction`). Rounding happens once, at output. Differences are taken from exact values, then rounded.

### Tool, view and contract

- One public function in `engine/tools.py`. It is not added to the LLM tool list. `tests/test_agent.py` checks that exactly 8 tools are exposed, and weights never come from the LLM.
- A new `view` in `agent/render.py`, chosen by code from the question text after the proposal and unsupported checks. Existing views stay unchanged.
- `docs/ui-contract.md` gets the new view. UI changes are agreed with the UI owner first.
- A fixture for the new view needs a real watsonx.ai run (Ian only). It also needs the new view type in `EXPECTED_TYPES` of `tests/test_ui_fixtures.py`, in a separate commit.

### Checks

- No world files gives the current results.
- One world on 11-17 gives the current results.
- WAIT on 11-11 equals NORMAL.
- Equal weights give the equal-weights table above.
- The stage 1 data gives the triangular table above.
- Multiplying every weight by the same number changes nothing.
- Every expected value lies between the best and the worst world of that option.

## Stage 2. Worlds from a Monte Carlo engine

- A Monte Carlo engine writes `data/worlds.csv` and `data/world_overrides.csv`. Stage 1 code does not change.
- It keeps random variables, distributions and shared causes inside itself. It writes only sampled outcomes and their counts.
- The model is meant to be rich. Shared causes, conditions such as weekends, and several variables at once.
- The engine reports its own sampling error. The total weight is a sample count only here.
- History records are synthetic in the demo. Real records would replace them.
- Check. With simple independent distributions the exact distribution of the sum can be computed. The sampled weights must converge to it. Tests use a fixed seed and a tolerance.
- First task. Separate the simulation window from the order horizon, so receipt dates after 11-21 can be computed. The window is set in several places today: `HORIZON_DAYS` in `engine/loader.py`, the string `HORIZON_ISO` in `engine/evaluate.py`, and the window check in `engine/simulate.py`. Line 157 of `engine/loader.py` (`DAY0.replace(day=DAY0.day + HORIZON_DAYS)`) is dead code that fails once the horizon passes November 30. It must go.
- The temporary stage 1 script and its test are deleted. ADR 0002 is marked superseded.

## Stage 3. Model refinement

Each item removes one model assumption listed in the README.

- Uncertain lead time for the alternative supplier and the transfer lanes. These open the `offer` and `lane` kinds. `simulate()` already reads both values from `db`, so no simulator change is needed.
- Daily production capacity. This needs a change in the production loop of `engine/simulate.py`.
- Conditional options such as "wait until a date, then buy". The simulator already accepts an `action_date`. A first probe showed that waiting is not attractive with the current data. Due dates come early and OF02 needs 3 days. The result depends on what the manager is assumed to know on the waiting date. That assumption must be stated.
- With several uncertain variables the what-if table cannot cover every combination. It then varies one variable and keeps the others at base values.

## Known limits of the current code

- `analysis.disruption_impact` (`get_impact`) has its own copy of the receipt-date logic. Worlds do not reach it. It reports the impact at the announced date.

## Open decisions

- Stage 1. Whether the worlds module reports a quantile of late orders. Worst case alone is set by the end of the range, because every possible date has a positive weight.
- Stage 1. How the new view looks in the UI. To be agreed with the UI owner.
- Stage 3. Information model for conditional options. Does the manager only learn that PO01 has not arrived, or does the manager receive an updated date?

## References

- Weight rule references (Jaynes 1957, Malcolm et al. 1959, Garthwaite, Kadane and O'Hagan 2005, Law 2015) are in ADR 0002.
- D. V. Lindley, *Making Decisions*, 2nd ed., Wiley, 1985. Standard textbook of Bayesian decision analysis. Source of Cromwell's rule.
- P. Glasserman, *Monte Carlo Methods in Financial Engineering*, Springer, 2003. Standard graduate textbook on Monte Carlo methods, widely cited.
- J. R. Birge and F. Louveaux, *Introduction to Stochastic Programming*, 2nd ed., Springer, 2011. Standard textbook for decisions with recourse under uncertainty, widely cited.
- K. Miettinen, *Nonlinear Multiobjective Optimization*, Kluwer, 1999. Standard textbook for keeping objectives separate (Pareto set, constraint method), widely cited.
