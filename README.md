# Supply Chain Recovery Decision Agent

An AI agent that helps a manufacturing operations manager respond to a supplier disruption.
The manager asks questions in plain English.
The agent calls a deterministic simulation engine, compares recovery options, explains the trade-offs, and prepares a proposal.
A human approves every action. The agent never approves or executes anything.

Team **Instant Bibimbab Masters**, IBM SkillsBuild AI Experiential Learning Lab.
Built with **IBM Bob** (development) and **IBM watsonx.ai** (LLM runtime).

---

## The problem in one paragraph

NovaTech, a fictional electronics manufacturer, learns on 2026-11-09 that purchase order PO01 (145 units of component C01) will arrive on 11-17 instead of 11-11. C01 goes into all three products, so 7 of 12 customer orders would be late if nothing is done. Recovery options include moving stock from two buffer warehouses and buying from an alternative supplier. The manager needs to know which option to choose under a budget, which customers are affected, and why specific orders stay late. All data is synthetic. See `reference/README.md` for the full scenario (Korean).

## Full design and demo scope

The full design starts from a delay notice that a manager types in plain words.
The demo starts after the notice has been parsed and judged.

```
 [Manager]  Delay notice in free text                             not in demo
                │
 [Agent]    Parse notice → event JSON                             not in demo
                │
 [Engine]   Response needed? ── no ──► [Agent] report "wait"      not in demo
                │ yes
 ───────── demo starts here: data/ holds the parsed event ─────────
                │
 [Engine]   Run calculation: shortages, at-risk orders,  ◄───┐
            options, evaluation, ranking                     │
                │                                            │ what-if
 [Agent]    Explain results and trade-offs in plain words    │ recalculate
                │                                            │
 [Manager]  Approve / reject, or ask what-if ────────────────┘
```

Two steps of the full design are not built in the demo.
The agent does not read a free-text notice.
The system does not decide whether a response is needed.

`data/` holds what those two steps would produce.
`disruptions.csv` and `purchase_orders.csv` contain the parsed event.
The other files hold the master data around it.
The data is synthetic.
It was written by hand so that the scenario is complete and every result can be checked.
`reference/verify.py` recomputes the scenarios independently of `engine/`.

