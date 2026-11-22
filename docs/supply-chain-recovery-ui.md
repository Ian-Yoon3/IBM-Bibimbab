# Supply Chain Recovery UI

Streamlit web interface for the Supply Chain Recovery Decision Agent.
Helps an operations manager review recovery options when a supplier delivery is delayed,
see the cost and on-time-delivery impact of each option, and prepare a proposal for
human approval — without needing an AI API key for the demo.

---

## Overview

The UI presents a fictional disruption scenario for NovaTech, a manufacturer whose
key component (C01, Microcontroller) is delayed 6 days by supplier Aster Silicon.
Seven of twelve customer orders are at risk.

The app opens on the **Overview** screen. The right half of the hero section shows a
supply-chain recovery illustration (`ui/assets/supply-chain-recovery.png`).
A "Demo mode" badge in the top-left of the hero confirms no API key is needed.

**Main pages** (sidebar navigation):

| Page | Purpose |
|---|---|
| 🏠 Overview | Situation summary, entry-point CTA, links to Compare and Impact |
| 🔍 Find a recovery plan | Enter a USD budget → agent returns the best option within that budget |
| ⚖️ Compare options | Browse saved examples of side-by-side scenario comparisons |
| 📊 Understand the impact | Browse saved examples showing which orders are affected |

The sidebar also shows a **Mode** selector (Fixtures / Live agent) and a
**New conversation** button that resets all conversation state without deleting
any decision records.

---

## Find a recovery plan

### How it works

1. Navigate to **Find a recovery plan** in the sidebar.
2. Enter a maximum additional budget in USD (integer, 0 – 1,000,000).
3. Click **Find a recovery plan**.

The app calls `run_agent()` with the message:

```
"Our budget is {budget} dollars. What should we do to maximise on-time orders?"
```

The agent runs the simulation engine, compares scenarios within the given budget, and
returns a structured `recommendation` view.

### Result display

When the agent returns a valid recommendation, three KPI cards are shown:

| Card | What it shows |
|---|---|
| 🎯 Budget | The budget you entered |
| 💰 Extra cost | Additional cost of the recommended option; green if within budget, yellow if over |
| 🚚 On-time orders | Count of on-time orders and total late-order days; colour-coded green / yellow / red |

A summary card names the recommended option.
The full agent analysis is available in a collapsed **Full analysis** expander.

An **All options compared** table is also available as a collapsible expander,
listing every scenario with on-time orders, total days late, extra cost, and a
"✓" (within budget) marker.

### Status codes and what they show

| Status | Trigger | UI message |
|---|---|---|
| `ok` | Recommendation within budget found | KPI cards + summary card |
| `key_missing` | `WX_API_KEY` not set | Setup guidance (info banner) |
| `api_error` | API key set but call failed | Connection error (error banner) |
| `unsupported` | Agent returns `view.type == "unsupported"` | Scope note from the backend |
| `over_budget` | Recommended option's `extra_cost` exceeds budget | "Try a higher budget" warning |
| `unverifiable` | Missing structured view, wrong budget in settings, or no recommended row | "Result could not be verified" warning |

Validation is performed by `_validate_find_plan_result()` in `app.py` before
any numbers are shown. The UI never displays a number it cannot verify against the
structured `view` data.

---

## Compare options

The **Compare options** page uses saved fixture examples. No API call is made.

A drop-down labelled **Saved examples** lists all 23 fixture entries.
Selecting one displays:

- The example question (labelled "Example question:") in a user chat bubble.
- The agent response in an assistant chat bubble, rendered according to its view type.

For `comparison` views, an **All options compared** table is expanded by default,
showing each option's name, on-time orders, total days late, and extra cost.
No star is shown because a comparison view has no single recommended option
(`recommended` is `None`).

For `recommendation` views, the recommended option is starred (★) in the table
and a summary card is shown.

A free-text input at the bottom accepts typed questions; in Fixtures mode it matches
only the exact text of a saved example. Unmatched input shows:

> "This demo uses saved examples. Choose an example, or use Live agent for a new analysis."

---

## Understand the impact

The **Understand the impact** page shares the same fixture-based layout as Compare options.

For `order` view fixtures (e.g. "Why is SO05 late?"), the response shows:

- An order detail card with due date, delivery date, and a delay badge (days late or on time).
- A one-sentence summary written by the engine (`detail.summary`).
- A **Full analysis** expander with the full agent answer.

For `option` view fixtures (e.g. "What does HYBRID involve?"), two KPI cards
(extra cost, delivery impact) and a summary card are shown.

---

## Error handling

The following situations are handled and surfaced to the user:

| Situation | Handled by | User-visible message |
|---|---|---|
| `WX_API_KEY` not set when budget form is submitted | `_page_find_plan()` → `render_api_key_missing()` | Info banner: "API connection required" |
| `run_agent()` raises an exception | `try/except` in `_page_find_plan()` | `fp_status = "api_error"` |
| Agent returns `result["error"]` key | `_validate_find_plan_result()` | Error banner via `render_find_plan_result()` |
| Agent returns `unsupported` view | `_validate_find_plan_result()` | Scope note info banner |
| Recommended option exceeds budget | `_validate_find_plan_result()` | "Over budget" warning with suggestion to try a higher budget |
| Response lacks structured data | `_validate_find_plan_result()` | "Result could not be verified" warning |
| Fixture entry is an error result | `is_error_fixture()` → `render_error_retry_banner()` | Warning banner + **Try again** button |
| Free-text input does not match any saved example | `_add_typed_question_to_conversation()` | Limitation info message |
| Live agent selected (no API key path) | `render_live_unavailable()` | Locked banner on all non-budget pages |

