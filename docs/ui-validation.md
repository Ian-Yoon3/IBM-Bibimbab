# UI Validation Report — Stage A

**Date:** 2026-11-17  
**Branch:** ui (local checkout, no git history — project delivered as folder)  
**Python:** 3.9.6 (system `/usr/bin/python3`), virtual environment `.venv/`  
**Streamlit:** installed via `.venv`

---

## 1. Environment inspection

| Item | Result |
|---|---|
| Working directory | `/Users/hyunsoo/Downloads/IBM-Bibimbab-ui` |
| OS | macOS 23.6.0 arm64 |
| Python | 3.9.6 |
| Virtual environment | `.venv/` created for this project |
| `app.py` exists | ✅ Created in Stage A |
| `ui/` directory exists | ✅ Created in Stage A |
| `.streamlit/` directory exists | ✅ Created in Stage A |
| `ui_fixtures/agent_results.json` | ✅ Unchanged (23 entries) |

---

## 2. Baseline test run (before UI work)

Command:
```
.venv/bin/python -m unittest discover -s tests -v
```

Result: **17 tests run, 1 FAIL, 7 ERRORS**

These failures are **pre-existing** and not introduced by Stage A:

| Failure | Cause |
|---|---|
| `test_demo_exits_cleanly` FAIL | `engine/simulate.py` uses `str \| None` syntax, unsupported on Python 3.9 |
| 7 import ERRORs | Same `str \| None` issue cascading through `engine/`, `agent/` imports |

The 5 tests that do not import the affected modules pass: `test_candidates` (5 tests).

---

## 3. UI test run

Command:
```
.venv/bin/python -m unittest discover -s ui/tests -v
```

Result: **34 tests, 0 failures, 0 errors — ALL PASS**

| Test class | Tests | Result |
|---|---|---|
| `TestLoadFixtures` | 4 | ✅ |
| `TestFixtureIds` | 3 | ✅ |
| `TestGetResultCopy` | 4 | ✅ |
| `TestIsErrorFixture` | 2 | ✅ |
| `TestLabelFor` | 3 | ✅ |
| `TestGetFixtureOptions` | 3 | ✅ |
| `TestUnmatchedMessage` | 1 | ✅ |
| `TestInitState` | 4 | ✅ |
| `TestResetConversation` | 3 | ✅ |
| `TestSwitchMode` | 5 | ✅ |
| `TestNavigateTo` | 2 | ✅ |

---

## 4. Acceptance criteria

| Criterion | Status |
|---|---|
| App starts with `python -m streamlit run app.py` | ✅ |
| Overview and saved responses work without `WX_API_KEY` | ✅ |
| All 23 fixture entries are selectable | ✅ |
| Successful and error responses with the same question are independently selectable | ✅ |
| Unmatched input is not silently replaced by the first fixture | ✅ (returns `None`; limitation message shown) |
| An error result is not presented with stale metrics or approval controls | ✅ (Stage A renders only `answer`; no metric cards) |
| Navigation and New conversation do not trigger AI calls | ✅ |
| Existing test suite: no new failures introduced | ✅ (pre-existing failures unchanged) |
| Browser verification | ⚠ Not performed in this automated check — manual verification required |

---

## 5. Files created or modified

| File | Purpose |
|---|---|
| `app.py` | Application entry point, navigation, page routing |
| `ui/__init__.py` | Python package marker |
| `ui/fixtures.py` | Fixture loading, unique ID generation, selection logic |
| `ui/state.py` | Session-state initialisation and reset |
| `ui/renderers.py` | Answer rendering (Stage A: `st.chat_message` + `st.markdown`) |
| `ui/tests/__init__.py` | Test package marker |
| `ui/tests/test_fixtures.py` | 21 tests for fixture loading and selection |
| `ui/tests/test_state.py` | 13 tests for session state management |
| `.streamlit/config.toml` | Light theme, usage stats off |
| `requirements.txt` | Added `streamlit` |
| `docs/ui-runbook.md` | Setup and run instructions |
| `docs/ui-validation.md` | This document |

**Protected files unchanged:**
- `engine/`, `agent/`, `data/`, `tests/expected/`, `reference/`
- `ui_fixtures/agent_results.json`

---

## 6. Known limitations and next steps

- **Stage B:** Budget form, structured renderers (tables, KPI cards), exact
  fixture-settings matching.
- **Stage C:** Proposal review, approval/rejection controls, decision log.
- **Stage D:** Live agent integration (requires `WX_API_KEY`).
- **Stage E:** Usability review, final validation.

Pre-existing backend issue (not in UI scope): `engine/simulate.py` uses
`str | None` union-type syntax that fails on Python 3.9. This needs a
fix from Ian (use `Optional[str]` from `typing`) to run the full backend
test suite on this Python version.

---

## 7. Reproduction steps

```bash
cd /Users/hyunsoo/Downloads/IBM-Bibimbab-ui
source .venv/bin/activate
python -m streamlit run app.py
# Open http://localhost:8501 in a browser
```

UI test command:
```bash
.venv/bin/python -m unittest discover -s ui/tests -v
```
