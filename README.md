# IBM Manufacturing Supply Chain Recovery Decision Agent — Engine

Pure-Python 3 calculation engine (stdlib only) for evaluating supply chain
disruption recovery options.  No external dependencies.

---

## Folder layout

```
IBM-Bibimbab/
├── data/               14 CSV input files (products, orders, inventory, …)
├── engine/             Calculation engine (Python package)
│   ├── loader.py       load_all() — reads and validates all 14 CSVs
│   ├── simulate.py     simulate(actions, disruption_id, db) — day-forward replay
│   ├── evaluate.py     evaluate(sim_result) — KPI summary
│   ├── candidates.py   transferable_qty / purchase_qty_options
│   ├── analysis.py     disruption_impact / priority_view / marginal_cost
│   ├── compare.py      rank_options(options, objective, budget)
│   └── tools.py        Agent-facing API (see below)
├── tests/
│   ├── expected/       Ground-truth CSVs (scenario_summary, order_results, …)
│   ├── test_scenarios.py   5 scenarios × KPI + order results (10 tests)
│   ├── test_candidates.py  transferable_qty and purchase_qty_options (9 tests)
│   ├── test_compare.py     rank_options and compare_scenarios (11 tests)
│   ├── test_analysis.py    disruption_impact, priority_view, marginal_cost (15 tests)
│   └── test_tools.py       All 7 agent tools (29 tests)
├── reference/
│   ├── README.md       Problem description (Korean)
│   ├── data_dictionary.md  Schema reference
│   └── verify.py       Original reference implementation
├── demo.py             End-to-end demo (see below)
└── engine-plan.md      Implementation plan
```

---

## How to run tests

```bash
# Run all 74 tests from the repo root
python3 -m unittest discover -s tests -v

# Run a single test file
python3 -m unittest tests.test_scenarios -v

# Run a single test case
python3 -m unittest tests.test_scenarios.TestScenarioSummary.test_NORMAL -v
```

---

## How to run the demo

```bash
python3 demo.py
```

Prints a step-by-step walkthrough of the full agent tool flow:
disruption details → impact analysis → scenario comparison →
priority view → purchase quantity exploration → action proposal.

---

## Agent tools (`engine/tools.py`)

| Function | Description |
|---|---|
| `get_disruption(disruption_id)` | Disruption details, affected PO, component, and delay days |
| `run_scenario(actions, disruption_id)` | Simulate any action list; returns KPIs + order results |
| `compare_scenarios(budget, objective)` | Rank all 4 disrupted scenarios; NORMAL returned as `baseline` |
| `get_impact(disruption_id)` | WAIT-baseline impact: first late order, C01 shortage by day |
| `get_priority_view(actions, disruption_id)` | Priority-1 order summary and per-customer late days |
| `explore_purchase_qty(offer_id, include_transfers, budget, objective)` | Sweep every valid purchase qty, optionally combined with all transfers |
| `propose_action(scenario_id_or_actions, reason)` | Package a proposal dict — never executes or approves anything |

All functions accept an optional `data_dir` parameter to override the
default `data/` directory.  All return values are JSON-serialisable dicts.

---

## Key design notes

- `simulate()` accepts an explicit **list of actions** (`type: "purchase"` or
  `type: "transfer"`), not a scenario name.  Named scenarios are converted
  to action lists via `build_scenario_actions(scenario_id, db)`.
- `compare_scenarios()` excludes the undisrupted NORMAL scenario from the
  ranking and returns it separately as `result["baseline"]`.
- `best` in `rank_options` / `compare_scenarios` is always a **scenario_id**
  (e.g. `"HYBRID"`); human-readable labels are in the `label` field.
- The engine enforces the inventory floor (`on_hand ≥ reserved + protected`)
  and inventory conservation on every simulation run.
