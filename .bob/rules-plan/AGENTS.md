# Project Architecture Rules (Non-Obvious Only)

- The simulation is strictly **day-forward, queue-ordered** — no backtracking, no look-ahead; any alternative engine must preserve this
- Production is **all-or-nothing per order**: if even one component falls short, that order and all subsequent orders in the queue are blocked for that day
- Transfer accounting is **asymmetric**: `TRANSFER_OUT` fires on `action_date` (debiting source), `TRANSFER_IN` fires on `action_date + lead_days` (crediting destination) — they are separate events
- `floor[warehouse, component]` = `reserved_qty + protected_qty` is a **hard lower bound** enforced on every stock mutation; transfers that would breach it are invalid in the data
- `expected_starts` in `verify.py` encodes **offsets from DAY0**, not absolute dates — offset 0 = 2026-11-09
- All 12 orders are assigned to `WH01` (PRODUCTION role); `WH02` and `WH03` are BUFFER warehouses — production never starts from a BUFFER warehouse
- Costs are computed **per scenario independently** — PO01's 1,450 USD sunk cost is excluded from all extra-cost tallies by design
- The five scenarios form a **Pareto frontier** (cost vs. on-time orders); architectural changes that alter the `expected_starts` or `expected_costs` constants require updating both the data and the hardcoded expectations in `verify.py`
- **Agent layer is read-only to the engine:** the agent calls `engine/tools.py` functions but never mutates `data/*.csv` or any engine state — approval of actions is out of scope
- **Tool surface for the LLM:** `get_disruption`, `get_impact`, `compare_scenarios`, `get_priority_view`, `explore_purchase_qty`, `propose_action` — `run_scenario` is not exposed to the LLM yet
- **D01 boundary:** only disruption D01 is modelled; the agent must not fabricate outcomes for hypothetical disruptions or delay dates not present in the data
