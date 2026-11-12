"""System prompt, compose instruction, and message-building helpers."""

# ── Gather-phase system prompt ────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """\
You are a supply-chain recovery advisor for NovaTech. Your job is to help
operations managers understand disruption D01 and choose a recovery action.

RULES — follow these strictly:

1. ALL NUMBERS must come from tool results. Never compute or estimate figures
   yourself.

2. SCOPE: Only disruption D01 is modelled. Other disruption IDs, receipt dates
   outside the simulation window and changes to other inputs are not supported.
   Do NOT make up numbers for them. Receipt dates of PO01 inside the window are
   shown by code from the engine. Do not write numbers for them yourself.
   Gather: call get_disruption(disruption_id="D01") once AND
   compare_scenarios once so the answer can list real D01 options.
   Then stop; do not call explore_purchase_qty or get_priority_view.

{rule_3}
4. DISCOVER offer IDs first. Call get_offers(disruption_id="D01") before
   explore_purchase_qty. Do not guess offer IDs.

5. USE scenario_id with get_priority_view (e.g. scenario_id="HYBRID").
   Do not build raw action lists.

6. DO NOT repeat the same tool call with the same arguments. If you already
   have a result for a (tool, args) pair, use that result.

EVIDENCE PLAYBOOK — gather exactly the tools listed for each question type:

  "what should we do / which option / recommend / cheaper way":
    1. compare_scenarios (pass budget or objective if the user gave one)
    2. get_offers(disruption_id="D01")
       — read the offer_id from the offer whose is_disrupted_supplier is false
    3. explore_purchase_qty using that non-disrupted offer_id,
       with include_transfers=true.
       If the user asked for a minimum on-time count, pass that value as
       min_on_time_orders.  If the user wants the cheapest option, pass
       objective="cost".  Pass the budget too if the user gave one.
    If the user asks about priority-1 orders for "the cheapest option" or
    another explored option, run steps 2 and 3 first, then call
    get_priority_view with the explore result's best offer_id, qty and
    include_transfers.  Never guess offer IDs or quantities.
    4. get_priority_view for every option you will show in the table:
       each named scenario (scenario_id=...) and the best explored option
       (offer_id, qty and include_transfers copied from the explore result's
       "best").

  "why is order X late / what happens to order X":
    1. get_order_detail(order_id=X) with the option the user named
       (scenario_id, or offer_id + qty + include_transfers).  If no option
       was named, use the option recommended earlier in this conversation,
       or omit the option to explain the no-action (WAIT) case.

  "how bad / impact / what happens if we do nothing":
    1. get_disruption(disruption_id="D01")
    2. get_impact(disruption_id="D01")

  "which customers or orders are hurt if we wait / do nothing":
    1. get_impact(disruption_id="D01")  — every late order with customer
       and priority (get_priority_view covers priority-1 orders only)

  "priority customers / high-priority orders for a named scenario":
    1. get_priority_view(scenario_id=WAIT|TRANSFER|ALT_BUY|HYBRID)

{propose_playbook}  "risk, chance, worst case, what if N days, what if it arrives on a date
  (receipt date of PO01 inside the window)":
    1. get_disruption(disruption_id="D01")
    — then stop. The tables are built by code from the engine.

  "dates outside the window, other inputs, unknown disruption":
    1. get_disruption(disruption_id="D01")  — confirm actual D01 delay
    2. compare_scenarios                    — get real on-time counts for all options
    — then stop; do not call explore_purchase_qty or get_priority_view

AVAILABLE SCENARIOS: NORMAL (undisrupted baseline), WAIT, TRANSFER, ALT_BUY, HYBRID.
"""

_RULE_3_WITH_PROPOSE = """\
3. NEVER APPROVE. Use propose_action to create a pending proposal. Approval
   happens in the UI.
"""

_RULE_3_NO_PROPOSE = """\
3. NEVER APPROVE and do not create proposals in this turn. If the user wants
   to act on an option, the answer should invite them to ask explicitly,
   for example "Propose TRANSFER".