A real notice rarely gives one certain date.
The supplier announced 11-17, but PO01 could arrive on any day from 11-11 to the end of the simulation window (11-21).
The engine therefore evaluates every option at every possible receipt date and reports the risk of each option.
How likely each date is comes from a data file, not from the model.
See [Uncertain receipt date](#uncertain-receipt-date) below.

## How it works

```
 Manager question ──► agent/ (watsonx.ai LLM, tool calling)
                          │   chooses tools, never computes numbers
                          ▼
                     engine/tools.py (8 LLM tools + get_world_risk for code, deterministic)
                          │   simulation, comparison, search, explanations
                          ▼
                     answer with an options table + pending proposal
                          │
                          ▼
                     human approves in the UI (not the agent)
```

Design rules, enforced in code:

1. **The engine computes, the LLM explains.** Every number in an answer must come from a tool result. Counts, differences and explanations that matter (late orders, shortfalls, scope limits) are produced by the engine as fields or sentences, so the model copies them instead of calculating.
2. **Two phases per turn.** A gather phase lets the model call tools (at most 10 steps, duplicate calls are blocked). Then the answer is built.
3. **Fixed answer layouts, built by code.** For recommendations, comparisons, option descriptions, order explanations, proposals and unsupported questions, `agent/render.py` lays out the engine data the same way every time: a situation sentence, an options table with the same rows and columns, a ★ on the option that best meets the user's budget and objective, and a next step the user can say back (for example *"Propose TRANSFER"*). The ★ follows the user's own words (budget, target, objective), not the model's choice. The model writes only the 2 or 3 sentences of reasoning and the trade-offs. Other questions (impact, priority customers, general questions) get a free-text answer. Each result also carries a structured `view` that a UI can render directly.
4. **Proposals only on request, approval only by a human.** `propose_action` is offered, named in the prompt, and callable only when the user asks to act (approve, propose, implement, submit). When a proposal is created, the answer lists the option, its metrics and each action in plain language, with status `pending_approval`. Only the UI can turn a proposal into approved or rejected, through `agent/decisions.record_decision()`, which the model cannot call.
5. **Safe failure.** Unsupported questions (receipt dates after the simulated window, unknown disruptions, changes to other inputs) get a scope note from the engine instead of invented numbers. If watsonx.ai cannot be reached, the agent retries twice and then returns a message that contains no numbers. If only the reasoning step fails, the engine-built table and recommendation are still shown.
6. **Uncertainty without invented numbers.** Questions about risk or about another receipt date ("what if it is 3 days late?") get the `world_risk` answer. Its tables come from the engine. The model writes one short paragraph, and code checks every number and option code in it against the tables. A paragraph that fails the check is not shown. See `docs/decisions/0003-uncertain-date-in-agent-answers.md`.
7. **Defensive argument handling.** String numbers and booleans (`"500"`, `"true"`) are coerced, `"null"` is treated as missing, unknown IDs and the disrupted supplier's offer are rejected with a message the model can act on.

## Quick start

Requirements: Python 3.11 or newer.

```bash
git clone https://github.com/Ian-Yoon3/IBM-Bibimbab.git
cd IBM-Bibimbab
pip install -r requirements.txt
```

The engine and all tests need no credentials. To talk to the agent, copy `.env.example` to `.env` and fill in your watsonx.ai credentials. `.env` is gitignored. Never commit it.

```
WX_API_KEY=...
WX_PROJECT_ID=...
WX_URL=https://us-south.ml.cloud.ibm.com
WX_MODEL_ID=meta-llama/llama-3-3-70b-instruct
```

Run every command from the repository root. Scripts are run as modules (`python -m ...`) so that the `agent` and `engine` packages are found.

| Task | Command | Needs `.env` |
|---|---|---|
| Run all tests | `python -m unittest discover -s tests` | no |
| Engine walkthrough | `python demo.py` | no |
| Chat with the agent | `python -m scripts.chat` | yes |
| Chat with another model | `python -m scripts.chat ibm/granite-4-h-small` | yes |
| Check the watsonx.ai connection | `python -m scripts.check_wx` | yes |
| Golden-question evaluation | `python -m scripts.eval_agent --runs 3` | yes |
| Realistic question sweep (answers saved for reading) | `python -m scripts.question_sweep` | yes |
| Evaluate selected questions | `python -m scripts.eval_agent --only Q5,Q13` | yes |
| First screen with the risk of each option (no LLM) | `python -c "from agent.overview import get_overview; print(get_overview()['markdown'])"` | no |
| Rewrite the stage 1 receipt-date weights (temporary) | `python -m scripts.stage1_triangular_worlds` | no |

Example chat:

```
You: Our budget is 500 dollars. What should we do?
You: Is there a cheaper way than HYBRID to keep 11 orders on time?
You: With that option, why is SO08 still late?
You: Propose that option.
```

## What the manager sees

Answer to *"Our budget is 500 dollars. What should we do?"* (the table, the ★, the late-order line and the next step are built by code from the engine; the two italic parts are written by the model):

> **Situation**
> A supplier equipment outage at Aster Silicon delays 145 units of Microcontroller (C01, order PO01) from Nov 11 to Nov 17, a delay of 6 days. With no action, 7 of 12 customer orders will be late.
>
> | Option | On-time orders | Priority-1 on time | Total days late | Extra cost | Within $500 |
> |---|---|---|---|---|---|
> | Wait for the delayed delivery (WAIT) | 5 of 12 | 2 of 6 | 27 | $0 | yes |
> | **Move stock from North Buffer and East Buffer (TRANSFER) ★** | **8 of 12** | **4 of 6** | **12** | **$416** | **yes** |
> | Buy 65 from Beacon Circuits (ALT_BUY) | 9 of 12 | 4 of 6 | 5 | $1,250 | no |
> | Move stock + buy 45 from Beacon Circuits (HYBRID) | 11 of 12 | 5 of 6 | 2 | $1,306 | no |
> | Move stock + buy 35 from Beacon Circuits (OF02 x35 + transfers, found by search) | 10 of 12 | 5 of 6 | 4 | $1,126 | no |
> | Move stock + buy 40 from Beacon Circuits (OF02 x40 + transfers, found by search) | 11 of 12 | 5 of 6 | 2 | $1,216 | no |
> | Move stock + buy 65 from Beacon Circuits (OF02 x65 + transfers, found by search) | 12 of 12 | 6 of 6 | 0 | $1,666 | no |
>
> **Recommendation:** Move stock from North Buffer and East Buffer (TRANSFER). *Within the budget, this is the only option that improves on waiting.*
>
> **Trade-offs and risks:** Still late with this option: SO05 (5 days), SO06 (3 days, priority 1), SO07 (2 days), SO08 (2 days, priority 1). *A larger budget would allow the 40-unit search option, which keeps 11 of 12 orders on time.*
>
> **Next step:** To act on this, say *"Propose TRANSFER"*. Nothing is executed until it is approved in the UI.

Answer to *"What if the supplier is 3 days late instead?"* from the real run in `eval_results/sweep_20261112_020142.json` (everything is built by code except the last paragraph, which the model wrote and code checked):

> **Reading**
> Read as: PO01 arrives on Nov 14.
> "N days late" counts from the original planned date (Nov 11). "N days earlier" or "N days later" counts from the announced date (Nov 17).
>
> | Option | Extra cost | Expected late orders | 90th percentile | Worst case | Chance of no late order | Late if it arrives Nov 14 |
> |---|---|---|---|---|---|---|
> | Wait for the delayed delivery (WAIT) | $0 | 6.53 | 10 | 11 | 1.4% | 4 |
> | Move stock from North Buffer and East Buffer (TRANSFER) | $416 | 3.73 | 7 | 8 | 5.6% | 1 |
> | Buy 65 from Beacon Circuits (ALT_BUY) | $1,250 | 2.99 | 6 | 7 | 1.4% | 1 |
> | Move stock + buy 45 from Beacon Circuits (HYBRID) | $1,306 | 1.36 | 4 | 5 | 35.0% | 0 |
>
> The full answer also has the late orders for every receipt date from Nov 11 to Nov 21, the trade-off steps between options, and notes.
>
> **What this means:** *If the supplier is 3 days late instead, the number of late orders would be 4 for the WAIT option, according to the "Late if it arrives Nov 14" column. The TRANSFER option would have 1 late order, and the ALT_BUY option would also have 1 late order. The HYBRID option would have 0 late orders, as shown in the same column.*

## Uncertain receipt date

Stage 1 of `docs/extension-plan.md`.

- **Worlds.** Each possible situation is a world: a set of changes to the base data with an integer weight. `data/worlds.csv` holds them, one row per world with its weight, its parameter draw and one column per changed value (ADR 0004). In stage 1 each world sets one receipt date of PO01. Without this file the engine uses the announced date with full weight, and every result equals the single-date result.
- **Weights.** A triangular three-point estimate: earliest 11-11 (original date), most likely 11-17 (announced), latest 11-21 (end of the window). The reasons and references are in `docs/decisions/0002-receipt-date-weights.md`. The file is written by a temporary script. A Monte Carlo engine replaces it in stage 2.
- **Exact computation.** The engine simulates every option in every world (`engine/worlds.py`). It does not sample. Arithmetic is exact and rounded once at output.
- **What is reported per option.** Extra cost, expected late orders, 90th percentile of late orders, worst case and chance of no late order. Time and cost are shown side by side and never combined. A separate table gives the late orders of every option for every receipt date. That table needs no weights.
- **What the manager sees.** `agent.overview.get_overview()` gives this picture before any question, without an LLM call. Questions about risk or about one date get the same tables, and a date question first states how it was read.

| Option | Extra cost | Expected late orders | 90th percentile | Worst case | Chance of no late order |
|---|---:|---:|---:|---:|---:|
| WAIT | $0 | 6.53 | 10 | 11 | 1.4% |
| TRANSFER | $416 | 3.73 | 7 | 8 | 5.6% |
| ALT_BUY | $1,250 | 2.99 | 6 | 7 | 1.4% |
| HYBRID | $1,306 | 1.36 | 4 | 5 | 35.0% |

ALT_BUY has fewer expected late orders than TRANSFER but a lower chance of no late order. The measures disagree, so the engine does not pick a winner.

## Engine tools (`engine/tools.py`)

These eight tools are offered to the LLM. `run_scenario`, `get_scenario_actions`, `get_catalog` and `get_world_risk` are used by the code (tests, `agent/render.py`) but are not offered to the model. `get_world_risk(disruption_id)` returns the uncertain-receipt-date results described above.

| Tool | What it returns |
|---|---|
| `get_disruption(disruption_id)` | Affected PO, component, dates, delay in days, and a `scope_note` stating what is modelled |
| `get_offers(disruption_id)` | Supplier offers for the affected component, with `is_disrupted_supplier` |
| `get_impact(disruption_id)` | What happens with no action: first late order, late order count, daily C01 shortage |
| `compare_scenarios(budget, objective)` | The four named options ranked, with NORMAL as the undisrupted baseline |
| `get_priority_view(scenario_id \| offer_id+qty+include_transfers)` | Priority-1 orders on time and late for one option |
| `get_order_detail(order_id, option)` | Why one order is late: blocked in the production queue or short of a component, with quantities and a one-sentence `summary` |
| `explore_purchase_qty(offer_id, include_transfers, budget, objective, min_on_time_orders)` | Every valid purchase quantity simulated and ranked. Finds options outside the four named scenarios |
| `propose_action(scenario_id \| offer_id+qty+include_transfers, reason)` | A proposal with metrics and status `pending_approval`. Nothing is executed |

The four named options for disruption D01:

| Option | On-time orders of 12 | Priority-1 on time of 6 | Extra cost USD |
|---|---:|---:|---:|
| WAIT | 5 | 2 | 0 |
| TRANSFER | 8 | 4 | 416 |
| ALT_BUY | 9 | 4 | 1,250 |
| HYBRID | 11 | 5 | 1,306 |

The search finds two options that are not in this list. Transfers plus 40 units from OF02 keep 11 orders on time for 1,216 USD, which is 90 USD less than HYBRID. Transfers plus 65 units keep all 12 orders on time for 1,666 USD.

## Evaluation

`scripts/eval_agent.py` asks 13 golden questions with known answers, each in a fresh conversation, and saves full transcripts to `eval_results/`. A question passes only if:

- the expected tool was called with the expected arguments,
- the key facts appear in the answer,
- every value in the options table matches the engine for that option and column,
- every number, date and ID in the answer appears in a tool result (grounding),
- no proposal was created unless the user asked for one.

The questions cover recommendations under a budget and under another objective, impact, priority customers, the cheaper option found by search, an unsupported hypothetical, approval, order-level explanations, and two multi-turn follow-ups.

Latest results with model `meta-llama/llama-3-3-70b-instruct`:

| Check | File | Result |
|---|---|---|
| 13 golden questions, 1 run, fixed answer layouts | `eval_results/20261107_235717.json` | **13 of 13 passed** |
| 13 golden questions, 3 runs, before the fixed layouts | `eval_results/20261107_220100.json` | 12 of 13 passed every run. Q13 repeated the previous answer in 2 runs, which the fixed order layout removes |
| 19 realistic conversations, 22 answers, read by hand | `eval_results/sweep_20261107_235511.json` | No table mismatch, no ungrounded number, every ★ and proposal matched the request |

The sweep (`python -m scripts.question_sweep`) found problems that the golden questions did not: the recommended option once followed the model's choice of objective instead of the user's budget, and a few question types had no fitting layout. Both were fixed before the latest runs.

Stage 1 added two more sweeps with the same model:

| Check | File | Result |
|---|---|---|
| 25 conversations, 28 answers, first world_risk prompt | `eval_results/sweep_20261112_015014.json` | No flagged answer. One paragraph named the late orders on one date "expected late orders". One correct paragraph was dropped because the stated budget was not shown. Both were fixed |
| Same questions, revised prompt | `eval_results/sweep_20261112_020142.json` | No flagged answer, no dropped paragraph, every number in the world_risk paragraphs carries the right column name. Source of `ui_fixtures/` |

The golden question Q5 ("What if the delay becomes 8 days?") now expects the `world_risk` answer for Nov 19 instead of a refusal. After stage 1 the golden evaluation was run again: `eval_results/20261112_021518.json`, **13 of 13 passed**. Q5 called only `get_disruption`, read the question as Nov 19 and quoted the "Late if it arrives Nov 19" column.

The default model was chosen with this evaluation. See `docs/decisions/0001-default-llm-model.md`.

## Known limitations

- Only disruption D01 is modelled. Receipt dates of PO01 from 11-11 to 11-21 are computed. Later dates, other disruptions and changes to other inputs are not, and the agent says so.
- The receipt-date weights are an assumption (a triangular three-point estimate), not data about the supplier. The latest date is the end of the simulation window, so the right tail is cut and the mean (11-16.3) falls before the announced date.
- Whether a question gets the `world_risk` answer is decided by its wording. A question phrased in an unexpected way can miss it and get a free-text answer. It does not get wrong numbers.
- In `world_risk` answers the code checks that every number in the model's paragraph is in the tables. It cannot see a correct number given the wrong name. The model also sometimes quotes more than three numbers, and once suggested an option without a stated criterion (see ADR 0003).
- `get_impact` (impact with no action) still reports the announced date only.
- Question types without a fixed layout (impact, priority questions, general questions) are still written freely by the model, so their wording varies.
- The evaluation checks tables, facts and number grounding, but not every sentence of prose. Wording is reviewed by hand.
- The model's short reasoning sometimes states a difference it computed itself (for example "$834 less than ALT_BUY"). The ones seen in the sweep were correct, but they are not engine numbers.
- `ibm/granite-4-h-small` can be selected but is not recommended. It wrote numbers that no tool returned in several runs (see the ADR).

## Model assumptions

These simplifications hold in every result the engine returns.

1. **No daily production capacity.** An order starts on the first day all its components are available. Several orders can start on the same day. Long delays are therefore shown shorter than they would be with a capacity limit.
2. **Fixed production queue.** Orders start in order of due date, then priority, then order ID. If the next order cannot start, later orders wait even when their own components are available.
3. **Only the receipt date of PO01 is uncertain.** Lead times of the alternative supplier and the transfer lanes are fixed. Options that rely on them can look safer than they are.
4. **All recovery actions are decided and executed on 11-09.** No option waits for more information before acting.
5. **Simulation window 11-09 to 11-21.** Receipts and order starts are simulated inside this window. A receipt date after 11-21 is not supported yet (stage 2).
6. **Receipt-date weights from a three-point estimate.** See ADR 0002. Extra cost does not depend on the receipt date in the current model.

## Repository layout

```
IBM-Bibimbab/
├── data/                 14 CSV input files + 2 optional world files (synthetic)
├── engine/               Deterministic simulation engine, stdlib only
│   ├── loader.py         Load and validate the CSVs
│   ├── simulate.py       Day-by-day simulation of an action list
│   ├── evaluate.py       KPIs per simulation
│   ├── candidates.py     Transferable quantities, valid purchase quantities
│   ├── analysis.py       Impact, priority view, marginal cost
│   ├── compare.py        Ranking by objective and budget
│   ├── worlds.py         Every option over weighted receipt-date worlds
│   └── tools.py          The API used by the agent
├── agent/                LLM layer (ibm-watsonx-ai)
│   ├── llm.py            watsonx.ai client, retries, argument normalisation
│   ├── tool_specs.py     Tool schemas, argument checks, dispatch
│   ├── prompts.py        System prompt, evidence playbook, answer formats
│   ├── loop.py           run_agent(): gather phase, answer phase, guards
│   ├── render.py         Fixed answer layouts built from engine data
│   ├── overview.py       First screen without an LLM call
│   ├── decisions.py      Human approve/reject log, called only by the UI
│   └── fake_llm.py       Scripted LLM for offline tests
├── scripts/              chat.py, eval_agent.py, question_sweep.py, check_wx.py, make_ui_fixtures.py,
│                         stage1_triangular_worlds.py (temporary)
├── tests/                Engine and agent tests (no network)
├── eval_results/         Saved evaluation transcripts
├── docs/decisions/       Architecture decision records (0001 model, 0002 weights, 0003 answers)
├── docs/extension-plan.md  Stages 1 to 3 of the uncertainty extension
├── reference/            Original reference implementation and data dictionary
├── demo.py               Engine-only walkthrough of the tools
├── docs/ui-contract.md   What the UI receives from run_agent() and how to approve
├── ui_fixtures/          Real agent results for UI work without an API key
└── bob_sessions/         IBM Bob session records per team member
```

Team members: see `CONTRIBUTING.md` for branches, ownership and key rules, and `docs/ui-contract.md` for the UI.

## How IBM Bob was used

`AGENTS.md` and `.bob/` hold the project rules Bob reads before every task.
Each team member's Bob sessions are exported to `bob_sessions/<name>/`.
Each record lists the sessions, the tools Bob called, and the lines Bob wrote per file.
Each session file starts with a prompt index.

| Team member | Scope | Record |
|---|---|---|
| Junseo (Dennis) Choi | Calculation engine: `engine/`, engine tests, `demo.py`, `AGENTS.md` and `.bob/` rules | [bob_sessions/dennis](bob_sessions/dennis/README.md) |
| Sunghyuk (Ian) Yoon | Agent layer: watsonx.ai connection, `agent/`, engine tool additions, evaluation harness. Stage 1 extension: worlds, loader, `engine/worlds.py`, `get_world_risk`, `world_risk` answers | [bob_sessions/ian](bob_sessions/ian/README.md) |

Work done outside Bob is stated in each record.
