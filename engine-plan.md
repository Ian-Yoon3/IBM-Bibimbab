# Engine Implementation Plan — Supply Chain Recovery Decision Agent

## Overview

Build a pure-Python 3 (stdlib only) calculation engine in `engine/` that
reproduces the five validated scenarios in `tests/expected/` from the fourteen
CSVs in `data/`. The engine must expose every capability as agent-callable
functions that return JSON-serialisable dicts. Tests live in `tests/` and use
`unittest`.

**Ground truth:** `reference/verify.py` defines all calculation rules exactly.
The new engine must reproduce its results without copying its hardcoded
expected-value assertions; those move into `tests/`.

**Key design contract:** `simulate()` accepts a *list of action dicts* (not a
scenario name). The five named scenarios are simply pre-defined action lists
built from the CSV data. This lets an AI agent construct arbitrary action
combinations and evaluate them on the fly.

---

## Module Dependency Order

```
loader.py
    └── simulate.py
            ├── evaluate.py
            ├── candidates.py
            └── analysis.py
                    └── compare.py
                            └── tools.py
```

Tests are added after each module is written.

---

## Sub-Task 1 — `engine/loader.py`

**Status:** [ ] pending

### Intent
Provide a single `load_all()` function that reads all 14 CSVs from `data/`
relative to the caller's working directory (project root) and returns
structured, validated Python dicts. All downstream modules call this once and
pass the result around — no module reads CSV directly.

### Expected Outcomes
- `load_all()` returns a dict with keys matching the 14 CSV base-names.
- Every FK reference is validated; missing or duplicate PKs raise `ValueError`.
- `scenarios.disruption_id` is the only nullable field; all other fields are
  required.
- Integer fields are stored as `int`, dates as `datetime.date`, strings as `str`.
- A `floor` sub-dict is pre-computed: `floor[warehouse_id][component_id] =
  reserved_qty + protected_qty`.
- A `queue` list is pre-computed: orders sorted by
  `(due_date, priority_rank, order_id)` → must equal `[SO01…SO12]`.
- A `needs` dict is pre-computed: `needs[order_id][component_id] = qty_per_unit
  × order_qty` (BOM × order qty for each component the product uses).

### Todo List
1. Create `engine/__init__.py` (empty).
2. Create `engine/loader.py` with:
   - `_load_csv(name)` → list of raw dicts (uses `csv.DictReader`; paths
     relative to `Path.cwd() / "data"`).
   - `_parse_int(v, field)` → int, raises `ValueError` if < 0.
   - `_parse_date(v, field)` → `datetime.date`.
   - `load_all()` → dict containing all validated, typed sub-dicts plus `floor`,
     `queue`, and `needs`.
3. Validate every FK/PK/constraint from `data_dictionary.md` with `ValueError`
   (not `assert`).
4. Confirm `queue == ["SO01", ..., "SO12"]`.
5. Confirm `gross C01 needs == 163` using `needs`.

### Relevant Context
- `reference/verify.py` lines 12–90 contain the original load + validation logic.
- `data/inventory.csv` has 15 rows (3 warehouses × 5 components); all must be
  present.
- `scenarios.disruption_id` empty string should become `None`.
- `bom` only contains 12 of the 15 possible product-component pairs; missing
  pairs have qty 0.

---

## Sub-Task 2 — `engine/simulate.py`

**Status:** [ ] pending

### Intent
Implement `simulate(actions, disruption_id, db)` which is the core day-forward
replay engine. It takes an explicit list of action dicts and an optional
disruption ID, and returns a detailed result dict (JSON-serialisable). All
hardcoded expected-value checks are removed; the function just computes.

### Function Signature

```python
def simulate(
    actions: list[dict],
    disruption_id: str | None,
    db: dict
) -> dict:
    ...
```

**`actions`** — each action is one of:
```python
# Purchase action
{"type": "purchase", "offer_id": str, "warehouse_id": str,
 "action_date": str, "qty": int}

# Transfer action
{"type": "transfer", "lane_id": str, "component_id": str,
 "action_date": str, "qty": int}
```

