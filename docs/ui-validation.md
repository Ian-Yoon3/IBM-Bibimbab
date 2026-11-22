# UI Validation Report — Stage A (Repaired, Session 3)

**Date:** 2026-11-22  
**Branch:** ui (commit 495b7f5 + local Stage A repairs, Session 3)  
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

## 2. Historical context

### Session 1 — Stage A Implementation (Python 3.9.6, `.venv/`)
A previous session used Python 3.9.6. On that version, 7 import errors and 1 test failure
occurred due to `str | None` union-type syntax in `engine/simulate.py`. Those are pre-existing
and not introduced by UI work. **This session uses Python 3.11.18.** All 291 backend tests pass.

### Session 2 — Stage A Repair (Commit 495b7f5 base)
Two defects were fixed: Live mode did not block fixture interactions, and typed question answers
disappeared on rerun. 54 UI tests passed after those fixes.

---

## 3. Backend test run

Command:
```
.venv311/bin/python -m unittest discover -s tests -v
```

Result: **291 tests, 0 failures, 0 errors — ALL PASS**

---

## 4. Reproduced Stage A regressions (Session 3)

The following three regressions were identified against commit 495b7f5 and fixed in this session.

### Regression A — First fixture selection did not display its answer

**Symptom:**
1. Start a fresh session in Fixtures mode.
2. Navigate to "Find a recovery plan".
3. Select the first saved example once.
4. Inspect the rendered page.

Observed: two messages stored in `display_messages`, but the answer was not rendered.
An additional ordinary rerun made it visible.

**Root cause:**
`_fixture_selector()` called `_render_display_messages()` *before* `_add_fixture_to_conversation()`.
The `pass` statement at the end that was supposed to `st.rerun()` never triggered a rerun.

**Fix:**
- In `_fixture_selector()`, call `_add_fixture_to_conversation()` first.
- After adding new messages, call `st.rerun()` immediately so the new messages are rendered on
  the very next pass.
- Only rerun when the selection is new (guarded by the `last_handled_selector_*` check), to
  avoid unconditional rerun loops.

---

### Regression B — Previous selector value overrode a new typed question

**Symptom:**
1. Select the saved $500 example.
2. Submit "We can spend up to $800. Which option?" through the text form.
3. Perform an ordinary rerun.

Observed: the $800 answer appeared, then the $500 fixture was automatically appended again;
`active_result` reverted to $500; the conversation became A → B → A without the user selecting A again.

**Root cause:**
The selector widget was processed on every render. The idempotency check only looked at the
*last message's* `fixture_id`, which was now `conv2_t1_i1` ($800). Since `conv1_t1_i0` ($500)
differed from that last ID, `_add_fixture_to_conversation()` appended it again.

**Fix:**
- Added `last_handled_selector_{page_hint}` as a session state key.
- `_fixture_selector()` only calls `_add_fixture_to_conversation()` when `chosen_id` differs
  from `last_handled_selector_{page_hint}`.
- After processing, sets `last_handled_selector_{page_hint} = chosen_id`.
- `reset_conversation()` in `ui/state.py` clears all `last_handled_selector_*` keys so that
  "New conversation" and mode switches start cleanly.

**Preserved behaviour:**
- Explicit A → B → A selector sequence still adds three entries to the conversation.
- After submitting typed question B while selector shows A, ordinary reruns do not replay A.

---

### Regression C — Repeated error examples crashed with duplicate button IDs

**Symptom:**
1. Select the error fixture.
2. Select a normal fixture.
3. Select the error fixture again.
4. Render the accumulated conversation.

Observed: Streamlit raised a duplicate element ID error — multiple historical error messages
each called `st.button("Try again")` without a unique key.

**Root cause:**
`render_error_retry_banner()` in `ui/renderers.py` created `st.button("Try again")` without
a `key=` argument. When multiple error messages were in `display_messages`, each rendered its
own unkeyed button, and Streamlit detected the collision.

**Fix:**
- Added a `msg_key: str = "0"` keyword argument to `render_error_retry_banner()`.
- Changed `st.button("Try again", ...)` to `st.button("Try again", key=f"retry_{msg_key}", ...)`.
- In `_render_display_messages()`, enumerate messages and pass `msg_key=str(idx)` to the
  renderer, giving each retry banner a stable unique identity per message position.

---

## 5. UI test run

Command:
```
.venv311/bin/python -m unittest discover -s ui/tests -v
```

Result: **71 tests, 0 failures, 0 errors — ALL PASS**

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
| `test_app_regression.TestLiveModeBlocking` | **10** | ✅ |
| `test_app_regression.TestDuplicateQuestionFixtures` | 1 | ✅ |
| `test_app_regression.TestUnmatchedInput` | 3 | ✅ |
| `test_app_regression.TestRegressionA_FirstSelectionDisplaysAnswer` | 1 | ✅ |
| `test_app_regression.TestRegressionB_SelectorDoesNotOverrideTypedQuestion` | 4 | ✅ |
| `test_app_regression.TestRegressionC_RepeatedErrorFixturesNoCrash` | 3 | ✅ |
| `test_app_regression.TestRegressionG_UnmatchedInputAfterResult` | 1 | ✅ |
| `test_app_regression.TestRegressionH_NewConversationClearsTracking` | 2 | ✅ |
| `test_app_regression.TestRegressionI_LiveModeBlockedAllPages` | 3 | ✅ |
| `test_app_regression.TestRegressionJ_ReturnFromLiveToFixtures` | 1 | ✅ |
| `test_app_regression.TestRegressionK_SeparateSessionsDoNotShareState` | 2 | ✅ |