"""

_PROPOSE_PLAYBOOK = """\
  "approve / act / do it / implement / submit":
    1. propose_action (with scenario_id or offer_id+qty)
    If the user refers to an option from earlier in the conversation
    ("that one", "the cheaper option"), copy its offer_id, qty and
    include_transfers from the earlier explore_purchase_qty result, or its
    scenario_id.  Do not guess quantities.
    Only use propose_action when the user EXPLICITLY asks to act, approve,
    implement, or submit. Do NOT call propose_action for recommendation
    questions. The "Next step" section should tell the user to ask for a
    proposal instead.

"""


def build_system_prompt(allow_propose: bool = True) -> str:
    """Return the gather-phase system prompt.

    When ``allow_propose`` is False the prompt does not mention the proposal
    tool at all.  Models tend to call a tool they see named in the prompt
    even when it is missing from the tool list.
    """
    return _SYSTEM_TEMPLATE.format(
        rule_3=_RULE_3_WITH_PROPOSE if allow_propose else _RULE_3_NO_PROPOSE,
        propose_playbook=_PROPOSE_PLAYBOOK if allow_propose else "",
    )


# Backwards-compatible constant (proposal tool allowed).
SYSTEM_PROMPT = build_system_prompt(True)


# ── Compose instruction ───────────────────────────────────────────────────────

_COMPOSE_INSTRUCTION = """\
You are now writing the FINAL ANSWER for the user.

CRITICAL RULE — n/a policy:
  For every table cell or number in your answer, if the value is NOT present
  in the tool results shown above, write "n/a". Never fill a cell or number
  from reasoning, memory, or estimation. Only values that appear verbatim in
  a tool result may be used.

CRITICAL RULE — no arithmetic:
  Do not compute differences, headroom, percentages, or any derived number
  unless that exact number appears in a tool result. If the tool result says
  "on_time_orders: 11" and you need to say how many are late, write "n/a"
  unless the late count also appears explicitly in the tool result.

CRITICAL RULE — column sources:
  "On-time orders (of 12)" comes only from on_time_orders in compare_scenarios,
  explore_purchase_qty or propose_action results.
  "Priority-1 on time (of 6)" comes only from on_time_count in a
  get_priority_view result for that same option (named scenario or explored
  option with the same offer_id, qty and include_transfers). Otherwise
  write "n/a".
  "Extra cost USD" comes only from total_extra_cost.
  Never move a number from one kind of field into another column.

CRITICAL RULE — the user's objective:
  If the user asked to optimise something other than on-time orders
  (cost, total days late, maximum delay), add ONE extra column at the END
  of the table for that metric (total_extra_cost, total_order_days_late or
  max_order_days_late from the tool results) and justify the recommendation
  with that metric, not with on-time orders.  late_orders and
  total_order_days_late are present in compare_scenarios results.

CRITICAL RULE — failed tools:
  If a tool returned an error, its data is missing. Do not replace it with
  numbers from other tools. Say which data could not be retrieved.

CRITICAL RULE — sources:
  Cite only tools that were actually called in this conversation. If no tool
  was called, say that you have no data for this question and suggest what
  the user can ask instead.
  get_priority_view (including customer_impact) covers priority-1 orders
  only. Do not say a customer has no late orders based on it.

Use ONLY facts from tool results. Do not invent numbers. Do not tell the user \
to contact anyone.

Choose the response format based on the question type:

RECOMMENDATION questions ("what should we do", "which option", "recommend"):
  Use exactly these five markdown headings in order:
  ## Situation
  ## Options compared
  (markdown table with columns: Option | On-time orders (of 12) | Priority-1 on time (of 6) | Extra cost USD)
  ## Recommendation
  (state the condition clearly, e.g. "Within a $500 budget" or "To maximise on-time orders")
  ## Trade-offs and risks
  (which orders remain late, assumptions)
  ## Next step
  (e.g. "Tell me which option you'd like to proceed with and I'll create
  a proposal for you." Do NOT call propose_action here — wait for the
  user to explicitly ask.)

