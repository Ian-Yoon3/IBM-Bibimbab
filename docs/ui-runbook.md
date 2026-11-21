# UI Runbook — Supply Chain Recovery Decision Agent

This document explains how to set up and run the Streamlit application on a local machine.

---

## Prerequisites

- macOS (arm64) or any POSIX system
- Python 3.9 or later (the system Python at `/usr/bin/python3` works)
- Git checkout of the `ui` branch

The application does **not** require a watsonx.ai API key to run in
Fixtures (demo) mode.

---

## First-time setup

```bash
# 1. Enter the project directory
cd /Users/hyunsoo/Downloads/IBM-Bibimbab-ui   # adjust path as needed

# 2. Create a virtual environment
python3 -m venv .venv

# 3. Activate it
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

The virtual environment `.venv/` is excluded from version control (see
`.gitignore`). Repeat steps 2–4 on a fresh checkout.

---

## Running the application

```bash
# From the project root with the virtual environment active:
source .venv/bin/activate   # skip if already active
python -m streamlit run app.py
```

Streamlit will print a local URL (e.g. `http://localhost:8501`). Open it
in a browser.

---

## Running without activating the virtual environment

```bash
.venv/bin/python -m streamlit run app.py
```

---

## Running the test suites

### Existing backend tests (Python 3.9 known issue)

```bash
.venv/bin/python -m unittest discover -s tests -v
```

**Note:** On Python 3.9 there are 7 pre-existing import errors and 1 test
failure caused by `str | None` union-type syntax in `engine/simulate.py`.
These failures exist on the `ui` branch before any UI work and are not
introduced by this implementation. The 5 candidate tests that do not
import engine code pass.

### New UI tests

```bash
.venv/bin/python -m unittest discover -s ui/tests -v
```

All 34 UI tests pass on Python 3.9.

---

## Fixtures mode (default, no API key required)

The application starts in **Fixtures** mode. All 23 saved examples from
`ui_fixtures/agent_results.json` are available through the example
selector drop-down on each page.

The original fixture file is **never modified** by the running application.

---

## Live agent mode (requires API key — Stage D)

Live mode is visible in the mode selector but intentionally unavailable in
Stage A. Submitting a live request requires:

```
WX_API_KEY      (your IBM Cloud API key)
WX_PROJECT_ID   (the watsonx.ai project ID)
WX_URL          (e.g. https://us-south.ml.cloud.ibm.com)
WX_MODEL_ID     (e.g. meta-llama/llama-3-3-70b-instruct)
```

Copy `.env.example` to `.env` and fill in those values. The application
reads them at startup via `python-dotenv`.

**Never commit `.env` or paste a key into this file.**

---

## Deployment (Streamlit Community Cloud)

This is covered in `CONTRIBUTING.md`. The UI owner pushes the `ui` branch,
Ian reviews and merges into `main`, and the app is deployed from `main`.

Secrets are entered in the app's hosting settings, not in the repository.

---

## Known limitations (Stage A)

- Structured result cards (tables, KPI metrics) are not yet rendered.
  Stage B will add them.
- Proposal approval/rejection controls are not yet wired. Stage C will
  add them.
- Live agent mode is blocked until Stage D.
- Decision log screen is marked *upcoming*.
- File-based decision records are lost when the hosted app restarts.
- The backend (`engine/`) uses `str | None` type hints that are not
  supported on Python 3.9; use Python 3.10+ or the system interpreter if
  the backend tests are needed.