**Note on `TestLiveModeBlocking`:** This class contains **10** tests, not 11 as stated in the
Session 2 report. The count has been corrected here.

**AppTest total:** 37 tests (20 from Session 2 + 17 new in Session 3).  
**Unit test total:** 34 tests (unchanged from Session 2).  
**Grand total:** 71 tests.

---

## 6. AppTest regression coverage (Session 3 additions)

**Regression A (TestRegressionA_FirstSelectionDisplaysAnswer):**
- All 23 fixtures display their answer immediately after one selection (subtests by index).
  Checks actual rendered markdown text, not just `display_messages` count.

**Regression B (TestRegressionB_SelectorDoesNotOverrideTypedQuestion):**
- Selecting $500 then submitting typed $800 question leaves $800 as the current result
  through ordinary reruns.
- Consecutive different fixture selections show the newest answer.
- Explicit A → B → A selector sequence correctly adds 3 conversation entries.
- Ordinary rerun does not add messages after selection.

**Regression C (TestRegressionC_RepeatedErrorFixturesNoCrash):**
- Error → success → error accumulates 6 messages without exception.
- Error fixture shows a warning banner, not an unhandled exception.
- Accumulated error messages each have a unique retry button key; no duplicate-ID crash.

**Case G (TestRegressionG_UnmatchedInputAfterResult):**
- After a fixture selection, an unmatched typed question shows the limitation message
  and records an "unmatched" message, not a reuse of the previous result.

**Case H (TestRegressionH_NewConversationClearsTracking):**
- New conversation deletes `last_handled_selector_*` keys.
- After New conversation, re-selecting the same fixture works correctly.

**Case I (TestRegressionI_LiveModeBlockedAllPages):**
- Live mode blocks fixture controls on find_plan, compare, and impact pages.

**Case J (TestRegressionJ_ReturnFromLiveToFixtures):**
- Fixtures → Live → Fixtures gives an empty conversation and clears `last_handled_selector_*`.

**Case K (TestRegressionK_SeparateSessionsDoNotShareState):**
- Two AppTest instances start with independent empty conversation state.
- Mutating one session's `display_messages` does not affect the other.

---

## 7. Acceptance criteria

| Criterion | Status |
|---|---|
| App starts with `python -m streamlit run app.py` | ✅ |
| Overview and saved responses work without `WX_API_KEY` | ✅ |
| All 23 fixture entries are selectable | ✅ |
| First fixture selection displays answer immediately (no extra rerun) | ✅ Fixed (Regression A) |
| Successful and error responses with the same question are independently selectable | ✅ |
| Typed question answers persist across reruns | ✅ |
| Repeated reruns do not duplicate messages | ✅ |
| Selector value does not override a new typed question on rerun | ✅ Fixed (Regression B) |
| Explicit A → B → A selector sequence is preserved | ✅ |
| Repeated error fixtures do not crash with duplicate button IDs | ✅ Fixed (Regression C) |
| Retry button is unique per error message | ✅ |
| Live mode blocks all fixture controls and question forms | ✅ |
| Switching to Live clears conversation, results, proposals, selections | ✅ |
| Overview in Live mode shows unavailable, not watsonx.ai credit warning | ✅ |
| Unmatched input is not silently replaced by the previous fixture result | ✅ |
| New conversation clears all conversation state and selection-tracking keys | ✅ |
| Navigation and New conversation do not trigger AI calls | ✅ |
| Backend test suite: no new failures | ✅ 291/291 pass |
| Reference verification | ✅ PASS |
| Browser verification | ⚠ Not performed — only AppTest verification used |

---

## 8. Files created or modified in this repair session (Session 3)

| File | Change |
|---|---|
| `app.py` | Fixed `_fixture_selector()`: process selection before rendering, call `st.rerun()` on new selection; added `last_handled_selector_{page_hint}` tracking for Regression B; fixed `_render_display_messages()` to pass `msg_key=str(idx)` to retry banner |
| `ui/renderers.py` | Added `msg_key` keyword argument to `render_error_retry_banner()` and passes it as `key=f"retry_{msg_key}"` to `st.button()` |
| `ui/state.py` | `reset_conversation()` now clears `last_handled_selector_*` keys |
| `ui/tests/test_app_regression.py` | Added 17 new AppTest tests (Cases A–K) covering all three regressions and broader behaviour |
| `docs/ui-validation.md` | This document (replaced) |
| `bob_sessions/hyunsoo/README.md` | Added Session 3 repair record |

**Protected files unchanged:**
- `engine/`, `agent/`, `data/`, `tests/expected/`, `reference/`
- `ui_fixtures/agent_results.json`

---

## 9. Known limitations and next steps

- **Browser verification** was not performed. All verification used Streamlit AppTest.
  Manual browser testing is recommended before merging to main.
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
