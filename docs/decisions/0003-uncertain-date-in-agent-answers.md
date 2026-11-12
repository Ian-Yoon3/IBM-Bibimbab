# ADR 0003. Uncertain receipt date in agent answers (stage 1)

- **Status:** Accepted
- **Date:** 2026-11-12
- **Branch:** `feature/extension-trial-ian`
- **Decision owner:** Sunghyuk (Ian) Yoon

## Context

Until now the agent declined every hypothetical delay.
"What if the supplier is 3 days late instead?" returned the unsupported view.
The rule lived in three places: `render.is_unsupported`, the `scope_note` of `get_disruption` and the SCOPE rule of the system prompt.
The rule was right while the engine knew only one receipt date.

Stage 1 changed that.
The worlds module computes every option at every receipt date of PO01 inside the simulation window (see ADR 0002 and `docs/extension-plan.md`).
`engine.tools.get_world_risk` returns these results. It is not an LLM tool.
Declining "3 days late" while the same screen shows the 11-14 column would be inconsistent.

The agent also has no check on numbers written by the LLM.
ADR 0001 records Llama reading the wrong row of a table.
The new view shows many numbers, so the risk of a wrong number in LLM text is higher here than in other views.

## Options considered

| Option | What it means | Result |
|---|---|---|
| A. Code only | Tables by code, no LLM text | Safe. The uncertainty is not reflected in the AI answer at all. |
| B. Code tables and a checked LLM paragraph | Tables by code, the LLM explains them, code checks every number the LLM writes | Chosen |
| C. Ninth LLM tool | `get_world_risk` in `TOOL_SPECS`, free LLM answer | Highest risk of wrong numbers. Changes model behaviour on existing questions. |
| Keep hypotheticals unsupported | No change to the unsupported view | Rejected. The change is deliberate and is reviewed in the stage 1 pull request. |

## Decision

### 1. One view, three modes

New view type `world_risk`. All modes use the same tables, built by code from `get_world_risk`.

| Mode | When | LLM paragraph |
|---|---|---|
| `overview` | Before any question. The UI calls `agent.overview.get_overview()`. No watsonx.ai call, no credits. | No |
| `general` | The user asks about uncertainty or risk | Yes |
| `date` | The question resolves to one receipt date inside the window | Yes. The view highlights that date. |

`get_overview()` becomes the fourth function the UI may call, next to `run_agent`, `record_decision` and `list_decisions`.

### 2. Routing

Order of view choice:
proposal, unsupported (narrowed), `world_risk`, order, option, comparison, recommendation, free text.

`world_risk` is chosen when one of these holds and the question names no order ID (`SO01` to `SO12`) and does not ask about customers.

1. An uncertainty word appears (uncertain, not sure, chance, likely, probability, odds, percentile).
2. A risk word (risk, risky, worst case) appears together with a target word (arrival, receipt, delivery, date, supplier, PO01, an option code).
3. A date or a number of days resolves to one receipt date inside the window, together with a target word.

The exact word lists live in `agent/render.py` and its tests. Every question in `ui_fixtures/agent_results.json` other than the two hypothetical-delay questions keeps its current view.

### 3. Reading days as a date

| Wording | Counted from | Example |
|---|---|---|
| "N days late", "a delay of N days", "the delay becomes N days" | Original planned date of PO01 (11-11) | 3 days late is 11-14 |
| "N days earlier", "N days sooner" | Announced date (11-17) | 2 days earlier is 11-15 |
| "N more days", "N days later", "slips another N days" | Announced date (11-17) | 2 more days is 11-19 |
| An explicit date ("11-19", "Nov 19") | Itself | 11-19 |
| Weeks | 7 days each | 2 weeks late is 11-25 |

"N days late" keeps the meaning the engine already used. `get_disruption` reports the recorded delay as 6 days, from 11-11 to 11-17.
All dates come from the data. None is written into the code.
If the wording gives more than one date, the general mode is used without a highlighted date.

The view always starts with these lines, written by code:

```
Read as: PO01 arrives on 11-14.
"N days late" counts from the original planned date (11-11). "N days earlier" or "N days later" counts from the announced date (11-17).
```

The second line is left out when the user gave an explicit date.

### 4. Still unsupported

- A resolved date after the last simulated day. The answer gives the reading, the rule line and "11-25 is after the last simulated day (11-21). Dates after the window are planned for stage 2."
- A resolved date before the original planned date.
- Disruption IDs other than D01.
- Changes to anything other than the receipt date of PO01, such as transfer or supplier lead times (stage 3).

### 5. What the LLM does and does not do

Code makes every number and every comparison. The LLM puts the result into the user's words.

| The LLM does | The LLM does not |
|---|---|
| Answer the user's question in plain sentences | Write a number that is not shown in the view |
| Quote numbers from the tables and say what they mean | Compute differences, sums, ratios or averages |
| Point out where measures disagree, for example ALT_BUY has fewer expected late orders than TRANSFER but a lower chance of no late order | Merge time and cost ("best value", "cost per late order") |
| Give conditional guidance ("if cost comes first, ...; if avoiding late orders comes first, ...") | Pick one winner when the user gave no criterion |
| Read marks that code puts in the table, such as options within a stated budget | Decide by itself whether an option meets a criterion |
| | Change weights or probabilities, or guess about the supplier |
| | Mention options that are not rows in the table, or write tables, headings or next steps |

Format. One free paragraph of at most four sentences, in a fixed slot below the tables.
The wording follows the user's question. The slot is fixed so that code can take it out and check it.

### 6. Number check

- Code extracts every number from the LLM paragraph and every option code it names.
- Each number must appear in the view as shown to the user. Each code must be a row of the table.
- Any mismatch drops the paragraph. A fixed line takes its place: "The AI explanation is not shown because it used a number that is not in the tables."
- The check applies to the new view only. Other views are unchanged.
- Limitation. The check cannot see a correct number attached to the wrong option. Prompt rules, scripted tests and a real watsonx.ai run reduce that risk. They do not remove it.

### 7. Deliberate changes to existing behaviour

- `render.is_unsupported` declines only the cases in section 4.
- The `scope_note` of `get_disruption` and the SCOPE rule of the system prompt say which receipt dates can be computed.
- Existing tests that expect "unsupported" for dates inside the window are updated.
- The golden question Q5 of `scripts/eval_agent.py` ("What if the delay becomes 8 days?", 11-19) now expects `world_risk`.
- Fixtures 11 and 12 become `world_risk`. One unsupported question stays in the fixtures, so every view type remains covered. `EXPECTED_TYPES` gets `world_risk`. The fixtures need a new real watsonx.ai sweep (Ian only).

Unchanged. The recommendation, comparison, option, order and proposal views, and the 8 LLM tools.

## Consequences

- Answers, the first screen and the tables agree on every date inside the window.
- An ambiguous wording cannot hide. The reading and the counting rule are always printed.
- A routing miss sends the question to the free-text answer. It does not produce wrong numbers.
- The work adds test and prompt updates and a full fixture sweep to stage 1.
