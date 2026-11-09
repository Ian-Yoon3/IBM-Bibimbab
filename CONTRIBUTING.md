# Working on this repo

Rules for the four of us. `README.md` is for judges and outside readers. This file is for the team.

## Who changes what

| Area | Folder | Owner | Others |
|---|---|---|---|
| Engine | `engine/`, `data/`, `tests/expected/` | Ian (built by Junseo) | Ask before changing |
| Agent | `agent/`, `scripts/` | Ian | Ask before changing |
| UI | `app.py`, `ui/` (if needed), `.streamlit/` | UI owner (TBD) | Free to change on the `ui` branch |
| Team docs | `CONTRIBUTING.md`, `docs/` | Anyone | Keep `docs/ui-contract.md` in sync with the agent |
| Bob records | `bob_sessions/<your name>/` | Each member | Only your own folder |

If the UI needs something from the engine or the agent, open an issue or ask Ian. Do not patch `engine/` or `agent/` from the `ui` branch. The tests guard those folders, and a quiet fix there can break the demo numbers.

## Branches

```
main   always green, Ian merges into it
ui     UI owner pushes here directly
feature/<topic>   Ian's agent and engine work, merged into main when green
```

1. `ui` is created from `main`. Before starting a work session on `ui`, bring in the latest `main`.
   ```bash
   git checkout ui
   git pull
   git merge origin/main
   ```
2. Push to `ui` as often as you like.
3. When the UI is ready, Ian merges `ui` into `main`.

Nobody pushes to `main` except through a merge that Ian checks.

## Before every push

```bash
python -m unittest discover -s tests
```

Every test must pass. The tests need no API key and make no network calls.

## What needs an API key

| Task | Key needed |
|---|---|
| Tests, `python demo.py`, `python reference/verify.py` | No |
| UI work with `ui_fixtures/agent_results.json` | No |
| `python -m scripts.chat`, `scripts.eval_agent`, `scripts.question_sweep` | Yes |
| Running the UI against the real agent | Yes |

Build the UI with the fixtures first. `docs/ui-contract.md` shows how. Test against the real agent only when a screen is finished, because every call uses watsonx.ai credits.

## Keys and secrets

- The key lives only in `.env` on the key holder's laptop and in the hosting service's secret settings.
- `.env` is gitignored. Never commit it. Never paste a key into Slack, an issue or a Bob prompt.
- This repository is public. A key pushed to any branch is exposed at once, even if the commit is deleted later. If that happens, tell Ian so the key can be revoked.
- Use `meta-llama/llama-3-3-70b-instruct` as `WX_MODEL_ID`. Granite was rejected for writing numbers no tool returned. See `docs/decisions/0001-default-llm-model.md`.

## Access to watsonx.ai for teammates

Pending. The team invitations to the IBM Cloud account expired, and the account owner has been asked to send them again.

- If the invitations come back, each member creates their own API key in IBM Cloud and uses the same `WX_PROJECT_ID`.
- Until then, only Ian can run the real agent. Everyone else works with the fixtures.

This section will be updated when IBM answers.

## When the agent output changes

The UI depends on the shape of `run_agent()` results. If a change in `agent/` alters a view:

1. Update `docs/ui-contract.md`.
2. Run `python -m scripts.make_ui_fixtures` and commit `ui_fixtures/agent_results.json`.
3. Tell the UI owner what changed.

`tests/test_ui_fixtures.py` fails when the replay no longer matches the saved real run, so the change cannot go unnoticed.

## Deployment (final demo)

The plan is Streamlit Community Cloud, deployed from `main` once the UI is merged.

- The key holder enters the secrets in the app settings, never in the repo.
  ```toml
  WX_API_KEY = "..."
  WX_PROJECT_ID = "..."
  WX_URL = "https://us-south.ml.cloud.ibm.com"
  WX_MODEL_ID = "meta-llama/llama-3-3-70b-instruct"
  ```
- `app.py` copies these values into `os.environ` at startup, because `agent/llm.py` reads environment variables.
- An app from a public repo is public by default. Anyone with the link can use our credits. Restrict viewers in the app's sharing settings during development.
- The decision log on the hosted app is lost when the app restarts. That is acceptable for the demo.

## IBM Bob records

Each member saves their own Bob task exports and screenshots in `bob_sessions/<your name>/`, with a short `README.md` listing what each session built. The submission requires them.
