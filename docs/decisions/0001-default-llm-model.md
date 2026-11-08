# ADR 0001. Default LLM for the recovery agent

- **Status:** Accepted (confirmed by eval run 3, see below)
- **Date:** 2026-11-07
- **Branch:** `feature/agent`
- **Decision owner:** Sunghyuk (Ian) Yoon

## Context

The agent calls the engine tools through watsonx.ai chat with tool calling.
The model is read from `WX_MODEL_ID`, so any watsonx.ai chat model can be used without code changes.
Two models were tested. Both run on IBM watsonx.ai in us-south through the same project and API key.

| Model | Provider | Reason it was tested |
|---|---|---|
| `ibm/granite-4-h-small` | IBM | The only Granite chat model listed in us-south. IBM-native option. |
| `meta-llama/llama-3-3-70b-instruct` | Meta, hosted on watsonx.ai | Largest instruct model listed in us-south. |

The agent is a decision-support tool.
A wrong number presented as fact is the most serious failure.
Model choice is therefore judged first on factual accuracy against tool results, then on tool selection, then on answer format.

## Method

1. A one-tool connectivity test (`scripts/check_wx.py`). Both models called `compare_scenarios` with `budget: 500`.
2. Manual multi-turn sessions in `scripts/chat.py`.
3. Golden-question evaluation (`scripts/eval_agent.py`), six questions with known answers from the validated engine.

Ground truth used for checking (from `engine/tools.py`):

| Fact | Value |
|---|---|
| D01 delay | 6 days, receipt moved from 2026-11-11 to 2026-11-17 |
| On-time orders of 12 | WAIT 5, TRANSFER 8, ALT_BUY 9, HYBRID 11 |
| Extra cost USD | WAIT 0, TRANSFER 416, ALT_BUY 1,250, HYBRID 1,306 |
| Priority-1 on time of 6 | WAIT 2, TRANSFER 4, ALT_BUY 4, HYBRID 5 |
| Cheaper than HYBRID with 11 on time | transfers + 40 units from OF02, 1,216 USD |

## Evidence

Every answer in `eval_results/20261107_202643.json` was read and compared with the ground truth.
The harness score was 8/12. The score alone was misleading, so the findings below come from the full answers.

### Granite 4 H Small

- **Invented numbers (Q4).** The answer table listed HYBRID as 6 on-time orders for 416 USD and WAIT as 0 priority-1 orders on time. The real values are 11 orders for 1,306 USD and 2 of 6. It also listed a "BUY 5" option that no tool returned.
- **Invented data (Q5).** For "What if the delay becomes 8 days?" it stated a revised receipt date of 2026-11-19 and an 8-day delay as fact. The data says 2026-11-17 and 6 days.
- **Wrong supplier (Q4).** It explored OF01, the offer of the disrupted supplier.
- **Contradiction (eval run 1).** It stated that all priority-1 orders were on time under HYBRID while its own evidence showed 5.
- **Tool loop (manual test).** For "What if the delay becomes 10 days?" it repeated identical `get_impact` and `get_disruption` calls until the 6-step limit.
- **Correct answers.** Q2 and Q6 were correct. Q3 in run 2 was correct ("5 of the 6"), but the harness missed the phrase.

### Llama 3.3 70B Instruct

- **No invented numbers found.** Every number in its answers either matched a tool result or came from a tool error caused by our own code (see below).
- **Unsupported question handled (Q5, manual test).** It stated that only D01 is modelled and did not invent a new delay.
- **Correct answers.** Q2, Q3, Q5 and Q6 were correct.
- **Q1 was wrong but caused by our code.** It sent `budget` as the string `"500"`. Our validation rejected it, so it had no data and answered "n/a". The harness marked it as a pass by mistake.
- **Q4 was wrong.** It picked the 65-unit row and called it 11 on-time orders. That row is 12 orders for 1,666 USD. The correct row (40 units, 11 orders, 1,216 USD) was second in the same list. This shows that scanning a ranked table is unreliable for an LLM, so the fix belongs in the engine.

### Eval run 3 (fresh conversation per question)

File `eval_results/20261107_204509.json`. Run after the fixes for argument types, the target filter and the history leak.
The harness score was Granite 3/6 and Llama 4/6. Every answer was again checked against the ground truth.

| | Granite 4 H Small | Llama 3.3 70B Instruct |
|---|---|---|
| Answers with every fact correct | Q3 | Q1 to Q6 (all six) |
| Answers with invented or wrong facts | Q1 (minor), Q2, Q4, Q5, Q6 | none |
| Process defects | none beyond the wrong facts | Q1 called `propose_action` while it was not offered. Q4 first sent a prompt placeholder as `offer_id`, then recovered. |

Granite errors in run 3, with no shared history this time:

- **Q6.** The table listed WAIT, TRANSFER and ALT_BUY as 0 on-time orders and HYBRID as 6 of 6 priority-1 orders on time. The real values are 5, 8, 9 and 5 of 6. It also listed stock levels that no tool returned. The harness marked this answer as a pass.
- **Q5.** It presented the 6-day results as the outcome of an 8-day delay. It listed 5 of 6 priority-1 orders on time for every option and mentioned a 2,000 USD budget that nobody gave.
- **Q2.** It stated that all orders are back on time after the revised receipt date. The late orders stay late.
- **Q4.** The numbers were right, but it described the option as "buy 40 units" without the transfers. Buying 40 units alone does not reach 11 orders.
- **Q1 (minor).** The main numbers were right. It stated a 3-day transfer lead time. The lanes take 2 and 4 days.

Llama's two failures in run 3 came from our layer, not from wrong facts.
The tool guard hid `propose_action` from the tool list but did not block a call to it.
The playbook contained a placeholder in angle brackets, and the model copied it as an argument.
Both are being fixed.

Run 3 confirms the decision. With a clean conversation per question, Granite still put numbers into answers that no tool returned. Llama did not.

## Decision

- **Default model is `meta-llama/llama-3-3-70b-instruct`.**
- Granite stays selectable through `WX_MODEL_ID` or the `scripts/chat.py` argument for testing.
- Granite is not offered in the demo UI.

Granite was not rejected for style or format.
It was rejected because it put numbers into answers that no tool returned.
The agent design rule says every number must come from a tool result, and Granite broke that rule in two of six questions.

## Limitations of this evidence

- Each question ran once at temperature 0. Six questions are a small sample.
- Run 3 removed the history leak, and the decision did not change.
- Run 2 shared conversation history across questions. The "$500 budget" in Granite's Q4 and Q5 answers leaked from Q1. The invented table values and the invented 2026-11-19 date are not explained by that leak.
- Several failures came from our own layer, not from the models. These were string-typed arguments, truthy `"false"`, and no target filter in `explore_purchase_qty`. Fixes are in progress.

## Consequences

- The IBM platform story is unchanged. Both models run on IBM watsonx.ai with the same credentials and billing.
- Llama is a third-party model. watsonx.ai shows a license notice on first use. `scripts/chat.py` hides only that notice.
- Llama 70B may be slower and use more tokens per question than Granite.

## Revisit when

- Granite scores 6/6 with no invented numbers in two consecutive runs. It is then reconsidered as the default for the IBM-native story.
- A newer Granite chat model appears in us-south.
