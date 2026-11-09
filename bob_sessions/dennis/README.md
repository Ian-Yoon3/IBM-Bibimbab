IBM Bob usage record: Junseo (Dennis) Choi
Scope: the calculation engine on branch `main` (`engine/`, `tests/`, `demo.py`, `README.md`, `AGENTS.md` and the `.bob/rules-*` files).
The agent layer on `feature/agent` was built by Sunghyuk (Ian) Yoon with his own Bob sessions.
Sessions
File	Started	Last activity	Prompts	Cost reported by Bob
session_20261107_3d75997f.md	2026-11-07 15:33	2026-11-07 16:03	5	15.12 (+0.23 explore sub-agent)
The five prompts, in order: `/init` (AGENTS.md and rule files), Plan mode design of the engine, implementation of loader / simulate / evaluate with scenario tests, implementation of candidates / analysis / compare / tools with their tests, and final adjustments (scenario_id keys, NORMAL as baseline, `demo.py`, `README.md`).
Tool calls made by Bob
Tool	Calls
`update_todo_list`	23
`write_file`	23
`read_file`	19
`execute_command`	14
`apply_diff`	11
`glob`	4
`list_files`	3
`use_skill`	1
`spawn_subagent`	1
Lines written by Bob, per file
Counted from the tool calls in the session log. `write_file` counts lines in files Bob wrote, `apply_diff` counts lines in Bob's replacement blocks. A file rewritten several times is counted each time.
File	Edits	Lines via write_file	Lines via apply_diff
`.bob/rules-agent/AGENTS.md`	2	11	4
`.bob/rules-ask/AGENTS.md`	1	8	0
`.bob/rules-plan/AGENTS.md`	1	10	0
`AGENTS.md`	3	59	29
`README.md`	1	92	0
`demo.py`	1	153	0
`engine-plan.md` (Plan mode output)	1	579	0
`engine/__init__.py`	1	1	0
`engine/analysis.py`	1	206	0
`engine/candidates.py`	1	96	0
`engine/compare.py`	2	91	82
`engine/evaluate.py`	1	51	0
`engine/loader.py`	1	445	0
`engine/simulate.py`	1	319	0
`engine/tools.py`	3	308	57
`tests/__init__.py`	1	1	0
`tests/probe_analysis.py` (temporary probe, deleted by Bob)	1	54	0
`tests/probe_compare.py` (temporary probe, deleted by Bob)	1	6	0
`tests/test_analysis.py`	1	134	0
`tests/test_candidates.py`	1	73	0
`tests/test_compare.py`	5	78	100
`tests/test_scenarios.py`	1	184	0
`tests/test_tools.py`	2	187	35
Total		3146	307
Result
76 unit tests pass (`python3 -m unittest discover -s tests -v`).
The engine reproduces all 5 validated scenarios in `tests/expected/` (scenario summary and all 60 order results).
`explore_purchase_qty` found two options outside the predefined scenarios: transfers + 40 units from S02 (11/12 on time, $1,216) and transfers + 65 units (12/12 on time, $1,666).
What was not written in Bob
Repository setup: cloning, copying the synthetic dataset into `data/`, `tests/expected/` and `reference/` (dataset by Jonghyun (John) Moon).
Running `demo.py` in the terminal, the git commit and the push to GitHub.
The prompts were prepared before each Bob turn and reviewed between turns; every code file listed above was written by Bob.
