# UI handoff prompt

For the UI owner. Read the three steps, then paste the prompt into your AI tool.

1. Work on the `ui` branch. Run `git checkout ui` and `git merge origin/main` before each session.
2. Write the code with IBM Bob and export each Bob task into `bob_sessions/<your name>/`. The submission needs every member's Bob record. Other AI tools are fine for questions.
3. Bob reads `AGENTS.md` by itself. Other tools cannot see the repo, so attach `docs/ui-contract.md`, `AGENTS.md` and `ui_fixtures/agent_results.json` together with the prompt.

Give the prompt one stage at a time. Finish and check a stage before asking for the next one.

---

## Prompt

```text
You are helping me build the web UI for a supply chain recovery decision agent.
The repository is IBM-Bibimbab. I work on the `ui` branch.

READ FIRST
- docs/ui-contract.md : everything the UI receives from the agent. Follow it exactly.
- AGENTS.md, section "UI work" : rules for UI code.
- ui_fixtures/agent_results.json : 23 real agent results. Use them instead of the real agent.

WHAT THE APP DOES
A manager types a question about a supplier delay.
The agent answers with Markdown and, for most questions, a structured `view`.
When the manager asks to act, the agent returns a `proposal`.
A human approves or rejects it in the UI. The agent never approves.

HARD RULES
- Streamlit, single entry file `app.py` at the repo root. Helper modules may go in `ui/`.
- Import only run_agent (agent.loop), record_decision and list_decisions (agent.decisions).
- Do not modify engine/, agent/, data/, tests/expected/ or reference/. If you think a change
  there is needed, stop and tell me what and why.
- Never compute or change a number. Display values from the result as they are.
- Read the view with result.get("view"). The error result has no view.
- No API keys in code. Add only `streamlit` to requirements.txt.
- After each stage, `python -m unittest discover -s tests` must still pass.

STAGES (do only the stage I ask for)

Stage 1. Chat with fixtures (must work end to end)
- A mode switch in the sidebar: "Fixtures" (default) or "Live agent".
- In Fixtures mode, a fake_run_agent(question, history) returns the fixture whose
  "question" matches, otherwise the first fixture. Also show the fixture questions as
  clickable examples so every result can be opened.
- Chat layout with st.chat_input and st.chat_message. Keep the conversation in
  st.session_state. Show result["answer"] with st.markdown.
- If result has "error", show the answer as a warning and a "Try again" button.
Check: every fixture question opens and its answer renders. The error fixture shows the warning.

Stage 2. Views
- recommendation and comparison: show view["situation"], then a table built from view["rows"]
  with columns Option (name and code), On-time orders (x of y), Priority-1 on time (x of y),
  Total days late, Extra cost (USD). Mark the row whose code equals view["recommended"] with ★.
  Mark rows with found_by_search = true as "found by search". Below the table, show the
  rest of result["answer"] (recommendation, trade-offs, next step).
- order: show view["detail"]["summary"] prominently, then the detail fields.
- option: show view["row"] metrics and the answer.
- unsupported: show view["scope_note"] as an info box, then the rows table.
- No view: show the answer only.
- An expander "How the agent got this" listing result["tool_trace"] (tool name and args).
Check: "Our budget is 500 dollars. What should we do?" shows ★ on TRANSFER with 8 of 12 on time
and 416 USD. "Compare TRANSFER and ALT_BUY for priority customers." shows no ★.

Stage 3. Approval
- When result["proposal"] is not None, show the proposal (option code, actions, on-time
  orders, extra cost, status) with a name field, a note field, Approve and Reject buttons.
- On click, call record_decision(proposal, approved, decided_by, note). Show the returned
  entry. Show ValueError messages to the user (for example "already decided").
- A "Decision log" page or sidebar section showing list_decisions() as a table.
- Never show the buttons when there is no proposal.
Check: the fixture "Let's go with TRANSFER." shows the buttons. Approving twice shows the
"already decided" message. Other fixtures show no buttons.

Stage 4. Live agent
- At startup, copy WX_API_KEY, WX_PROJECT_ID, WX_URL, WX_MODEL_ID from st.secrets into
  os.environ if present. Wrap it in try/except because a local run may have no secrets file.
- "Live agent" mode is available only when WX_API_KEY is set. Otherwise show why and stay
  on fixtures.
- In Live mode call run_agent(question, history) and keep result["history"] in
  st.session_state for the next turn. A "New conversation" button clears it.
- Show a spinner while waiting. Never call run_agent on rerun or on button clicks that are
  not a new question (each call costs credits).
Check: with a key, the same question as Stage 2 gives the same table and ★.

Start with Stage 1. First give me a short plan (files and functions), then the code.
```