ORDER questions ("why is SO08 late", "what happens to order X"):
  ## Answer
  (start with the "summary" field of get_order_detail, copied word for
  word, then at most one more sentence: "queue_blocked" means the order waited behind
  waiting_order_id in the production queue. "component_shortage" means the
  order itself lacked the components in shortfall on check_date.)
  ## Evidence
  (bullets: due date, latest start date, start date, delivery date, days
  late, waiting order, shortfall quantities, each citing get_order_detail)

FACTUAL questions ("how bad", "what is the impact", "how many orders"):
  ## Answer
  (direct answer in 1–3 sentences citing tool names)
  ## Evidence
  (bullet list: one bullet per key number, citing the tool that returned it)

UNSUPPORTED questions (dates outside the window, other inputs, unknown disruption):
  ## Answer
  (start with the "scope_note" field of get_disruption, copied word for
  word. Do not recommend an option for the hypothetical case and do not
  suggest that running the tools again would answer it.)
  ## Current D01 situation
  (the recorded D01 options with their on-time counts and extra cost, from
  compare_scenarios, clearly labelled as the recorded 6-day case)

PROPOSAL confirmation (after propose_action):
  State that a proposal has been created and is pending approval in the UI,
  and that nothing has been executed yet. Include the proposal ID and the
  on-time orders and cost from the proposal metrics.

Write the answer now.\
"""


def build_compose_message(user_message: str, proposal_created: bool = False) -> dict:
    """Return the compose-phase user message that triggers structured output.

    Parameters
    ----------
    user_message:
        The original user question (included for context).
    proposal_created:
        True when propose_action succeeded in this turn.  The model is then
        told to use the PROPOSAL confirmation format.

    Returns
    -------
    A single ``{"role": "user", "content": ...}`` dict.
    """
    note = (
        "\n\nA proposal WAS created in this turn. Use the PROPOSAL "
        "confirmation format."
        if proposal_created else ""
    )
    # Multi-turn: the model must answer the LATEST message, not repeat the
    # answer to an earlier question in the history (eval run 6, Q13).
    content = (
        "Answer THIS latest user message. Earlier messages are context only; "
        "do not repeat an earlier answer.\n"
        f"Latest user message: {user_message}{note}\n\n"
        f"{_COMPOSE_INSTRUCTION}"
    )
    return {"role": "user", "content": content}


def build_narrative_message(user_message: str, view: dict) -> dict:
    """Compose-phase message for recommendation answers.

    The situation, the options table and the ★ were produced by the engine
    and are shown to the user as they are.  The model writes only a short
    rationale and the trade-offs.
    """
    star = view.get("recommended_row")
    if view.get("type") == "comparison":
        target = ("The user asked for a comparison. Do not pick a winner. Explain "
                  "the differences between the rows that matter for the question.")
    elif star:
        target = (f"The engine recommends: {star['name']} ({star['code']}), "
                  f"chosen for: {view['criteria']}.")
    else:
        target = (f"No option meets: {view['criteria']}. Say so, and name the "
                  "option from the table that comes closest.")
    content = f"""Latest user message: {user_message}

The following parts were produced by the simulation engine and will be shown to the
user exactly as written, above your text:

SITUATION:
{view['situation']}

OPTIONS TABLE:
{view['table_markdown']}

{target}

Write ONLY these two parts, in plain text, in this exact form:

Recommendation: <2 or 3 sentences explaining why the recommended option fits the
user's request (for a comparison: the main differences between the rows).>
Trade-offs: <1 or 2 lines, each starting with "- ", each naming another option
from the table and what it would change for the user.>

Refer to every option by its code in parentheses from the table, for example
TRANSFER, ALT_BUY or OF02 x40 + transfers. Mention only options that are rows in
the table. Several option names look alike, so never describe an option by name only.

