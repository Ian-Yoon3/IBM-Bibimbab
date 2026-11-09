# Team AI prompt

Paste the block below into your AI tool before you start any work on this repo.
The AI will answer with a three-line summary of the rules. Check that summary before you continue.

UI owner: paste this first, then `docs/ui-handoff-prompt.md`.

```text
Before we start, read and follow these project rules for the rest of this conversation.

PROJECT
- Team project "Supply Chain Recovery Decision Agent" for the IBM SkillsBuild AI
  Experiential Learning Lab. Repo: github.com/Ian-Yoon3/IBM-Bibimbab (public).
- A deterministic Python engine (engine/) computes every number. A watsonx.ai LLM
  agent (agent/) chooses engine tools and explains results. A human approves actions
  in the UI. The agent never approves anything.
- Owner of engine/ and agent/ and reviewer of every merge: Ian (GitHub Ian-Yoon3).

READ FIRST
- AGENTS.md, CONTRIBUTING.md, and for UI work docs/ui-contract.md.
- If you cannot open the repo yourself, ask me to paste these files. Do not guess
  their contents.

BRANCHES
- main is protected. Never commit or push to main. Changes reach main only through a
  pull request that Ian reviews and merges.
- UI work happens on the branch `ui`. Any other work happens on a new branch
  `feature/<short-topic>` created from main.
- At the start of each session:
    git checkout <my branch>
    git pull
    git merge origin/main
- When a piece of work is finished, open a pull request into main and add Ian-Yoon3
  as reviewer. Pushing more commits to the same branch updates the open pull request.

DO NOT TOUCH WITHOUT ASKING IAN
- engine/, agent/, data/, tests/expected/, reference/.
- If my task seems to need a change there, stop and tell me what change and why.

NUMBERS
- Never compute, estimate, round differently or invent a number in code, docs or UI.
  Every number must come from an engine result or a saved result file.

TESTS
- Before every push: python -m unittest discover -s tests
- All tests must pass. Tests need no API key and make no network calls.

API KEYS
- The repo is public. Never put an API key in code, a commit, a log, a screenshot or
  a prompt, on any branch. .env is gitignored and stays on the key holder's laptop.
- Without a key, use ui_fixtures/agent_results.json instead of calling the agent.
- The LLM model is meta-llama/llama-3-3-70b-instruct. Do not switch to Granite.

IBM BOB AND AUTHORSHIP
- The project requires IBM Bob as the development tool. Code that goes into the repo
  should be written in IBM Bob, and each Bob task is exported to
  bob_sessions/<my name>/. Other AI tools may be used for questions and explanations.
- Commits are authored by me. Do not add AI co-author lines or AI attribution to
  commit messages, pull requests or files.

HOW TO WORK WITH ME
- I am not an experienced developer. Give exact commands for Windows PowerShell and
  explain briefly why each step is needed.
- Work in small steps. After each step, tell me how to check that it worked.
- If something is unclear or risky, ask me before doing it.

Confirm you understand these rules in three lines, then ask what I am working on.
```
