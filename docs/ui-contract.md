# UI contract

This page is everything the UI needs from the agent.
You do not need to read `agent/` to build the UI.
You do not need an API key either. Use `ui_fixtures/agent_results.json` until the end.

## The calls the UI makes

```python
from agent.loop import run_agent                 # ask the agent (needs .env)
from agent.decisions import record_decision, list_decisions   # approve / reject (no .env)
from agent.overview import get_overview          # first screen (no .env, no credits)
```

The UI calls nothing else in `agent/` or `engine/`.

### 1. `run_agent(user_message, history=None)`

Call it once per user message.
Keep `result["history"]` and pass it back on the next message of the same conversation.
Pass `None` to start a new conversation.

It returns a dict.

| Key | Always there | What it is |
|---|---|---|
| `answer` | yes | The full answer as Markdown. Showing only this is already a working UI. |
| `view` | no | Structured data for a nicer layout. Missing or `None` means a free-text answer. Read it with `result.get("view")`. |
| `proposal` | yes | `None`, or a proposal waiting for approval. Show the approve and reject buttons only when it is not `None`. |
| `tool_trace` | yes | The engine calls the agent made, with arguments and results. Useful for a "how the agent got this" panel. |
| `history` | yes | Pass back on the next turn. Not in the fixture file. |
| `error` | no | Only when watsonx.ai could not be reached. `answer` then holds a safe message with no numbers. |

`run_agent` never raises because of the LLM. A failure comes back as the `error` key.

### 2. `record_decision(proposal, approved, decided_by, note="")`

Call it when a person presses approve or reject.

- `proposal` is `result["proposal"]` exactly as received.
- `approved` is `True` or `False`.
- `decided_by` is the person's name. It must not be empty.
- It returns the log entry and appends it to `decisions/decision_log.jsonl`.
- It raises `ValueError` if the proposal was already decided or the input is wrong. Show the message to the user.

`list_decisions()` returns every decision, oldest first. Use it for a decision log table.

### 3. `get_overview()`

Call it when the app opens, before the first question.
It returns a `world_risk` view in `overview` mode (see below).
It makes no watsonx.ai call, costs no credits and needs no `.env`.
It shows the current situation and the risk of each option, so the manager can read the state first and then ask.
Its `suggested_questions` can be shown as clickable examples. Each click is a normal question, so in live mode it calls `run_agent`.

The agent cannot call `record_decision`. Only the UI can. That is the "a human approves every action" rule.

On Streamlit Community Cloud the log file is lost when the app restarts. That is fine for the demo.

## View types

`view["type"]` tells you which layout to use. Every view also has `markdown`, which is the same text as `answer`.

| `type` | When | Fields to use |
|---|---|---|
| `recommendation` | The user asks what to do | `situation`, `rows`, `recommended`, `criteria`, `settings` |
| `comparison` | The user asks to compare options | same as above, but `recommended` is `None` (no star) |
| `option` | "What does HYBRID involve?" | `row` |
| `order` | "Why is SO05 late?" | `detail` |
| `proposal` | The user asked to act | `proposal`, `code` |
| `world_risk` | The receipt date of PO01 is uncertain: risk, chance, worst case, or "what if it arrives on Nov 19 / 3 days late" | see the `world_risk` section |
| `unsupported` | A date after the simulated window, another disruption, or a change to another input | `scope_note`, `rows` |
| no view | Impact, customer questions, general questions | show `answer` only |

### `rows` (recommendation, comparison, unsupported) and `row` (option)

One row per option. Each row has:

| Field | Example | Meaning |
|---|---|---|
| `code` | `"TRANSFER"` or `"OF02 x40 + transfers"` | Short name. The user can say it back ("Propose TRANSFER"). |
| `name` | `"Move stock from North Buffer and East Buffer"` | Display name |
| `found_by_search` | `false` | `true` for options found by `explore_purchase_qty`, not in the original four |
| `on_time_orders`, `total_orders` | `8`, `12` | |
| `priority_on_time`, `priority_total` | `4`, `6` | Priority-1 orders |
| `total_days_late` | `12` | |
| `extra_cost` | `416` | USD |
| `late_orders` | `[{"order_id": "SO05", "days_late": 5, "priority_rank": 2}, ...]` | |
| `scenario_id`, `offer_id`, `qty`, `include_transfers` | | Identify the option. Not for display. |

Mark the row whose `code` equals `view["recommended"]` with a star.
`settings["budget"]` is the user's budget or `None`. Use it for a "within budget" column if you want one.

### `world_risk`

