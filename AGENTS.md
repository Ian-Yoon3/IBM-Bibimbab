# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project

Supply chain recovery simulation for a fictional manufacturer (NovaTech). The engine is a single Python 3 script with no external dependencies. All data lives in `data/*.csv`; expected outputs are in `tests/expected/*.csv`.

- **Base date:** 2026-11-09; **horizon:** 2026-11-21 (12 calendar days)
- **Scenarios:** `NORMAL`, `WAIT`, `TRANSFER`, `ALT_BUY`, `HYBRID`

## Commands

```bash
# Run verify.py from inside reference/ — the script resolves paths relative to __file__
# so it expects data/ and validation/ as siblings of verify.py, not at the project root
cd reference && python3 verify.py

# Regenerate reference/validation/*.csv
cd reference && python3 verify.py --write
```

**Gotcha:** `ROOT = Path(__file__).resolve().parent` means data is read from `reference/data/` and written to `reference/validation/`. The repo currently stores data at `data/` and expected outputs at `tests/expected/` (both at project root). Running `python3 reference/verify.py` from the project root will `FileNotFoundError`. The intended layout requires `data/` and `validation/` to exist inside `reference/`, or `ROOT` must be changed to `ROOT.parent`.

There is no separate test runner, linter, or build step. The single script IS the test.

## Data conventions (`data/*.csv`)

- UTF-8, comma-separated, first row is header; dates are `YYYY-MM-DD`
- All fields are non-empty **except** `scenarios.disruption_id` (empty = undisrupted)
- Composite primary keys: `inventory` → `warehouse_id + component_id`, `bom` → `product_id + component_id`, `recovery_purchases` → `scenario_id + offer_id`, `recovery_transfers` → `scenario_id + lane_id + component_id`
- `available_qty = on_hand_qty - reserved_qty - protected_qty` — never go below floor
- Transfer dispatches debit the source warehouse on `action_date`; credit the destination on `action_date + lead_days`
- `purchase_orders.planned_receipt_date` must equal `order_date + offer.lead_days` exactly

## Simulation rules (critical for correctness)

1. Order queue is sorted by `(due_date, priority_rank, order_id)` — `queue == [SO01…SO12]` in that order
2. Each day: process all receipts/transfers first, **then** attempt production in queue order
3. Production is all-or-nothing per order — no partial fulfillment; start requires all BOM components available
4. Production start deducts all components immediately; delivery = start + `production_days`
5. `delay_days = max(0, delivery_date - due_date)`; summed per scenario without quantity weighting
6. Extra cost = `unit_cost × qty + fixed_fee` for each recovery purchase and each transfer lane used; PO01's base cost (1,450 USD) is excluded from all scenarios' extra cost
7. Inventory conservation check: `Σ_warehouses opening[c] + external_receipts[c] - production_used[c] = Σ_warehouses closing[c]` for every component

## Output files (`tests/expected/`)

| File | Rows |
|---|---|
| `scenario_summary.csv` | 5 (one per scenario) |
| `order_results.csv` | 60 (12 orders × 5 scenarios) |
| `inventory_ledger.csv` | variable — one row per stock event |
| `checks.csv` | 5 — all three audit columns must be `PASS` |

## Code style (`reference/verify.py`)

- stdlib only: `csv`, `collections`, `datetime`, `pathlib`, `sys`
- `load(name, *keys)` returns a dict keyed by single value or tuple; duplicate keys raise `AssertionError`
- `number(row, key)` / `day(row, key)` are the canonical accessors — enforce non-negative int and ISO date
- Assertions are used for all data-integrity checks (no `raise` statements)
- `ROOT` is resolved relative to `__file__`, not `cwd`
- The `engine/` directory is empty — new simulation code should go there or alongside `verify.py` in `reference/`
