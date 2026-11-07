# Project Coding Rules (Non-Obvious Only)

- **`verify.py` must be run from inside `reference/`** (`cd reference && python3 verify.py`); `ROOT = Path(__file__).parent` resolves data paths relative to the script file, not the cwd — running from project root gives `FileNotFoundError`
- `load()` in `reference/verify.py` asserts no duplicate keys AND no empty fields (except `scenarios.disruption_id`) — any new CSV must conform or `load()` will crash
- `number()` and `day()` are the only correct ways to read int/date fields; bare `int(row[k])` skips the non-negative guard
- `floor` dict is pre-computed as `reserved_qty + protected_qty` and is reused across all 5 scenario simulations — it must not be mutated
- `simulate()` accumulates ledger/detail/summary into module-level lists; if you refactor into a class, those appends must be preserved for `--write` mode
- `events` dict keys are `date` objects, not strings — comparisons must use `date` arithmetic
- `in_transit` counter tracks `(lane_id, component_id)` and must reach zero by horizon end; assertion at line 180 will fail otherwise
- `write()` uses `header.split()` (space-separated string) to produce column names — add columns by extending that string, not a list
- `engine/` directory exists but is empty — intended for new simulation/engine code
- No `requirements.txt`, `setup.py`, or virtual env — stdlib only; never add third-party imports