Each **Try again** button for a historical error message in the conversation
carries a unique key (`retry_{idx}`) to avoid Streamlit duplicate-element-ID errors.

---

## Local setup

### Requirements

- **Python 3.11 or newer** (required for the full project, including the backend engine)
- Git checkout of the `ui` branch

### Installation

```bash
# Clone the repository and enter the project root
git clone https://github.com/Ian-Yoon3/IBM-Bibimbab.git
cd IBM-Bibimbab

# Create and activate a virtual environment (Python 3.11+)
python3.11 -m venv .venv311
source .venv311/bin/activate   # Windows: .venv311\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

`requirements.txt` includes `streamlit`, `ibm-watsonx-ai`, and `python-dotenv`.

### Running the app

```bash
# From the project root with the virtual environment active:
python -m streamlit run app.py
```

Streamlit prints a local URL (usually `http://localhost:8501`). Open it in a browser.

The app starts in **Fixtures mode**. All 23 saved examples work immediately
without any credentials.

### Environment variables for live agent mode

Copy `.env.example` to `.env` and fill in the following values.
**Never commit `.env` or paste actual key values into source files or commits.**

| Variable | Description |
|---|---|
| `WX_API_KEY` | IBM Cloud API key with access to watsonx.ai |
| `WX_PROJECT_ID` | watsonx.ai project ID |
| `WX_URL` | watsonx.ai service URL (e.g. `https://us-south.ml.cloud.ibm.com`) |
| `WX_MODEL_ID` | Model identifier (e.g. `meta-llama/llama-3-3-70b-instruct`) |

The `.env` file and `.venv311/` directory are gitignored and must not be committed.

On **Streamlit Community Cloud**, enter these values in the app's hosting settings
(not in the repository). The app copies them from `st.secrets` into `os.environ`
at startup so `agent/llm.py` can read them.

---

## Validation and limitations

### Verified with mock agent responses (no live API required)

The following behaviours are tested and confirmed with Streamlit AppTest and
`unittest`, using `ui_fixtures/agent_results.json` (23 entries) and mock `run_agent`
functions — no real watsonx.ai calls are made in any test:

| Behaviour | Test class |
|---|---|
| All 23 fixture entries are selectable and display their answer immediately | `TestRegressionA_FirstSelectionDisplaysAnswer` |
| Selector does not replay a stale fixture after a typed question is submitted | `TestRegressionB_SelectorDoesNotOverrideTypedQuestion` |
| Repeated error fixtures do not crash with duplicate Streamlit button IDs | `TestRegressionC_RepeatedErrorFixturesNoCrash` |
| Live mode blocks fixture controls on all pages (find_plan, compare, impact) | `TestRegressionI_LiveModeBlockedAllPages` |
| New conversation clears all conversation state and selection-tracking keys | `TestRegressionH_NewConversationClearsTracking` |
| Switching Fixtures → Live → Fixtures gives an empty conversation | `TestRegressionJ_ReturnFromLiveToFixtures` |
| Two app sessions do not share `display_messages` state | `TestRegressionK_SeparateSessionsDoNotShareState` |
| Unmatched typed input shows the limitation message, not a reused result | `TestRegressionG_UnmatchedInputAfterResult` |
| Budget form `key_missing`, `ok`, `over_budget`, `unverifiable`, `api_error` paths | `test_find_plan.py` |
| Previous result is cleared before each new budget submission | `test_find_plan.py` |
| Backend simulation engine: 291 tests all pass | `tests/` |
| Reference verification: 5 scenarios, 60 orders, costs, inventory conservation | `reference/verify.py` |

**Test counts (Python 3.11, `.venv311/`):**

| Suite | Tests | Result |
|---|---|---|
| `python -m unittest discover -s tests` | 291 | All pass |
| `python -m unittest discover -s ui/tests` | 125 | All pass |
| `python reference/verify.py` | — | PASS |

### Not yet verified with a real watsonx.ai environment

The following items require a live `WX_API_KEY` and have not been tested:

- **Live agent mode end-to-end:** `run_agent()` called from the budget form with a real
  watsonx.ai model. The UI code path is implemented and unit-tested with mocks.
- **Streamlit Community Cloud deployment:** `st.secrets` injection is implemented but
  has not been exercised on the hosted platform.
- **Multi-turn conversation in the UI:** The agent supports multi-turn via `history`,
  but the current UI uses single-turn calls on the Find-a-plan page.
- **Proposal approval / rejection:** `record_decision()` is imported and the UI
  contract is followed, but the approve/reject buttons are not yet wired to a UI form.
- **Decision log screen:** Marked as upcoming in the sidebar ("Saved examples" disabled button).

> **Note:** User registration, login, and production deployment are not represented in the
> current codebase. They are not listed as completed features.

---

## Repository files

| Path | Purpose |
|---|---|
| `app.py` | Streamlit entry point; page routing, sidebar, budget form, fixture chat |
| `ui/state.py` | Session-state initialisation, reset, navigation helpers |
| `ui/fixtures.py` | Load and catalogue `ui_fixtures/agent_results.json` |
| `ui/renderers.py` | CSS injection, view-type renderers, error/retry banners |
| `ui/assets/supply-chain-recovery.png` | Overview hero illustration |
| `ui_fixtures/agent_results.json` | 23 real agent results for Fixtures mode |
| `ui/tests/` | Streamlit AppTest regression tests and unit tests for UI modules |
| `docs/ui-contract.md` | API contract between the UI and `run_agent()` |
| `.streamlit/config.toml` | Streamlit theme and server configuration |
| `.env.example` | Template for required environment variables (never commit `.env`) |
