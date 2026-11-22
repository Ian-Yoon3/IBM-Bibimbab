# Bob Sessions — hyunsoo

This folder stores IBM Bob task exports and screenshots for the **hyunsoo** team member,
as required by the team submission guidelines in `CONTRIBUTING.md`.

---

## Sessions

### Session 1 — Stage A UI Implementation (2026-11-17)

**Task:** Implement Stage A of the Supply Chain Recovery Decision Agent UI.

**Prompt used:** `IBM_Bob_UI_Implementation_Prompt_EN.txt`  
*(Attached to Bob; full text available from the team shared document.)*

**Files created or modified:**

| File | Purpose |
|---|---|
| `app.py` | Streamlit application entry point |
| `ui/__init__.py` | Package marker |
| `ui/fixtures.py` | Fixture loading and unique selection |
| `ui/state.py` | Session-state management |
| `ui/renderers.py` | Response rendering (answer + markdown) |
| `ui/tests/__init__.py` | Test package marker |
| `ui/tests/test_fixtures.py` | 21 fixture unit tests |
| `ui/tests/test_state.py` | 13 state unit tests |
| `.streamlit/config.toml` | Theme settings |
| `requirements.txt` | Added streamlit |
| `docs/ui-runbook.md` | Run instructions |
| `docs/ui-validation.md` | Validation report |
| `bob_sessions/hyunsoo/README.md` | This file |

**Test results:**
- UI tests: 34 / 34 pass (`python -m unittest discover -s ui/tests -v`)
- Backend tests: 5 / 17 pass — 7 import errors + 1 failure are pre-existing
  Python 3.9 incompatibilities in `engine/simulate.py`; not introduced by this work.

**What you can do after Stage A:**
- Start the app: `source .venv/bin/activate && python -m streamlit run app.py`
- Browse to `http://localhost:8501`
- Select any of the 23 saved examples in the drop-down
- Successfully and error examples that share a question are independently selectable
- Use "New conversation" to reset the session
- Switching between Fixtures and Live clears history

**Bob task export:**  
Automatic export was not available in this session. To export manually:
open the Bob session in the UI, click the export/download icon, and save
the file here as `session1_stage_a.json` or similar.

**Next stage:** Stage B — budget form, exact fixture-settings matching,
structured renderers (tables, KPI cards).

---

### Session 2 — Stage A UI Repair (2026-11-21)

**Task:** Fix verified Stage A UI defects on the `ui` branch (commit 9b2be78).

**Files modified:**

| File | Change |
|---|---|
| `app.py` | Rewrote fixture selection/rendering to use `display_messages`; added live mode guard; selector key cleanup on mode switch and New conversation |
| `ui/state.py` | Fixed shared mutable default for `display_messages` (fresh list per session) |
| `ui/tests/test_state.py` | Scoped fake Streamlit stub — restores `sys.modules["streamlit"]` and `sys.modules["ui.state"]` after import |
| `ui/tests/test_app_regression.py` | New: 20 AppTest regression tests covering both defects |
| `docs/ui-runbook.md` | Updated: Python 3.11, `.venv311/`, removed Python 3.9 claims, clarified Live mode unavailability |
| `docs/ui-validation.md` | Replaced: documents defects, fixes, actual test counts |
| `bob_sessions/hyunsoo/README.md` | This file |

**Defects fixed:**

1. **Live mode did not block fixture interactions** — Switching to Live mode
   left the previously selected fixture visible. The overview page showed a
   misleading watsonx.ai credit warning. Non-overview pages had no guard.
   Fixed by adding `_live_mode_guard()`, returning early with
   `render_live_unavailable()` on all pages in Live mode, and explicitly
   deleting selector widget keys on mode switch.

2. **Typed question answers disappeared on rerun** — `display_messages` was
   never populated; results were rendered only once on the submission run.
   Fixed by recording every submission in `display_messages` and replaying
   via `_render_display_messages()` on every render pass. Also fixed a shared
   mutable default (`display_messages = []` in `_DEFAULTS`) that caused
   cross-session contamination between AppTest instances.

**Test results:**
- Backend tests: 291 / 291 pass
- UI tests: 54 / 54 pass (34 unit + 20 AppTest regression)
- Reference verification: PASS
- Browser verification: **not performed** — AppTest only

**Reviewed commit:** 9b2be7893602514a38000b67ff14a4c159d944d9
**Changes are local only.** No commit, push, or PR was made.

---

### Session 3 — Stage A UI Repair (2026-11-22)

**Task:** Fix three verified Stage A regressions on the `ui` branch (commit 495b7f5).

**Python:** 3.11.18  
**Streamlit:** 1.67.0  
**Virtual environment:** `.venv311/`

**Files modified:**

| File | Change |
|---|---|
| `app.py` | Fixed `_fixture_selector()`: process selection before rendering, `st.rerun()` on new selection; added `last_handled_selector_*` tracking to prevent selector replay (Regression B); `_render_display_messages()` passes unique `msg_key` per message to retry banner |
| `ui/renderers.py` | Added `msg_key` keyword arg to `render_error_retry_banner()`; passes it as `key=f"retry_{msg_key}"` to `st.button()` to prevent duplicate element IDs (Regression C) |
| `ui/state.py` | `reset_conversation()` now clears `last_handled_selector_*` keys |
| `ui/tests/test_app_regression.py` | Added 17 new AppTest tests (Cases A–K) covering all three regressions |
| `docs/ui-validation.md` | Replaced: documents all three regressions, fixes, corrected test counts |
| `bob_sessions/hyunsoo/README.md` | This file |

**Regressions fixed:**

1. **Regression A — First fixture selection did not display its answer**  
   Root cause: `_render_display_messages()` was called before `_add_fixture_to_conversation()`;
   the `pass` where `st.rerun()` should have been.  
   Fix: process selection first, then `st.rerun()` only when a new selection is handled.

2. **Regression B — Previous selector value overrode a new typed question**  
   Root cause: selector was processed on every render; idempotency check used only the last
   message's fixture_id — which changed after a typed submission, causing the old selector
   value to replay.  
   Fix: `last_handled_selector_{page_hint}` session key tracks the last *processed* fixture_id
   independently of the conversation. Selection is only processed when the chosen_id differs
   from that key. `reset_conversation()` and mode switches clear it.

3. **Regression C — Repeated error examples crashed with duplicate button IDs**  
   Root cause: `render_error_retry_banner()` called `st.button("Try again")` without a `key=`
   argument; multiple historical error messages each rendered the same unkeyed button.  
   Fix: `render_error_retry_banner()` now accepts `msg_key: str`; `_render_display_messages()`
   passes the message index as `msg_key`.

**Test results:**
- Backend tests: **291 / 291 pass**
- UI tests: **71 / 71 pass** (34 unit + 37 AppTest regression)
  - Previous AppTest count: 20 (Session 2)
  - New AppTest count: 37 (Session 3, +17 new tests)
  - `TestLiveModeBlocking` count corrected: **10** tests (not 11 as stated in Session 2 report)
- Reference verification: **PASS**
- Browser verification: **not performed** — AppTest only

**Reviewed commit:** 495b7f5f06eade6d6cb1bea076f0715fe4c793a5  
**Changes are local only.** No commit, push, or PR was made. The user will review and commit personally.