`action_date` is an ISO string (`"YYYY-MM-DD"`); `simulate()` converts it to
`datetime.date` internally.

**Return value:**
```python
{
  "order_results": [
    {
      "order_id": str,
      "product_id": str,
      "qty": int,
      "due_date": str,          # ISO
      "c01_required": int,
      "start_date": str,        # ISO
      "delivery_date": str,     # ISO
      "days_late": int
    }, ...                      # 12 entries, one per order
  ],
  "purchase_cost": int,
  "transfer_cost": int,
  "total_extra_cost": int,
  "end_inventory": {            # on_hand_qty after simulation
    "WH01": {"C01": int, ...},  # 3 warehouses × 5 components
    "WH02": {...},
    "WH03": {...}
  },
  "ledger": [
    {
      "date": str,
      "event_type": str,        # PO_RECEIPT | ALT_RECEIPT | TRANSFER_OUT
                                #  | TRANSFER_IN | PRODUCTION_ISSUE
      "reference_id": str,
      "warehouse_id": str,
      "component_id": str,
      "signed_qty": int,
      "on_hand_after": int
    }, ...
  ]
}
```

### Calculation Rules (from verify.py)
1. **Queue:** from `db["queue"]` — pre-sorted `[SO01…SO12]`.
2. **Events scheduling:**
   - PO receipts: use `revised_receipt_date` if disruption applies, else
     `planned_receipt_date`.
   - ALT_RECEIPT: `action_date + offer.lead_days`.
   - TRANSFER_OUT on `action_date`; TRANSFER_IN on `action_date + lane.lead_days`.
3. **Daily loop** `for offset in range(13)` (DAY0 to HORIZON inclusive):
   - Process all events for `today`, sorted by `qty` descending (largest
     receipts first).
   - Then iterate the order queue: if all components satisfy
     `stock[wh][c] - floor[wh][c] >= needs[oid][c]`, deduct all and record
     start. Break on first order that cannot start.
4. **Floor constraint:** after every stock mutation, `stock[wh][c] >=
   floor[wh][c]`; raise `RuntimeError` if violated.
5. **Costs:** purchase cost = `unit_cost × qty + fixed_fee` per purchase action;
   transfer cost = `unit_cost × qty + fixed_fee` per lane used (grouped by
   lane_id, not by individual transfer row — but the data only has one row per
   lane per scenario, so cost is per-row).
6. **Inventory conservation:** verified internally; raise `RuntimeError` if
   violated.

### Expected Outcomes
- `simulate([], "D01", db)` reproduces WAIT scenario results exactly.
- `simulate([], None, db)` reproduces NORMAL results exactly.
- Return dict passes `json.dumps()` without error.

### Todo List
1. Write `engine/simulate.py` implementing the rules above.
2. No hardcoded expected values — pure computation only.
3. Dates in return dict are ISO strings (`str`), not `date` objects.
4. Validate purchase actions against offer constraints (`min_qty`, `multiple_qty`,
   `max_qty`) and raise `ValueError` on violation.
5. Validate transfer actions against `lane.max_qty` (per-lane total) and raise
   `ValueError` on violation.

### Relevant Context
- `reference/verify.py` lines 108–201 contain the full `simulate()` logic.
- `in_transit` counter: key is `(lane_id, component_id)`; starts at 0, decremented
  by TRANSFER_OUT (negative qty added), incremented by TRANSFER_IN. Final value
  must be 0.
- Events on the same day sorted by `qty DESC` (line 169 of verify.py uses
  `sorted(events[today], key=lambda x: -x[2])`).
- All orders use `WH01` as the production warehouse.

---

## Sub-Task 3 — `engine/evaluate.py`

**Status:** [ ] pending

### Intent
Compute the KPI summary for a simulation result. This is a thin calculation
layer over a `simulate()` return value — no simulation logic here.

