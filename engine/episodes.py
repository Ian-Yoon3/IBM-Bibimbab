"""Episode helpers: shock lookup, derived tags, world identity."""
from datetime import date


def cause_of(db: dict, target_type: str, target_id: str):
    """Return the cause_id whose targets include (target_type, target_id), or None."""
    causes = db.get("causes")
    if not causes:
        return None
    for row in causes:
        if row["target_type"] == target_type and row["target_id"] == target_id:
            return row["cause_id"]
    return None


def first_overlap_delay(episodes: list, order_date: date, promised_date: date) -> int:
    """Return the delay of the first episode that overlaps [order_date, promised_date].

    An episode overlaps when episode.start <= promised_date AND episode.end >= order_date.
    Returns 0 if no episode overlaps.
    Episodes are tested in slot order (the order they appear in the list).
    """
    for ep in episodes:
        if ep["start"] <= promised_date and ep["end"] >= order_date:
            return ep["delay"]
    return 0


def derived_tags(world: dict, db: dict) -> dict:
    """Return {cause_id: 0 or 1} for a world.

    For a new-format world (non-empty "episodes" dict):
        1 if any episode of the cause has start <= H0 and end >= DAY0, else 0.
    For a legacy world return world.get("tags", {}).
    """
    episodes = world.get("episodes", {})
    if not episodes:
        return world.get("tags", {})

    cause_horizons = db.get("cause_horizons") or {}
    DAY0 = db["DAY0"]
    result = {}
    for cause_id, ep_list in episodes.items():
        H0 = cause_horizons.get(cause_id, {}).get("H0")
        tag = 0
        if H0 is not None:
            for ep in ep_list:
                if ep["start"] <= H0 and ep["end"] >= DAY0:
                    tag = 1
                    break
        result[cause_id] = tag
    return result


def world_identity(world: dict):
    """Return a hashable value built from the world's overrides and episodes."""
    overrides_part = frozenset(world.get("overrides", {}).items())
    episodes = world.get("episodes", {})
    ep_parts = []
    for cause_id in sorted(episodes.keys()):
        for ep in episodes[cause_id]:
            ep_parts.append((cause_id, ep["start"], ep["end"], ep["delay"]))
    return (overrides_part, tuple(ep_parts))
