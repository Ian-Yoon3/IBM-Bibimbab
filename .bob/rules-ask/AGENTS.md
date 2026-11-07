# Project Documentation Rules (Non-Obvious Only)

- `reference/` holds the canonical reference implementation and data dictionary — NOT the engine that agents should build in `engine/`
- `tests/expected/` is the ground truth for output format; `reference/verify.py --write` regenerates it from current simulation logic
- The README is written in Korean; the data dictionary field descriptions are in Korean — agent-generated code/comments should still be in English
- `validation/` mentioned in the README does NOT exist in the repo — the correct output directory is `tests/expected/`
- Scenario `NORMAL` has an empty `disruption_id` in `scenarios.csv` — querying `disruptions[scenario["disruption_id"]]` will KeyError on it; the script guards with `if scenario["disruption_id"]`
- `data_dictionary.md` is the authoritative schema reference — any new CSV field must be documented there
