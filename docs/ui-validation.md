# UI Validation Report — Stage A (Repaired)

**Date:** 2026-11-21  
**Branch:** ui (commit 9b2be78 + local Stage A repairs)  
**Python:** 3.11.18 (virtual environment `.venv311/`)  
**Streamlit:** 1.67.0

---

## 1. Environment inspection

| Item | Result |
|---|---|
| Working directory | `/Users/hyunsoo/Downloads/IBM-Bibimbab-ui` |
| OS | macOS 23.6.0 arm64 |
| Python | 3.11.18 |
| Virtual environment | `.venv311/` |
| `app.py` exists | ✅ |
| `ui/` directory exists | ✅ |
| `.streamlit/` directory exists | ✅ |
| `ui_fixtures/agent_results.json` | ✅ Unchanged (23 entries) |

---

## 2. Historical context — Python 3.9 environment (prior session)

A previous validation session used Python 3.9.6 with a `.venv/` environment.
On that version, 7 import errors and 1 test failure occurred due to `str | None`
union-type syntax in `engine/simulate.py`, which is not supported on Python 3.9.
Those failures were pre-existing and not introduced by UI work.

**The current session uses Python 3.11.18.** All 291 backend tests pass on this
version. The Python 3.9 incompatibility is not an `engine/simulate.py` defect
requiring code changes — it is a Python version requirement.

---

## 3. Backend test run

Command:
```
.venv311/bin/python -m unittest discover -s tests -v
```

Result: **291 tests, 0 failures, 0 errors — ALL PASS**

---

## 4. Reproduced defects

The following two defects were identified by real app interaction testing
on the reviewed commit (9b2be78) and have been fixed in this repair session.

### Defect 1 — Live mode did not block fixture interactions

**Cause:**
- `switch_mode()` cleared conversation state correctly, but the mode radio
  widget's previous value remained in `st.session_state`, causing a rerun to
  immediately reload the previously selected fixture.
- The overview page displayed a misleading "Submitting a request will call
  watsonx.ai" warning even though live integration is not implemented.
- Non-overview pages (`find_plan`, `compare`, `impact`) had no rendering guard
  for Live mode; fixture selectors and question forms were still shown.

**Fix:**
- Added a `_live_mode_guard()` check in `main()` that returns early with
  `render_live_unavailable()` for all non-overview pages when in Live mode.
- Overview page now calls `render_live_unavailable()` and returns early
  when in Live mode (removes the misleading watsonx.ai warning).
- Mode switch and "New conversation" now explicitly delete selector widget
  keys (`fixture_selector_<page_hint>`) from `st.session_state` to prevent
  Streamlit from restoring the old selection on the next rerun.
- Sidebar caption updated from "🤖 Live agent (requires API key)" to
  "🔒 Live agent — not available in Stage A".

### Defect 2 — Typed question answers disappeared on rerun

**Cause:**
- `_handle_fixture_selection()` and `_free_text_input()` rendered results
  imperatively on the submission run only. `display_messages` was never
  populated, so subsequent reruns had nothing to re-render.
- `_DEFAULTS["display_messages"] = []` assigned a single shared list to all
  sessions; multiple AppTest instances in the same process shared the same
  list object, causing cross-test contamination.

**Fix:**
- Introduced `display_messages` as the persistent conversation store.
  Each submitted question (typed or selector) is recorded via
  `_add_typed_question_to_conversation()` or `_add_fixture_to_conversation()`.
- Added `_render_display_messages()`, called on every render pass, to
  replay all stored messages from `display_messages`.
- Idempotency check in `_add_fixture_to_conversation()` prevents
  duplicate messages on repeated reruns with the same fixture selected.
- Fixed `ui/state.py`: `display_messages` is now created as a **fresh list**
  per session (`if "display_messages" not in st.session_state: ... = []`)
  instead of assigning the shared `_DEFAULTS` list object.

---

## 5. UI test run

Command:
```
.venv311/bin/python -m unittest discover -s ui/tests -v
```

Result: **54 tests, 0 failures, 0 errors — ALL PASS**

| Test module / class | Tests | Result |
|---|---|---|
| `test_fixtures.TestLoadFixtures` | 4 | ✅ |
| `test_fixtures.TestFixtureIds` | 3 | ✅ |
| `test_fixtures.TestGetResultCopy` | 4 | ✅ |
| `test_fixtures.TestIsErrorFixture` | 2 | ✅ |
| `test_fixtures.TestLabelFor` | 3 | ✅ |
| `test_fixtures.TestGetFixtureOptions` | 3 | ✅ |
| `test_fixtures.TestUnmatchedMessage` | 1 | ✅ |
| `test_state.TestInitState` | 4 | ✅ |
| `test_state.TestResetConversation` | 3 | ✅ |
| `test_state.TestSwitchMode` | 5 | ✅ |
| `test_state.TestNavigateTo` | 2 | ✅ |
| `test_app_regression.TestTypedQuestionPersistence` | 6 | ✅ |
| `test_app_regression.TestLiveModeBlocking` | 11 | ✅ |
| `test_app_regression.TestDuplicateQuestionFixtures` | 1 | ✅ |
| `test_app_regression.TestUnmatchedInput` | 3 | ✅ |

