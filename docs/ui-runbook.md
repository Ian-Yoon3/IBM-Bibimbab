# UI Runbook — Supply Chain Recovery Decision Agent

This document explains how to set up and run the Streamlit application on a local machine.

---

## Prerequisites

- macOS (arm64) or any POSIX system
- **Python 3.11 or newer** (required for the full project, including backend engine)
- Git checkout of the `ui` branch

The application does **not** require a watsonx.ai API key to run in
Fixtures (demo) mode.

> **Virtual environments and secrets** must remain outside commits.
> Neither `.venv311/` nor `.env` is tracked in version control.

---

## First-time setup

```bash
# 1. Enter the project directory
cd /Users/hyunsoo/Downloads/IBM-Bibimbab-ui   # adjust path as needed

# 2. Create a virtual environment (Python 3.11 or newer)
python3.11 -m venv .venv311

# 3. Activate it
source .venv311/bin/activate

# 4. Install dependencies
python -m pip install -r requirements.txt
```

The project uses `.venv311/` as the canonical environment name.

---

## Running the application

```bash
# From the project root with the virtual environment active:
source .venv311/bin/activate   # skip if already active
python -m streamlit run app.py
```

Streamlit will print a local URL (e.g. `http://localhost:8501`). Open it
in a browser.

---

## Running without activating the virtual environment

```bash
.venv311/bin/python -m streamlit run app.py
```

---

## Running the test suites

### Backend tests

```bash
.venv311/bin/python -m unittest discover -s tests -v
```

Result: **291 tests, 0 failures, 0 errors** on Python 3.11.

### UI unit and regression tests

```bash
.venv311/bin/python -m unittest discover -s ui/tests -v
```

Result: **54 tests, 0 failures, 0 errors** (34 unit tests + 20 AppTest
regression tests).

Both test suites may be run together in a single discovery:

```bash
.venv311/bin/python -m unittest discover -s tests -v && \
.venv311/bin/python -m unittest discover -s ui/tests -v
```

---

## Fixtures mode (default, no API key required)

The application starts in **Fixtures** mode. All 23 saved examples from
`ui_fixtures/agent_results.json` are available through the example
selector drop-down on each page.

The original fixture file is **never modified** by the running application.

---

## Live agent mode — unavailable in Stage A

**Live mode is unavailable throughout Stage A, even when a `WX_API_KEY`
is present in the environment or in `.env`.**

Selecting "Live agent" in the mode selector will display an explanation
and block all fixture controls and question forms.  No AI service calls
are made.

Live mode will be enabled in Stage D once the API connection has been
validated.

---

## Configuration for future live mode (Stage D)

When live mode is enabled, the following environment variables are
required:

```
WX_API_KEY      (your IBM Cloud API key)
WX_PROJECT_ID   (the watsonx.ai project ID)
WX_URL          (e.g. https://us-south.ml.cloud.ibm.com)
WX_MODEL_ID     (e.g. meta-llama/llama-3-3-70b-instruct)
```

Copy `.env.example` to `.env` and fill in those values. The application
reads them at startup via `python-dotenv`.

**Never commit `.env` or paste a key into this file or any source file.**
The `.env` file and `.venv311/` directory must remain outside commits.

---

## Deployment (Streamlit Community Cloud)

This is covered in `CONTRIBUTING.md`. The UI owner pushes the `ui` branch,
Ian reviews and merges into `main`, and the app is deployed from `main`.

Secrets are entered in the app's hosting settings, not in the repository.

---

## Known limitations (Stage A)

- **Live mode is blocked.** Even with an API key, live calls are not made.
  Stage D will enable live integration.
- Structured result cards (tables, KPI metrics) are not yet rendered.
  Stage B will add them.
- Proposal approval/rejection controls are not yet wired. Stage C will
  add them.
- Decision log screen is marked *upcoming*.
- File-based decision records are lost when the hosted app restarts.