### Function Signature

```python
def evaluate(sim_result: dict) -> dict:
    ...
```

**Return value:**
```python
{
  "on_time_orders": int,
  "on_time_units": int,
  "orders_completed_by_horizon": int,
  "total_order_days_late": int,
  "max_order_days_late": int,
  "purchase_cost": int,
  "transfer_cost": int,
  "total_extra_cost": int,
  "end_c01": {"WH01": int, "WH02": int, "WH03": int}
}
```

**Rules:**
- `on_time_orders` = count of orders where `days_late == 0`.
- `on_time_units` = sum of `qty` for orders where `days_late == 0`.
- `orders_completed_by_horizon` = count of orders where `delivery_date <=
  "2026-11-21"`.
- `total_order_days_late` = sum of `days_late` (no quantity weighting).
- `max_order_days_late` = max of `days_late`.

### Expected Outcomes
- `evaluate(simulate([], "D01", db))` returns WAIT row from
  `tests/expected/scenario_summary.csv` exactly.

### Todo List
1. Write `engine/evaluate.py` with `evaluate(sim_result)`.
2. No external imports beyond stdlib.

---

## Sub-Task 4 — `engine/candidates.py`

**Status:** [ ] pending

### Intent
Two utility functions that enumerate valid action parameters without running a
simulation. These are used by the AI agent to understand what it *can* do before
deciding what to do.

### Function Signatures

```python
def transferable_qty(lane_id: str, component_id: str, db: dict) -> dict:
    ...

def purchase_qty_options(offer_id: str, db: dict) -> dict:
    ...
```

**`transferable_qty` return value:**
```python
{
  "lane_id": str,
  "component_id": str,
  "from_warehouse_id": str,
  "to_warehouse_id": str,
  "available_at_source": int,   # on_hand - reserved - protected
  "lane_max_qty": int,
  "transferable_qty": int        # min(available_at_source, lane_max_qty)
}
```

**`purchase_qty_options` return value:**
```python
{
  "offer_id": str,
  "component_id": str,
  "supplier_id": str,
  "lead_days": int,
  "unit_cost_usd": int,
  "fixed_fee_usd": int,
  "min_qty": int,
  "multiple_qty": int,
  "max_qty": int,
  "valid_quantities": [int, ...]   # all valid qtys: min_qty, min+step, ..., max_qty
}
```

### Expected Outcomes
- `transferable_qty("LN01", "C01", db)["transferable_qty"] == 18`
- `transferable_qty("LN02", "C01", db)["transferable_qty"] == 14`
- `purchase_qty_options("OF02", db)["valid_quantities"]` contains `[20, 25, 30, 35, 40, 45, 50, 55, 60, 65]`.

### Todo List
1. Write `engine/candidates.py` with both functions.
2. `valid_quantities` uses `range(min_qty, max_qty + 1, multiple_qty)`.

---

## Sub-Task 5 — `engine/analysis.py`

**Status:** [ ] pending

### Intent
Three read-only analysis functions that extract insight from the data or from
a simulation result without running a new simulation.

### Function Signatures

```python
def disruption_impact(disruption_id: str, db: dict) -> dict:
    ...
    # (A) Simulates WAIT (actions=[], disruption=disruption_id) internally,
    # then reports first late order and C01 shortage by day.

def priority_view(sim_result: dict, db: dict) -> dict:
    ...
    # (C) Filters sim_result for orders with priority_rank == 1,
    # and groups late days by customer_id.

def marginal_cost(evaluated_options: list[dict]) -> dict:
    ...
    # (E) Given a list of {scenario_id/label, on_time_orders, total_extra_cost},
    # computes cost per incremental on-time order between adjacent options.
```

**`disruption_impact` return value:**
```python
{
  "disruption_id": str,
  "first_late_order_id": str,
  "first_late_days": int,
  "c01_shortage_by_day": [
    {"date": str, "c01_available": int, "c01_cumulative_needed": int,
     "shortage": int}, ...
  ]
}
```