**test_state.py isolation note:** The fake Streamlit module stub is now
scoped — both `sys.modules["streamlit"]` and `sys.modules["ui.state"]` are
restored after the import, so AppTest-based tests in the same discovery
run get a fresh `ui.state` bound to real Streamlit.

---

## 6. AppTest regression coverage

The 20 new AppTest tests in `ui/tests/test_app_regression.py` verify:

**Defect 2 regressions (TestTypedQuestionPersistence):**
- Typed matched question → answer visible immediately after submit
- Answer count unchanged on plain rerun (no disappearance)
- Repeated reruns do not duplicate messages
- Fixture selection stores user + assistant messages in `display_messages`
- Navigation preserves conversation state
- New conversation clears messages, results, proposals, and selections

**Defect 1 regressions (TestLiveModeBlocking):**
- Live mode shows unavailable warning on find_plan page
- Live mode hides fixture selector
- Live mode hides text input form
- Switching to Live clears `active_result`
- Switching to Live clears `active_proposal` (proposal fixture test)
- Switching to Live clears `display_messages`
- Switching to Live deletes selector widget key
- Live guard fires on compare and impact pages (all non-overview pages)
- Overview page also shows unavailable in Live mode
- Switching back to Fixtures starts cleanly with empty conversation

**Other regressions:**
- Error and success fixtures with identical question text are independently
  selectable and have different fixture IDs (TestDuplicateQuestionFixtures)
- Unmatched input shows limitation message, not substituted result
  (TestUnmatchedInput × 3)

---

## 7. Acceptance criteria

| Criterion | Status |
|---|---|
| App starts with `python -m streamlit run app.py` | ✅ |
| Overview and saved responses work without `WX_API_KEY` | ✅ |
| All 23 fixture entries are selectable | ✅ |
| Successful and error responses with the same question are independently selectable | ✅ |
| Typed question answers persist across reruns | ✅ Fixed |
| Repeated reruns do not duplicate messages | ✅ Fixed |
| Live mode blocks all fixture controls and question forms | ✅ Fixed |
| Switching to Live clears conversation, results, proposals, selections | ✅ Fixed |
| Live mode shows clear unavailable explanation (no misleading AI credit warning) | ✅ Fixed |
| Overview in Live mode shows unavailable, not watsonx.ai credit warning | ✅ Fixed |
| Unmatched input is not silently replaced by the first fixture | ✅ |
| New conversation clears all conversation state and widget selections | ✅ Fixed |
| Navigation and New conversation do not trigger AI calls | ✅ |
| Backend test suite: no new failures | ✅ 291/291 pass |
| Browser verification | ⚠ Not performed — only AppTest verification used |

---

## 8. Files created or modified in this repair session

| File | Change |
|---|---|
| `app.py` | Rewrote fixture selection/rendering to use `display_messages`; added `_live_mode_guard()`, `_render_display_messages()`, `_add_fixture_to_conversation()`, `_add_typed_question_to_conversation()`; removed `_handle_fixture_selection()`; fixed Live mode guard on all pages and Overview; selector key deletion on mode switch and New conversation |
| `ui/state.py` | Fixed shared mutable default: `display_messages` now created as fresh list per session |
| `ui/tests/test_state.py` | Scoped fake Streamlit injection: restores both `sys.modules["streamlit"]` and `sys.modules["ui.state"]` after import |
| `ui/tests/test_app_regression.py` | New: 20 AppTest regression tests covering both defects |
| `docs/ui-runbook.md` | Updated: Python 3.11, `.venv311/`, `python -m pip`, Live mode unavailability, removed Python 3.9 claims |
| `docs/ui-validation.md` | This document (replaced) |
| `bob_sessions/hyunsoo/README.md` | Added Session 2 repair record |

**Protected files unchanged:**
- `engine/`, `agent/`, `data/`, `tests/expected/`, `reference/`
- `ui_fixtures/agent_results.json`

---

## 9. Known limitations and next steps

- **Browser verification** was not performed. All verification used
  Streamlit AppTest. Manual browser testing is recommended before
  merging to main.
- **Live AI integration** was not tested. No real `run_agent` calls were made.
- **Stage B:** Budget form, structured renderers (tables, KPI cards).
- **Stage C:** Proposal review, approval/rejection controls, decision log.
- **Stage D:** Live agent integration (requires `WX_API_KEY`).
- **Stage E:** Usability review, final validation.

---

## 10. Reproduction steps

```bash
cd /Users/hyunsoo/Downloads/IBM-Bibimbab-ui

# Backend tests
.venv311/bin/python -m unittest discover -s tests -v

# UI tests (unit + AppTest regression)
.venv311/bin/python -m unittest discover -s ui/tests -v

# Reference verification
.venv311/bin/python reference/verify.py

# App
.venv311/bin/python -m streamlit run app.py
# Open http://localhost:8501 in a browser
```
