# UI contract

This page is everything the UI needs from the agent.
You do not need to read `agent/` to build the UI.
You do not need an API key either. Use `ui_fixtures/agent_results.json` until the end.

## The two calls the UI makes

```python
from agent.loop import run_agent                 # ask the agent (needs .env)
from agent.decisions import record_decision, list_decisions   # approve / reject (no .env)
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
| `unsupported` | A hypothetical the engine does not model | `scope_note`, `rows` |
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

`ui_fixtures/agent_results.json` holds 23 real results.
22 are from a Llama 3.3 sweep on 2026-11-07, replayed through the current code.
1 is the error case.
Every view type appears at least once.
Conversations 18 and 19 are multi-turn and end with a proposal.

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