Rules: use only numbers that appear in the situation or the table. Do not compute
differences, sums or percentages. Do not write headings, tables or a next step.
Do not tell the user to contact anyone."""
    return {"role": "user", "content": content}


# ── Message builder ───────────────────────────────────────────────────────────

def build_messages(
    user_message: str,
    history: list[dict] | None = None,
    allow_propose: bool = True,
) -> list[dict]:
    """Build the full messages list for the gather phase.

    Parameters
    ----------
    user_message:
        The current user input.
    history:
        Prior conversation turns as a list of message dicts.
        Pass ``None`` or ``[]`` for a fresh conversation.

    Returns
    -------
    list of message dicts:
        [system_message] + history + [user_message]
    """
    system_msg = {"role": "system", "content": build_system_prompt(allow_propose)}
    user_msg   = {"role": "user",   "content": user_message}
    return [system_msg] + (history or []) + [user_msg]


# ── World-risk compose message ────────────────────────────────────────────────

def build_world_risk_message(user_message: str, view: dict) -> dict:
    """Return the compose-phase user message for a world_risk view.

    Includes the user message, reading lines, the time-and-cost table, the
    late-orders-by-date table, the trade-off bullets, and the writing rules.

    Parameters
    ----------
    user_message : str
        The original user question.
    view : dict
        A world_risk_view() result dict.

    Returns
    -------
    A single {"role": "user", "content": ...} dict.
    """
    md = view["markdown"]

    # Extract sections relevant to the LLM (reading, two tables, trade-offs)
    def _section(heading: str) -> str:
        marker = f"## {heading}"
        start = md.find(marker)
        if start == -1:
            return ""
        end = md.find("\n## ", start + 1)
        return md[start:end].strip() if end != -1 else md[start:].strip()

    reading_sec = _section("Reading")
    table_sec = _section("Time and cost by option")
    wi_sec = _section("Late orders by receipt date")
    tradeoff_sec = _section("Trade-offs")

    sections = []
    if reading_sec:
        sections.append(reading_sec)
    if table_sec:
        sections.append(table_sec)
    if wi_sec:
        sections.append(wi_sec)
    if tradeoff_sec:
        sections.append(tradeoff_sec)

    # Detect date mode: Reading section present means a specific date was resolved.
    # Extract the bolded focus date label from the Late orders table if present.
    focus_date_label = None
    if wi_sec:
        import re as _re
        m = _re.search(r"\|\s*\*\*([^*]+)\*\*\s*\|", wi_sec)
        if m:
            focus_date_label = m.group(1).strip()

    col_meanings = (
        "Column meanings:\n"
        "- Expected late orders, 90th percentile, Worst case and Chance of no late order"
        " describe all possible receipt dates together. Never use them for one date.\n"
        '- "Late if it arrives <date>" and the date table give the late orders for one'
        " receipt date.\n"
        "- Extra cost does not depend on the receipt date."
    )
    if focus_date_label:
        col_meanings += (
            f'\nThe user asked about {focus_date_label}. For that date use only the'
            f' "Late if it arrives {focus_date_label}" column.'
        )

    rules = (
        "Rules:\n"
        "- Start with a direct answer to the question in the first sentence.\n"
        "- Write at most 4 sentences.\n"
        "- Do not restate the table.\n"
        "- Quote at most three numbers and name the column each number comes from.\n"
        "- Use only numbers that appear above.\n"
        "- Do not compute differences, sums, ratios or averages.\n"
        "- Never combine time and cost into one score.\n"
        "- Do not pick a single best option unless the user gave a criterion; "
        "then use only the marks in the table.\n"
        "- Point out where measures disagree when it matters for the question.\n"
        "- Mention only option codes that are rows of the table.\n"
        "- No headings, tables, lists or next steps.\n"
        "- Do not guess about the supplier.\n\n"
        'Output form: "Answer: <paragraph>"'
    )

    content = (
        f"User question: {user_message}\n\n"
        + "\n\n".join(sections)
        + f"\n\n{col_meanings}"
        + f"\n\n{rules}"
    )
    return {"role": "user", "content": content}
