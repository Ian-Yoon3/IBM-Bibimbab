# IBM Bob usage record: Sunghyuk (Ian) Yoon

Scope: the AI agent layer on branch `feature/agent` (watsonx.ai connection, `agent/`, engine tool additions, evaluation harness), and stage 1 of the uncertainty extension on branch `feature/extension-trial-ian` (worlds, loader, `engine/worlds.py`, `get_world_risk`, `world_risk` answers).
The engine itself was built by Junseo (Dennis) Choi with his own Bob sessions, recorded in [../dennis](../dennis/README.md).

## Sessions

| File | Started | Last activity | Prompts | Cost reported by Bob | Scope |
|---|---|---|---|---|---|
| [session_20261107_ababa723.md](session_20261107_ababa723.md) | 2026-11-07 18:17 | 2026-11-07 21:01 | 13 | 62.09 | Agent layer |
| [session_20261111_a4210a4e.md](session_20261111_a4210a4e.md) | 2026-11-11 16:51 | 2026-11-12 02:06 | 15 | 82.67 | Stage 1 extension |

Each session file starts with a prompt index. Prompts are shown in full, Bob's replies and tool calls follow each prompt.

## Session `ababa723`: agent layer

### Commits made during the session

Commits `dc36ec8` to `e13f855` on `feature/agent` (2026-11-07, 18:41 to 21:02) were made during this session.
`b873bf2` adds the ADR 0001 document, which was written outside Bob. Bob's attribution log has no entry under `docs/decisions/`.
Two commits in that window carry the ADR title by mistake. `829c6ae` holds eval run 3 results (`eval_results/20261107_204509.json`). `5fb8012` holds the Bob fixes from Prompt 12 (tool-offer guard, no placeholders in prompts, explored-option labels, grounding check).

### Tool calls made by Bob

| Tool | Calls |
|---|---|
| `read_file` | 70 |
| `apply_diff` | 69 |
| `execute_command` | 58 |
| `update_todo_list` | 27 |
| `write_file` | 22 |
| `list_files` | 4 |
| `search_ibm_docs` | 1 |

### Lines written by Bob, per file

From Bob's attribution log. `write_file` counts lines in files Bob wrote, `apply_diff` counts lines Bob changed. A file rewritten several times is counted each time.

| File | Edits | Lines via write_file | Lines via apply_diff |
|---|---|---|---|
| `.bob/rules-agent/AGENTS.md` | 5 | 16 | 15 |
| `.bob/rules-ask/AGENTS.md` | 1 | 10 | 0 |
| `.bob/rules-plan/AGENTS.md` | 1 | 13 | 0 |
| `.env.example` | 2 | 3 | 1 |
| `AGENTS.md` | 5 | 94 | 13 |
| `agent/fake_llm.py` | 1 | 72 | 0 |
| `agent/llm.py` | 15 | 130 | 59 |
| `agent/loop.py` | 34 | 235 | 10 |
| `agent/prompts.py` | 27 | 163 | 42 |
| `agent/tool_specs.py` | 28 | 556 | 35 |
| `engine/analysis.py` | 2 | 0 | 2 |
| `engine/compare.py` | 7 | 0 | 37 |
| `engine/tools.py` | 12 | 0 | 88 |
| `requirements.txt` | 1 | 2 | 0 |
| `scripts/chat.py` | 5 | 74 | 19 |
| `scripts/check_wx.py` | 2 | 116 | 1 |
| `scripts/eval_agent.py` | 86 | 313 | 218 |
| `tests/test_agent.py` | 44 | 456 | 674 |
| `tests/test_tools.py` | 14 | 0 | 128 |

### What was not written in Bob

After Bob coins ran low, later changes (from eval run 4 onward: argument handling fixes, the table check, `get_order_detail`, fixed answer layouts in `agent/render.py`, the question sweep) were prepared as reviewed patches outside Bob, applied with `git apply`, and tested with the same 277-test suite. Those are the commits from `81674d9` onward (2026-11-07 21:10 and later), now part of `main`.

## Session `a4210a4e`: stage 1 extension

One Bob task on `feature/extension-trial-ian`, 15 prompts, each a small step with stated checks. Each step was reviewed and tested before it was committed. Plan and decisions: `docs/extension-plan.md`, `docs/decisions/0002-receipt-date-weights.md`, `docs/decisions/0003-uncertain-date-in-agent-answers.md`.

