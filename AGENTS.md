# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project

Supply chain recovery simulation for a fictional manufacturer (NovaTech). The simulation engine lives in `engine/`; an LLM-based agent layer lives in `agent/`. All data lives in `data/*.csv`; expected outputs are in `tests/expected/*.csv`.

- **Base date:** 2026-11-09; **horizon:** 2026-11-21 (12 calendar days)
- **Scenarios:** `NORMAL`, `WAIT`, `TRANSFER`, `ALT_BUY`, `HYBRID`

## Commands

```bash
# Run the full test suite (76 tests must stay green)
python -m unittest discover -s tests -v

# Regenerate reference/validation/*.csv (reference implementation only)
cd reference && python3 verify.py --write
```

## Repository layout

| Path | Purpose |
|---|---|
| `engine/` | Simulation engine — stdlib only. The sole public API is `engine/tools.py`. |
| `agent/` | watsonx.ai agent layer — may use packages in `requirements.txt`. |
| `scripts/` | One-off utility scripts — may use packages in `requirements.txt`. |
| `reference/` | Reference implementation (`verify.py`) and data dictionary. |
| `data/` | Source CSV files. |
| `tests/` | Unit + integration tests; expected CSVs in `tests/expected/`. |

## Engine API

`engine/tools.py` is the **only** module the agent should call. Do not import other `engine/` modules directly from `agent/` or `scripts/`.

## Agent design

- **Platform:** watsonx.ai chat with tool calling via `ibm_watsonx_ai.foundation_models.ModelInference`.
- **Model:** read from env `WX_MODEL_ID`; default `ibm/granite-4-h-small`. Always set `max_tokens` explicitly.
- **Tool-call arguments** may arrive as a JSON string or as a parsed object — normalise to a dict before calling the engine.
- **Tools exposed to the LLM (7 total):**
  `get_disruption`, `get_offers`, `get_impact`, `compare_scenarios`,
  `get_priority_view`, `explore_purchase_qty`, `propose_action`.
  (`run_scenario` is not exposed yet.)
- `get_offers` must be called before `explore_purchase_qty` to discover the offer ID for the disrupted component.
- `get_priority_view` accepts `scenario_id=` (preferred) or a raw `actions` list.
- `propose_action` (LLM-facing) accepts either `scenario_id` **or** `(offer_id, qty, include_transfers)` — the agent layer resolves the latter via `explore_purchase_qty` before calling the engine.
- The agent **never approves** recovery actions — it only proposes.
- Only disruption **D01** exists in the data. If asked about other disruption IDs or new delay dates, the agent must reply that they are not supported yet rather than inventing numbers.

## Secrets & environment

- Secrets live exclusively in `.env` (gitignored). Never commit credentials.
- Copy `.env.example` → `.env` and fill in `WX_API_KEY`, `WX_PROJECT_ID`, `WX_URL`, `WX_MODEL_ID`.
- Agent tests must use a fake/mock LLM and make **no** network calls.

## Dependencies

- `engine/` — stdlib only (`csv`, `collections`, `datetime`, `pathlib`, `sys`). Never add third-party imports to `engine/`.
- `agent/` and `scripts/` — may use packages listed in `requirements.txt` (`ibm-watsonx-ai`, `python-dotenv`).

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

## Code style (`engine/` and `agent/`)

- Data and input errors raise `ValueError` with a clear message — no `assert` for validation logic
- `engine/` reads CSVs exclusively via `engine/loader.py`; never open data files directly elsewhere
- Public functions return JSON-serialisable dicts
