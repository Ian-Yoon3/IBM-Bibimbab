"""WatsonxLLM — thin wrapper around ibm_watsonx_ai ModelInference.

Public interface
----------------
normalize_tool_calls(raw_message) -> dict
    Pure function.  Converts a raw watsonx chat response message into a
    normalised shape::

        {
            "content": str | None,
            "tool_calls": [
                {"id": str, "name": str, "args": dict}
            ]
        }

    Handles both Granite-style arguments (JSON-encoded string) and
    Llama-style arguments (already a dict).

WatsonxLLM
    .chat(messages, tools) -> normalised message dict (same shape as above)
"""

import json
import os

from dotenv import load_dotenv


# ── argument normalisation (pure, testable without network) ──────────────────

def normalize_tool_calls(raw_message: dict) -> dict:
    """Normalise a raw watsonx chat response message.

    Parameters
    ----------
    raw_message:
        The ``message`` dict from ``response["choices"][0]["message"]``.

    Returns
    -------
    dict with keys:
        content     – str or None
        tool_calls  – list of {"id": str, "name": str, "args": dict}
    """
    tool_calls = []
    for tc in raw_message.get("tool_calls") or []:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                decoded = json.loads(raw_args)
                # Granite sometimes double-encodes: the result is another string
                if isinstance(decoded, str):
                    try:
                        decoded = json.loads(decoded)
                    except json.JSONDecodeError:
                        decoded = {}
                args = decoded if isinstance(decoded, dict) else {}
            except json.JSONDecodeError:
                args = {}
        else:
            args = raw_args if isinstance(raw_args, dict) else {}
        tool_calls.append({
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "args": args,
        })
    return {
        "content": raw_message.get("content"),
        "tool_calls": tool_calls,
    }


# ── WatsonxLLM ────────────────────────────────────────────────────────────────

class WatsonxLLM:
    """Wraps ibm_watsonx_ai ModelInference with a normalised .chat() interface.

    Parameters
    ----------
    model_id:
        watsonx.ai model ID.  Defaults to env ``WX_MODEL_ID`` or
        ``ibm/granite-4-h-small``.
    max_tokens:
        Maximum tokens in the response.  Defaults to 2048.
    """

    def __init__(self, model_id: str | None = None, max_tokens: int = 2048):
        load_dotenv()
        api_key    = os.environ.get("WX_API_KEY", "")
        project_id = os.environ.get("WX_PROJECT_ID", "")
        url        = os.environ.get("WX_URL", "https://us-south.ml.cloud.ibm.com")
        if not api_key:
            raise ValueError("WX_API_KEY is not set")
        if not project_id:
            raise ValueError("WX_PROJECT_ID is not set")

        resolved_model = (
            model_id
            or os.environ.get("WX_MODEL_ID", "ibm/granite-4-h-small")
        )

        # Import here so the module can be imported without ibm_watsonx_ai
        # installed (e.g. in pure-stdlib engine tests).
        from ibm_watsonx_ai import APIClient, Credentials
        from ibm_watsonx_ai.foundation_models import ModelInference

        creds  = Credentials(url=url, api_key=api_key)
        client = APIClient(credentials=creds, project_id=project_id)
        self._model = ModelInference(
            model_id=resolved_model,
            api_client=client,
            params={"max_new_tokens": max_tokens, "temperature": 0},
        )
        self.model_id = resolved_model

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Call the model and return a normalised message dict.

        Parameters
        ----------
        messages:
            Conversation history in OpenAI-compatible format.
        tools:
            List of tool JSON schemas.

        Returns
        -------
        Normalised message dict — see ``normalize_tool_calls``.
        """
        response = self._model.chat(
            messages=messages,
            tools=tools,
            tool_choice_option="auto",
        )
        raw_message = response["choices"][0]["message"]
        return normalize_tool_calls(raw_message)
