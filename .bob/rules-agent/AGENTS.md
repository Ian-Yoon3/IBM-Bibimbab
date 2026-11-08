# Project Coding Rules (Non-Obvious Only)

- **Test runner:** `python -m unittest discover -s tests -v` — all 76 tests must stay green; do not break them
- **Engine API boundary:** `engine/tools.py` is the only module agents and scripts may call; never import `engine/loader.py`, `engine/simulate.py`, etc. directly from `agent/` or `scripts/`
- **stdlib boundary:** `engine/` is stdlib-only (`csv`, `collections`, `datetime`, `pathlib`, `sys`); third-party packages (`ibm-watsonx-ai`, `python-dotenv`) are only allowed in `agent/` and `scripts/`
- **Tool-call argument normalisation:** `ibm_watsonx_ai` may return `tool_calls[].function.arguments` as a JSON-encoded string or as a parsed dict — always normalise to a dict with `json.loads()` guarded by `isinstance(args, str)` before passing to the engine
- **Model config:** read `WX_MODEL_ID` from env (default `ibm/granite-4-h-small`); always pass an explicit `max_tokens` to `ModelInference` — the SDK default (1024) emits a warning and may truncate responses
- **Agent tests are network-free:** patch/mock `ModelInference.chat` — never make real watsonx.ai calls in `tests/`
- **D01 only:** only disruption D01 exists; the agent must not invent delay dates or outcomes for other disruption IDs
- **(reference/verify.py only)** `load()` asserts no duplicate keys AND no empty fields (except `scenarios.disruption_id`) — any new CSV must conform or `load()` will crash
- **(reference/verify.py only)** `number()` and `day()` are the only correct ways to read int/date fields; bare `int(row[k])` skips the non-negative guard
- **(reference/verify.py only)** `floor` dict is pre-computed as `reserved_qty + protected_qty` and is reused across all 5 scenario simulations — it must not be mutated
- **(reference/verify.py only)** `simulate()` accumulates ledger/detail/summary into module-level lists; if you refactor into a class, those appends must be preserved for `--write` mode
- **(reference/verify.py only)** `events` dict keys are `date` objects, not strings — comparisons must use `date` arithmetic
- **(reference/verify.py only)** `in_transit` counter tracks `(lane_id, component_id)` and must reach zero by horizon end; assertion at line 180 will fail otherwise
- **(reference/verify.py only)** `write()` uses `header.split()` (space-separated string) to produce column names — add columns by extending that string, not a list
