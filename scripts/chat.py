"""scripts/chat.py — terminal REPL for manual testing of the NovaTech agent.

Usage:
    python scripts/chat.py
    python scripts/chat.py <model_id>

Prints the model ID at startup, shows each tool call with its args as it
happens, and prints the final answer. History accumulates across turns.
Type 'quit' or 'exit' to end the session.
"""

import json
import sys
import warnings

from dotenv import load_dotenv


def _print_tool_call(entry: dict) -> None:
    args_str = json.dumps(entry["args"], ensure_ascii=False)
    print(f"  → [{entry['name']}] {args_str}")
    if "error" in entry["result"]:
        print(f"    ✗ error: {entry['result']['error']}")


def main() -> None:
    load_dotenv()
    # Suppress only the "Non-IBM Product" disclaimer inside WatsonxAPIWarning.
    # All other watsonx warnings remain visible.
    try:
        from ibm_watsonx_ai.foundation_models.utils.utils import WatsonxAPIWarning
        warnings.filterwarnings(
            "ignore",
            message=".*Non-IBM Product.*",
            category=WatsonxAPIWarning,
        )
    except ImportError:
        pass

    model_id = sys.argv[1] if len(sys.argv) > 1 else None

    from agent.llm import WatsonxLLM
    from agent.loop import run_agent

    llm = WatsonxLLM(model_id=model_id)
    print(f"NovaTech Recovery Agent  |  model: {llm.model_id}")
    print("Type 'quit' or 'exit' to end the session.\n")

    history = None
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye.")
            break

        result = run_agent(user_input, history=history, llm=llm)

        if result["tool_trace"]:
            print("Tools called:")
            for entry in result["tool_trace"]:
                _print_tool_call(entry)

        print(f"\nAgent: {result['answer']}\n")
        if result.get("error"):
            print(f"  (technical detail: {result['error']})\n")

        if result["proposal"]:
            p = result["proposal"]
            m = p.get("metrics", {})
            print(
                f"  📋 Proposal {p['proposal_id'][:8]}…  "
                f"status={p['status']}  "
                f"on_time={m.get('on_time_orders', '?')}  "
                f"cost=${m.get('total_extra_cost', '?')}\n"
            )

        history = result["history"]


if __name__ == "__main__":
    main()
