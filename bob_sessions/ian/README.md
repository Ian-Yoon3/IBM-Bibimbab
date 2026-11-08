# IBM Bob usage record: Sunghyuk (Ian) Yoon

Scope: the AI agent layer on branch `feature/agent` (watsonx.ai connection, `agent/`, engine tool additions, evaluation harness).
The engine itself was built by Junseo Choi with his own Bob sessions.

## Sessions

| File | Started | Last activity | Prompts | Cost reported by Bob |
|---|---|---|---|---|
| [session_20261107_ababa723.md](session_20261107_ababa723.md) | 2026-11-07 18:17 | 2026-11-07 21:01 | 13 | 62.09 |

## Tool calls made by Bob

| Tool | Calls |
|---|---|
| `read_file` | 70 |
| `apply_diff` | 69 |
| `execute_command` | 58 |
| `update_todo_list` | 27 |
| `write_file` | 22 |
| `list_files` | 4 |
| `search_ibm_docs` | 1 |

## Lines written by Bob, per file

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

## What was not written in Bob

After Bob coins ran low, later changes (from eval run 4 onward: argument handling fixes, the table check, `get_order_detail`, fixed answer layouts in `agent/render.py`, the question sweep) were prepared as reviewed patches outside Bob, applied with `git apply`, and tested with the same 277-test suite. Those commits are visible in the git history of `feature/agent`.