Three modes share one layout. `view["mode"]` is `overview` (from `get_overview()`), `general` (a risk question) or `date` (a question that names one receipt date).

| Field | Example | Meaning |
|---|---|---|
| `mode` | `"date"` | Which of the three modes |
| `situation` | `"A supplier equipment outage ..."` | Text. Show as is |
| `reading` | `["Read as: PO01 arrives on Nov 14.", "\"N days late\" counts from ..."]` | Date mode only, else `[]`. Show above the tables. It tells the manager how the question was read |
| `focus_date` | `"2026-11-14"` | Date mode only, else `None`. Highlight this column in the date table |
| `rows` | see below | One row per option |
| `what_if` | `{"dates": ["2026-11-11", ...], "late_orders": {"WAIT": [0, 1, ...], ...}}` | Late orders of each option for each receipt date. Needs no weights |
| `steps` | `[{"from": "TRANSFER", "to": "ALT_BUY", "extra_cost_change": 834, "expected_late_change": -0.73, "p90_late_change": -1, "worst_late_change": -1, "p_no_late_pct_change": -4.2}]` | Moving to the next option in order of cost |
| `explanation` | `"ALT_BUY expects 2.99 ..."` or `None` | The AI paragraph, only when `explanation_status` is `"ok"` |
| `explanation_status` | `"ok"`, `"dropped"`, `"unavailable"` or `None` | `dropped` means the code removed the paragraph because it used a number or option that is not in the tables. `None` in overview |
| `scope_note` | `"Weights come from data/worlds.csv ..."` | Where the weights come from |
| `suggested_questions` | list of 4 strings | Overview only, else `[]` |
| `settings` | `{"budget": 500}` or `{"budget": None}` | The budget the user stated |

Each row in `rows`:

| Field | Example | Meaning |
|---|---|---|
| `code`, `name`, `scenario_id` | `"TRANSFER"`, `"Move stock from North Buffer and East Buffer"` | Same meaning as in other views |
| `extra_cost` | `416` | USD. The cost axis |
| `expected_late_orders` | `3.73` | Weighted average. Keep the two decimals |
| `p90_late_orders` | `7` | In 9 of 10 weighted cases late orders are at or below this number. Label it "90th percentile" |
| `worst_late_orders` | `8` | Worst receipt date in the data |
| `p_no_late_pct` | `5.6` | Chance of no late order, in percent. Show with a % sign |
| `late_at_focus` | `1` or `None` | Date mode only. Late orders on `focus_date` |
| `within_budget` | `true`, `false` or `None` | Only when the user stated a budget |

Rules for this view
- No star and no approve button. `proposal` is always `None` here.
- Show the time columns and the cost column side by side. Never combine them into one score or rank.
- Show the reading lines in date mode. Do not hide them.
- If `explanation_status` is not `"ok"`, do not show any AI text. The fixed line in `markdown` explains why.

### `detail` (order)

`order_id`, `customer_id`, `option`, `due_date`, `start_date`, `delivery_date`, `days_late`, `priority_rank`, `cause`, `summary`, `components_needed`.
`summary` is one sentence written by the engine. Show it as is.

### `proposal`

`proposal_id`, `actions` (list of purchases and transfers), `metrics` (`on_time_orders`, `total_orders`, `total_extra_cost`, ...), `reason`, `status` (`"pending_approval"`).
`view["code"]` is the short name of the proposed option.

## Rules for the UI

1. Never compute or change a number. Every number comes from `rows`, `detail`, `proposal` or `answer`.
2. Never show an approve button without a `proposal`.
3. Never call `run_agent` for display tricks. Each call costs watsonx.ai credits.
4. When `error` is present, show `answer` and offer a retry. Do not show old numbers as if they were new.

## Working without an API key

`ui_fixtures/agent_results.json` holds real results from the latest Llama 3.3 question sweep, replayed through the current code, plus 1 error case.
Every view type appears at least once, including `world_risk` and `unsupported`.
Conversations 18 and 19 are multi-turn and end with a proposal.
The overview needs no fixture. Call `get_overview()` directly.

```python
import json
FIXTURES = json.load(open("ui_fixtures/agent_results.json", encoding="utf-8"))

def fake_run_agent(user_message, history=None):
    for f in FIXTURES:
        if f["question"] == user_message:
            return f["result"]
    return FIXTURES[0]["result"]
```

Swap `fake_run_agent` for `run_agent` when testing with a key.
If the agent output changes, regenerate the file with `python -m scripts.make_ui_fixtures`. The script stops if the replay no longer matches the saved run.
