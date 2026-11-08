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

## How it works

```
 Manager question ──► agent/ (watsonx.ai LLM, tool calling)
                          │   chooses tools, never computes numbers
                          ▼
                     engine/tools.py (8 tools, pure Python, deterministic)
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
3. **Fixed answer layouts, built by code.** For recommendations, order explanations, proposals and unsupported questions, `agent/render.py` lays out the engine data the same way every time: a situation sentence, an options table with the same rows and columns, a ★ on the option that best meets the user's budget and objective, and a next step the user can say back (for example *"Propose TRANSFER"*). The model writes only the 2 or 3 sentences of reasoning and the trade-offs. Other questions get a free-text answer. Each result also carries a structured `view` that a UI can render directly.
4. **Proposals only on request.** `propose_action` is offered, named in the prompt, and callable only when the user asks to act (approve, propose, implement, submit). When a proposal is created, the answer lists the option, its metrics and each action in plain language, with status `pending_approval`.
5. **Safe failure.** Unsupported questions (new delays, unknown disruptions) get a scope note from the engine instead of invented numbers. If watsonx.ai cannot be reached, the agent retries twice and then returns a message that contains no numbers. If only the reasoning step fails, the engine-built table and recommendation are still shown.
6. **Defensive argument handling.** String numbers and booleans (`"500"`, `"true"`) are coerced, `"null"` is treated as missing, unknown IDs and the disrupted supplier's offer are rejected with a message the model can act on.

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
| Evaluate selected questions | `python -m scripts.eval_agent --only Q5,Q13` | yes |

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

## Engine tools (`engine/tools.py`)

These eight tools are offered to the LLM. `run_scenario`, `get_scenario_actions` and `get_catalog` are used by the code (tests, `agent/render.py`) but are not offered to the model.

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

Result before the fixed answer layouts (`eval_results/20261107_220100.json`, model `meta-llama/llama-3-3-70b-instruct`, 3 runs): **12 of 13 questions passed in all 3 runs.** Q13 (a follow-up asking why SO08 is late under the option found in the previous turn) passed 1 of 3, because the model repeated its previous answer although it had called the right tool. The fixed order layout removes this failure mode, because that answer is now built by code from the tool result. The grounding check found no invented number in any of the 39 answers.

The default model was chosen with this evaluation. See `docs/decisions/0001-default-llm-model.md`.

## Known limitations

- Only disruption D01 with its recorded 6-day delay is modelled. The agent says so and does not simulate hypothetical delays.
- Question types without a fixed layout (impact, priority questions, general questions) are still written freely by the model, so their wording varies.
- The evaluation checks tables, facts and number grounding, but not every sentence of prose. Wording is reviewed by hand.
- `ibm/granite-4-h-small` can be selected but is not recommended. It wrote numbers that no tool returned in several runs (see the ADR).

## Repository layout

```
IBM-Bibimbab/
├── data/                 14 CSV input files (synthetic)
├── engine/               Deterministic simulation engine, stdlib only
│   ├── loader.py         Load and validate the CSVs
│   ├── simulate.py       Day-by-day simulation of an action list
│   ├── evaluate.py       KPIs per simulation
│   ├── candidates.py     Transferable quantities, valid purchase quantities
│   ├── analysis.py       Impact, priority view, marginal cost
│   ├── compare.py        Ranking by objective and budget
│   └── tools.py          The API used by the agent
├── agent/                LLM layer (ibm-watsonx-ai)
│   ├── llm.py            watsonx.ai client, retries, argument normalisation
│   ├── tool_specs.py     Tool schemas, argument checks, dispatch
│   ├── prompts.py        System prompt, evidence playbook, answer formats
│   ├── loop.py           run_agent(): gather phase, answer phase, guards
│   ├── render.py         Fixed answer layouts built from engine data
│   └── fake_llm.py       Scripted LLM for offline tests
├── scripts/              chat.py, eval_agent.py, check_wx.py
├── tests/                Engine and agent tests (no network)
├── eval_results/         Saved evaluation transcripts
├── docs/decisions/       Architecture decision records
├── reference/            Original reference implementation and data dictionary
└── demo.py               Engine-only walkthrough of the tools
```

For developers using IBM Bob, `AGENTS.md` and `.bob/` hold the project rules Bob reads before every task.
