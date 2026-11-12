# Project Documentation Rules (Non-Obvious Only)

- `reference/` holds the canonical reference implementation and data dictionary — NOT the engine that the agent calls; the live engine is in `engine/`
- `tests/expected/` is the ground truth for output format; `reference/verify.py --write` regenerates it from current simulation logic
- The README is written in Korean; the data dictionary field descriptions are in Korean — agent-generated code/comments should still be in English
- `validation/` mentioned in the README does NOT exist in the repo — the correct output directory is `tests/expected/`
- Scenario `NORMAL` has an empty `disruption_id` in `scenarios.csv` — querying `disruptions[scenario["disruption_id"]]` will KeyError on it; the script guards with `if scenario["disruption_id"]`
- `data_dictionary.md` is the authoritative schema reference — any new CSV field must be documented there
- **Agent scope:** the agent only covers disruption D01; do not document or imply support for other disruptions or for receipt dates outside the simulation window; dates inside the window are supported through worlds (ADR 0002, ADR 0003)
- **Secrets:** `.env` is gitignored — never document steps that involve committing or printing credentials
