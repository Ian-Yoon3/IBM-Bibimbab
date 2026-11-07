"""
check_wx.py — watsonx.ai connectivity & tool-calling probe

Usage:
    python scripts/check_wx.py                        # list chat-capable models
    python scripts/check_wx.py <model_id>             # run tool-call test
"""

import json
import os
import sys
import urllib.request

from dotenv import load_dotenv

load_dotenv()

WX_API_KEY    = os.environ.get("WX_API_KEY", "")
WX_PROJECT_ID = os.environ.get("WX_PROJECT_ID", "")
WX_URL        = os.environ.get("WX_URL", "https://us-south.ml.cloud.ibm.com").rstrip("/")

# ── helpers ──────────────────────────────────────────────────────────────────

def _get_iam_token() -> str:
    """Exchange an IBM Cloud API key for a short-lived IAM bearer token."""
    data = (
        "grant_type=urn%3Aibm%3Aparams%3Aoauth%3Agrant-type%3Aapikey"
        f"&apikey={urllib.parse.quote(WX_API_KEY)}"
    ).encode()
    req = urllib.request.Request(
        "https://iam.cloud.ibm.com/identity/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


# ── step (b): list models ─────────────────────────────────────────────────────

def list_models() -> None:
    url = (
        f"{WX_URL}/ml/v1/foundation_model_specs"
        "?version=2025-02-11&filters=function_text_chat&limit=200"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    resources = data.get("resources", [])
    print(f"{'model_id'}")
    print("-" * 60)
    for r in resources:
        print(r.get("model_id", "<unknown>"))
    print(f"\n{len(resources)} models found.")


# ── step (c): tool-call test ──────────────────────────────────────────────────

DUMMY_TOOL = {
    "type": "function",
    "function": {
        "name": "compare_scenarios",
        "description": "Compare supply-chain recovery scenarios.",
        "parameters": {
            "type": "object",
            "properties": {
                "budget": {
                    "type": "integer",
                    "description": "Optional budget ceiling in USD.",
                },
            },
            "required": [],
        },
    },
}

USER_MSG = "Which recovery option is best if our budget is 500 dollars?"


def test_tool_call(model_id: str) -> None:
    from ibm_watsonx_ai import APIClient, Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference

    creds = Credentials(url=WX_URL, api_key=WX_API_KEY)
    client = APIClient(credentials=creds, project_id=WX_PROJECT_ID)

    model = ModelInference(
        model_id=model_id,
        api_client=client,
    )

    response = model.chat(
        messages=[{"role": "user", "content": USER_MSG}],
        tools=[DUMMY_TOOL],
        tool_choice_option="auto",
    )

    msg = response["choices"][0]["message"]
    print(json.dumps(msg, indent=2))

    if msg.get("tool_calls"):
        print("\nTOOL CALL OK")
    else:
        print("\nNO TOOL CALL")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import urllib.parse  # needed by _get_iam_token; import here avoids top-level side-effect

    if len(sys.argv) >= 2:
        test_tool_call(sys.argv[1])
    else:
        list_models()
