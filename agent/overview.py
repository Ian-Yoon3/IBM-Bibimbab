"""Overview module: no-LLM entry point for the world-risk view.

get_overview() is the fourth function the UI may call, alongside
run_agent, record_decision and list_decisions.  It makes no network calls
and uses no watsonx.ai credits.
"""

from agent.render import world_risk_view


def get_overview(disruption_id: str = "D01") -> dict:
    """Return the world_risk overview view for a disruption.

    No LLM call, no network.  Uses the engine cache after the first call.

    Parameters
    ----------
    disruption_id : str
        The disruption to summarise (default "D01").

    Returns
    -------
    world_risk_view("overview") dict.
    """
    return world_risk_view("overview", disruption_id=disruption_id)