**`priority_view` return value:**
```python
{
  "priority_1_orders": [
    {"order_id": str, "customer_id": str, "due_date": str,
     "days_late": int, "qty": int}, ...
  ],
  "customer_impact": {
    "CU01": {"orders": int, "late_orders": int, "total_late_days": int},
    ...
  }
}
```

**`marginal_cost` return value:**
```python
{
  "steps": [
    {"from_label": str, "to_label": str,
     "extra_on_time_orders": int,
     "extra_cost_usd": int,
     "cost_per_order_usd": float | None}, ...
  ]
}
```
`cost_per_order_usd` is `None` when `extra_on_time_orders == 0`.

### Todo List
1. Write `engine/analysis.py` with all three functions.
2. `disruption_impact` must call `simulate([], disruption_id, db)` internally
   to get the WAIT baseline.
3. `priority_view` joins `sim_result["order_results"]` with
   `db["orders"][oid]["priority_rank"]` and `db["orders"][oid]["customer_id"]`.
4. `marginal_cost` sorts the input list by `on_time_orders` ascending before
   computing steps.

---

## Sub-Task 6 — `engine/compare.py`

**Status:** [ ] pending

### Intent
Rank a set of pre-evaluated options by a chosen objective, with an optional
budget ceiling.

### Function Signature

```python
def rank_options(
    options: list[dict],     # list of evaluate() return dicts, each with "label" key added
    objective: str,          # "on_time_orders" | "on_time_units" |
                             # "total_late_days" | "max_delay" | "cost"
    budget: int | None = None
) -> dict:
    ...
```

**Return value:**
```python
{
  "objective": str,
  "budget": int | None,
  "ranked": [
    {"rank": int, "label": str, "score": int | float,
     "on_time_orders": int, "total_extra_cost": int}, ...
  ],
  "best": str   # label of rank-1 option
}
```

**Ranking rules:**
- `on_time_orders`, `on_time_units`: higher is better.
- `total_late_days`, `max_delay`, `cost`: lower is better.
- `budget` filter: exclude options where `total_extra_cost > budget` before
  ranking. If no options survive, return `"best": null`.
- Ties: keep original order.

### Expected Outcomes
- `rank_options(options, "on_time_orders", budget=500)["best"] == "TRANSFER"`
- `rank_options(options, "on_time_orders")["best"] == "HYBRID"`

### Todo List
1. Write `engine/compare.py` with `rank_options`.
2. Validate objective string against allowed values; raise `ValueError` on unknown.

---

## Sub-Task 7 — `engine/tools.py`

**Status:** [ ] pending

### Intent
Agent-facing API layer. Every function here is a direct tool the AI can call.
All inputs and outputs are JSON-serialisable. No simulation or data-loading
happens inside `tools.py` itself — it delegates to the lower modules, passing
a module-level `_db` loaded once at import time.

### Functions

```python
def get_disruption(disruption_id: str) -> dict:
    # Returns full details of a disruption: affected PO, original and revised
    # receipt dates, reason, and the component/qty impacted.

def run_scenario(
    actions: list[dict],
    disruption_id: str | None
) -> dict:
    # Calls simulate() then evaluate(). Returns merged result.
    # Result includes all order_results rows, KPIs, and end_inventory.

def compare_scenarios(
    budget: int | None = None,
    objective: str = "on_time_orders"
) -> dict:
    # Builds action lists from the 5 named scenarios in scenarios.csv /
    # recovery_purchases.csv / recovery_transfers.csv.
    # Calls run_scenario for each, then rank_options.
    # Returns ranked list + best label.

def get_impact(disruption_id: str) -> dict:
    # Calls disruption_impact() from analysis.py.

def get_priority_view(
    actions: list[dict],
    disruption_id: str | None
) -> dict:
    # Runs simulate(), then calls priority_view().

def explore_purchase_qty(offer_id: str) -> dict:
    # Calls purchase_qty_options() from candidates.py.

def propose_action(disruption_id: str) -> dict:
    # Evaluates all transferable quantities and all max-qty purchase options
    # (one action at a time), runs each as a single-action scenario, and
    # returns results sorted by on_time_orders DESC, total_extra_cost ASC.
    # Does NOT approve or execute anything.
```

