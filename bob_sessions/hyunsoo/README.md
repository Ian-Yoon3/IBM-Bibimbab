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