### Commits made during the session

| Commit | Content from Bob |
|---|---|
| `fbacd91` | `scripts/stage1_triangular_worlds.py`, its tests, and the two world files written by running that script. ADR 0002 in the same commit was written outside Bob |
| `1385d45` | World files in `engine/loader.py` (prompts 2 and 3) |
| `5db7fd1` | `engine/worlds.py` and its tests (prompt 4) |
| `b03fc88` | `get_world_risk` in `engine/tools.py` (prompt 5) |
| `f2ac79e` | Reading questions as receipt dates (prompts 6 and 7) |
| `5e8802b` | `world_risk` view, overview, explanation check (prompts 8 and 9) |
| `b68dae8` | Wiring and the deliberate behaviour changes of ADR 0003 (prompts 10 to 15) |

`f63a9ac`, `35456ec`, `efe6d72` and `e6c3317` change documents only and were written outside Bob.
`b68dae8` also holds documents written outside Bob (`AGENTS.md`, `.bob/` rules, `docs/ui-contract.md`, `docs/ui-handoff-prompt.md`, ADR 0003), two question sweeps and `ui_fixtures/agent_results.json` produced by running the scripts with the real model, and the `DEFAULT_SWEEP` path in `scripts/make_ui_fixtures.py`, changed with one command outside Bob.

### Tool calls made by Bob

| Tool | Calls |
|---|---|
| `execute_command` | 119 |
| `read_file` | 96 |
| `apply_diff` | 41 |
| `update_todo_list` | 28 |
| `grep` | 21 |
| `write_file` | 10 |
| `search_and_replace` | 5 |
| `list_files` | 4 |
| `insert_content` | 3 |
| `glob` | 2 |
| `FindSymbol` | 2 |

### Lines written by Bob, per file

From Bob's attribution log for the time of this session. `write_file` counts lines in files Bob wrote, `apply_diff` counts lines Bob changed, the last column counts lines added with `insert_content` or `search_and_replace`. A file rewritten several times is counted each time.

| File | Edits | Lines via write_file | Lines via apply_diff | Lines via insert or replace |
|---|---|---|---|---|
| `agent/loop.py` | 5 | 0 | 26 | 0 |
| `agent/overview.py` | 1 | 25 | 0 | 0 |
| `agent/prompts.py` | 10 | 0 | 41 | 68 |
| `agent/render.py` | 48 | 0 | 145 | 647 |
| `engine/loader.py` | 9 | 0 | 153 | 1 |
| `engine/tools.py` | 4 | 0 | 61 | 0 |
| `engine/worlds.py` | 1 | 290 | 0 | 0 |
| `scripts/eval_agent.py` | 5 | 0 | 16 | 0 |
| `scripts/make_ui_fixtures.py` | 6 | 0 | 14 | 0 |
| `scripts/question_sweep.py` | 9 | 0 | 45 | 0 |
| `scripts/stage1_triangular_worlds.py` | 26 | 239 | 0 | 1 |
| `tests/test_agent.py` | 10 | 0 | 34 | 0 |
| `tests/test_date_reading.py` | 10 | 286 | 71 | 0 |
| `tests/test_loader_worlds.py` | 2 | 368 | 54 | 0 |
| `tests/test_stage1_triangular_worlds.py` | 1 | 189 | 0 | 0 |
| `tests/test_tools_world_risk.py` | 1 | 112 | 0 | 0 |
| `tests/test_ui_fixtures.py` | 1 | 0 | 1 | 0 |
| `tests/test_world_risk_view.py` | 13 | 291 | 256 | 1 |
| `tests/test_worlds.py` | 2 | 487 | 0 | 1 |

### What was not written in Bob

- Documents: `docs/extension-plan.md`, ADR 0002, ADR 0003, `reference/data_dictionary.md` (world files), `docs/ui-contract.md`, `docs/ui-handoff-prompt.md`, `AGENTS.md` and `.bob/` rule updates, `README.md`, `.gitignore`.
- Results of running the code: the question sweeps and the golden evaluation in `eval_results/`, and `ui_fixtures/agent_results.json`.
- Every change was checked against the stated expected numbers and the full test suite before commit. Bob's own test runs left output files in the repository root a few times. They were deleted and not committed.
