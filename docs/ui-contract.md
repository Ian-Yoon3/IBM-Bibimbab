# UI contract

This page is everything the UI needs from the agent.
You do not need to read `agent/` to build the UI.
You do not need an API key either. Use `ui_fixtures/agent_results.json` until the end.

## The calls the UI makes

```python
from agent.loop import run_agent                 # ask the agent (needs .env)
from agent.decisions import record_decision, list_decisions   # approve / reject (no .env)
from agent.overview import get_overview          # first screen (no .env, no credits)
from agent.overview import get_data_overview     # data files and run state (no .env, no credits)
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

### 4. `get_data_overview()`

Call it to show which data the numbers come from, for example in an "Add a file" dialog.
It makes no watsonx.ai call, costs no credits and changes nothing.

| Field | Example | Meaning |
|---|---|---|
| `data_dir` | `"data"` | The folder the engine loads |
| `files` | `[{"name": "orders.csv", "group": "inputs", "rows": 12}, {"name": "history/shipments.csv", "group": "history", "rows": 43}]` | Every CSV file in the folder. `rows` counts data rows without the header. `group` is `inputs` or `history` |
| `run` | see below | The selected Monte Carlo run and whether it matches the data |
| `synthetic_history` | `true` | The history files are synthetic (read from `data/history/README.md`). Say so on the screen |
| `upload` | `{"enabled": false, "note": "Not connected in this demo. ..."}` | Whether a data set can be uploaded through the UI. It is `false`: a new data set needs a new Monte Carlo run before any number can change |

`run`:

| Field | Example | Meaning |
|---|---|---|
| `status` | `"match"`, `"stale"`, `"invalid"` or `"none"` | Same check as `python -m engine.runs --check`. `stale`: data or code changed after the run. `invalid`: the selection file cannot be read. `none`: no run is selected |
| `name` | `"runs/demo"` or `None` | The run folder |
| `message` | `"Monte Carlo run runs/demo: inputs, code and outputs match."` | One sentence for the screen. Show as is |
| `detail` | `""` or the text of the failed check | What differs, for an expander |
| `settings` | `{"M": 1000, "N": 200, "seed": 20261109, "method": "lhs"}` or `None` | Only when `status` is `match` |
| `grid` | `"present"`, `"absent"` or `None` | Whether the run has a threshold grid |
| `created_at` | `"2026-11-22T05:31:21+00:00"` or `None` | When the run was made |

Rules
- While `upload["enabled"]` is `false`, keep the upload control and its confirm button disabled and show `upload["note"]` next to them. Do not read or store a file.
- When `status` is not `match`, show `message` as a warning. Do not present the risk numbers as current.

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

### AI text in `recommendation` and `comparison`

The model writes two parts of `markdown`: the short reasoning under "Recommendation" (or "Comparison") and the lines it adds under "Trade-offs and risks". The lines "Still late with this option: ..." are written by the code.

Before the text is shown, the code checks every comparison in it against `rows` (`agent/claims.py`): higher/lower, more/fewer, most/fewest, cheaper, "3 fewer", "save $416", "ranging from ... to ...", "within the budget". A comparison that disagrees with the rows, or that the code cannot tie to a column and to options on both sides, is not shown.

`view["narrative_check"]` reports the result:

| Field | Values | Meaning |
|---|---|---|
| `rationale` | `"ok"`, `"dropped"`, `"unavailable"` | `dropped`: the reasoning was replaced by a fixed line in `markdown`. `unavailable`: the model returned no text |
| `tradeoff_lines_dropped` | `0`, `1`, ... | Number of AI trade-off lines left out. When it is not 0, `markdown` has one fixed line saying so |

How the code reads a sentence (so a dropped text can be understood):
- "the most / the lowest" covers every row of the table, unless the limit stands in the same phrase ("the most on-time orders within the budget", "the lowest cost among options with at least 10 on-time orders"). "has the most on-time orders, and is within the budget" is read as a claim about every row.
- "other options", also in "other options like WAIT", means every other row.
- A trade-off line that names one option and no second one is compared with the starred option. In a comparison (no star) this works only when the table has two rows.
- The budget is the one in `settings["budget"]`. A sentence about a budget when the request has none is not shown.

Limits:
- Only the listed comparison words, any "... than ...", and "the <word>est" are recognised. A comparison made in other words ("has an edge over") is not seen.
- A correct sentence can be left out when the code cannot read it. A sentence is never shown on the benefit of the doubt.
- A number that is attached to the wrong option or the wrong column is not checked, unless it is part of a comparison ("increase on-time orders to 9").
- Answers without a view (impact, customer and general questions) are free text and are not checked this way.

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
| `steps` | `[{"from": "TRANSFER", "to": "ALT_BUY", "extra_cost_change": 834, "expected_late_change": -0.90, "p90_late_change": -1, "p_no_late_pct_change": -3.2, "tail_mean_late_change": -0.09}]` | Moving to the next option in order of cost |
| `ranking` | `{"order": ["HYBRID", "ALT_BUY", "TRANSFER", "WAIT"], "draws": 1000, "same_draws": 957, "other_orders": [{"order": [...], "draws": 43}]}` or `None` | How often the order by expected late orders holds over the parameter draws. `None` when the weights have only one draw (stage 1 worlds, announced date) |
| `causes` | list, see below, or `[]` | One entry per shared cause. `[]` when the data has no causes or no cause episodes |
| `common_scale` | `{"reference_cause": "K2", "crossings": [], "max_m": 40.53}` or `None` | All cause rates multiplied by the same factor m. `None` without a threshold grid |
| `assumptions` | list of strings or `[]` | Assumption lines shown under "Assumptions". Show them as they are |
| `explanation` | `"ALT_BUY expects 2.99 ..."` or `None` | The AI paragraph, only when `explanation_status` is `"ok"` |
| `explanation_status` | `"ok"`, `"dropped"`, `"unavailable"` or `None` | `dropped` means the code removed the paragraph. `None` in overview |
| `explanation_drop_reason` | `"number"`, `"comparison"` or `None` | Why the paragraph was removed. `number`: it used a number or option that is not in the tables. `comparison`: a comparison in it disagrees with the tables or could not be confirmed (same check and limits as "AI text in `recommendation` and `comparison`"; "late orders" without a column name must hold in every late-orders column; values are compared as printed) |
| `scope_note` | `"Weights come from data/worlds.csv ..."` | Where the weights come from |
| `suggested_questions` | list of 4 strings | Overview only, else `[]` |
| `settings` | `{"budget": 500}` or `{"budget": None}` | The budget the user stated |

Each row in `rows`:

| Field | Example | Meaning |
|---|---|---|
| `code`, `name`, `scenario_id` | `"TRANSFER"`, `"Move stock from North Buffer and East Buffer"` | Same meaning as in other views |
| `extra_cost` | `416` | USD. The cost axis |
| `expected_late_orders` | `3.73` | Weighted average. Keep the two decimals |
| `average_range` | `[3.64, 5.8]` or `None` | Range of the AVERAGE over the parameter draws (5% to 95%). Label it "Range of the average". It is not the range of one outcome. `None` with one draw |
| `p90_late_orders` | `7` | In 9 of 10 weighted cases late orders are at or below this number. Label it "90th percentile" |
| `tail_mean_late_orders` | `9.5` | Average late orders in the worst 10% of weighted cases. Label it "Worst-10% average". Replaces the old worst case column |
| `p_no_late_pct` | `5.6` | Chance of no late order, in percent. Show with a % sign |
| `late_at_focus` | `1` or `None` | Date mode only. Late orders on `focus_date` |
| `within_budget` | `true`, `false` or `None` | Only when the user stated a budget |

Each entry in `causes`:

| Field | Example | Meaning |
|---|---|---|
| `cause_id`, `targets` | `"K1"`, `[["purchase_order", "PO01"], ["offer", "OF02"]]` | The cause and what it delays |
| `active_pct` | `9.5` | Chance in percent that an episode of the cause is under way in the decision window |
| `without`, `with` | `{"WAIT": 7.24, ...}`, `{"WAIT": 9.13, ...}` | Expected late orders per option over the cases without and with the cause. A value is `None` when no case falls in that group |
| `per_year_mean` | `4.1` or `None` | Estimated episodes per year (Monte Carlo run only) |
| `open_episode` | `None` or `{"start_date": "2026-11-07", "end_date": None, "delay_days": 3}` | The cause is in progress on the decision day. Then show the status sentence from `markdown` instead of without/with |
| `grid` | `{"D0_days": 9, "crossings": [{"pair": ["TRANSFER", "ALT_BUY"], "p_lo": 0.8125, "p_hi": 0.81875, "per_year_lo": 67.9, "per_year_hi": 69.3}], "max_p": 0.99, "max_per_year": 186.8}` or `None` | Where two options swap order as the cause gets more frequent. No crossing means the order holds up to `max_p` |

Rules for this view
- No star and no approve button. `proposal` is always `None` here.
- Never compute a threshold from `without` and `with`. The thresholds come only from `grid` and `common_scale`.
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