### Expected Outcomes
- `compare_scenarios(budget=500)["best"] == "TRANSFER"`
- `compare_scenarios()["best"] == "HYBRID"`
- All return values pass `json.dumps()`.

### Todo List
1. Create `engine/tools.py`.
2. Add module-level `_db = load_all()` at the top (loaded once on import).
3. Implement all seven functions using the lower-layer modules.
4. Ensure no function modifies `_db`.

---

## Sub-Task 8 — Tests

**Status:** [ ] pending

### Intent
Prove the engine is numerically correct by comparing against the ground truth
in `tests/expected/`. Also test the two specific transferable-qty and
compare_scenarios assertions from the requirements.

### Test Files

**`tests/test_scenarios.py`** — scenario correctness
- `TestScenarioSummary`: for each of the 5 scenarios, call `run_scenario` with
  the appropriate action list and compare `evaluate()` output row-by-row to
  `tests/expected/scenario_summary.csv`.
- `TestOrderResults`: compare all 60 order-result rows to
  `tests/expected/order_results.csv` (start_date, delivery_date, days_late).

**`tests/test_candidates.py`** — candidate enumeration
- `test_transferable_wh02_c01`: assert == 18.
- `test_transferable_wh03_c01`: assert == 14.
- `test_purchase_of02_valid_qty`: assert `20 in valid_quantities` and
  `65 in valid_quantities` and `len == 10`.

**`tests/test_compare.py`** — comparison and ranking
- `test_compare_budget_500`: assert `compare_scenarios(budget=500)["best"] == "TRANSFER"`.
- `test_compare_no_budget`: assert `compare_scenarios()["best"] == "HYBRID"`.

### Running Tests
```bash
# Run all tests from project root
python -m unittest discover -s tests -p "test_*.py"

# Run a single test file
python -m unittest tests.test_scenarios

# Run a single test case
python -m unittest tests.test_scenarios.TestScenarioSummary.test_NORMAL
```

### Todo List
1. Create `tests/__init__.py` (empty, if it doesn't exist).
2. Write `tests/test_scenarios.py` loading `tests/expected/scenario_summary.csv`
   and `tests/expected/order_results.csv` as the expected values.
3. Write `tests/test_candidates.py`.
4. Write `tests/test_compare.py`.
5. All tests must pass with `python -m unittest discover -s tests -p "test_*.py"`.

---

## Build Order Summary

| Step | File | Depends On |
|------|------|------------|
| 1 | `engine/loader.py` | (none) |
| 2 | `engine/simulate.py` | loader |
| 3 | `engine/evaluate.py` | simulate |
| 4 | `engine/candidates.py` | loader |
| 5 | `engine/analysis.py` | simulate |
| 6 | `engine/compare.py` | evaluate |
| 7 | `engine/tools.py` | all engine modules |
| 8 | `tests/test_*.py` | tools + expected CSVs |

---

## Key Invariants the Tests Will Enforce

1. **Queue order** — `queue == [SO01…SO12]` (due_date → priority_rank → order_id).
2. **Transferable qty** — WH02→WH01 = 18, WH03→WH01 = 14.
3. **All scenario KPIs** — must match `tests/expected/scenario_summary.csv` exactly.
4. **All order start/delivery/late days** — must match `tests/expected/order_results.csv` exactly.
5. **compare_scenarios(budget=500)** best option by on_time_orders = TRANSFER.
6. **compare_scenarios()** best option by on_time_orders = HYBRID.
7. **Cost formulas** — TRANSFER = $416, ALT_BUY = $1,250, HYBRID = $1,306.
8. **Inventory conservation** — verified inside simulate() on every run.
