"""TEMPORARY. Stage 1 only. Writes world data from a triangular three-point
estimate until the stage 2 Monte Carlo engine replaces this script.
Nothing in engine/, agent/ or scripts/ may import this module.
Delete this file and tests/test_stage1_triangular_worlds.py when stage 2
writes data/worlds.csv. See docs/decisions/0002-receipt-date-weights.md."""

import argparse
import csv
import pathlib
from datetime import date, timedelta
from fractions import Fraction


# ---------------------------------------------------------------------------
# Pure function: triangular day weights
# ---------------------------------------------------------------------------

def _tri_cdf(x, a, c, b):
    """Closed-form CDF of the triangular distribution (exact, using Fraction).

    Parameters
    ----------
    x, a, c, b : Fraction
        x   – evaluation point
        a   – left edge  (earliest - 0.5)
        c   – peak       (mode)
        b   – right edge (latest + 0.5)
    """
    if x <= a:
        return Fraction(0)
    if x >= b:
        return Fraction(1)
    ba = b - a
    if x <= c:
        return (x - a) ** 2 / (ba * (c - a))
    return Fraction(1) - (b - x) ** 2 / (ba * (b - c))


def triangular_day_weights(earliest, mode, latest, total):
    """Return a list of (date, int) with integer weights summing to *total*.

    The weight of each calendar day d is proportional to the probability mass
    that the continuous triangular distribution (a = earliest - 0.5 day,
    peak = mode, b = latest + 0.5 day) assigns to the interval [d-0.5, d+0.5].
    This is computed exactly with the closed-form CDF and Python's Fraction type
    so that symmetric inputs always produce symmetric outputs.

    Integers are produced by the largest-remainder method.  Ties in the
    remainder step go to the earlier date.  Days whose integer weight is zero
    are omitted from the result.

    Raises ValueError if earliest > mode, mode > latest, or total <= 0.
    """
    if not (earliest <= mode <= latest):
        raise ValueError(
            f"dates must satisfy earliest <= mode <= latest, "
            f"got {earliest} <= {mode} <= {latest}"
        )
    if total <= 0:
        raise ValueError(f"total must be a positive int, got {total}")

    # Degenerate case: single day
    if earliest == mode == latest:
        return [(earliest, total)]

    # Build the date range
    days = []
    d = earliest
    while d <= latest:
        days.append(d)
        d += timedelta(days=1)

    # Triangle parameters as exact fractions
    # origin = earliest; offsets are integers (0, 1, 2, ...)
    origin = earliest
    a = Fraction(-1, 2)                               # earliest - 0.5
    c = Fraction((mode - origin).days)                # mode offset
    b = Fraction((latest - origin).days) + Fraction(1, 2)   # latest + 0.5

    # Exact probability mass for each day via closed-form CDF
    raw = []
    for day in days:
        x = Fraction((day - origin).days)
        half = Fraction(1, 2)
        mass = _tri_cdf(x + half, a, c, b) - _tri_cdf(x - half, a, c, b)
        raw.append(mass)

    total_mass = sum(raw)  # == 1 by construction, but use sum for safety

    # Scale to exact rationals that would sum to total
    scaled = [r * total / total_mass for r in raw]

    # Largest-remainder method: floor each value, then distribute the deficit
    floors = [int(s) for s in scaled]          # int() truncates toward zero
    remainders = [(scaled[i] - floors[i], i) for i in range(len(days))]
    deficit = total - sum(floors)

    # Sort descending by remainder; ties broken by earlier date (smaller index)
    remainders.sort(key=lambda t: (-t[0], t[1]))
    for k in range(deficit):
        floors[remainders[k][1]] += 1

    # Drop zero-weight days
    result = [
        (day, weight)
        for day, weight in zip(days, floors)
        if weight > 0
    ]
    return result


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _world_id(n):
    """Return a zero-padded world id string such as 'W001'."""
    return f"W{n:03d}"


def write_worlds(weights, po, out_dir):
    """Write worlds.csv and world_overrides.csv into out_dir.

    Parameters
    ----------
    weights : list of (date, int)   – output of triangular_day_weights
    po      : str                   – purchase-order id (e.g. 'PO01')
    out_dir : str or Path           – directory to write into (created if absent)

    Returns
    -------
    list of (world_id, date, weight) – one entry per world written
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for idx, (day, weight) in enumerate(weights, start=1):
        rows.append((_world_id(idx), day, weight))

    worlds_path = out_dir / "worlds.csv"
    overrides_path = out_dir / "world_overrides.csv"

    with open(worlds_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["world_id", "weight"])
        for world_id, _, weight in rows:
            writer.writerow([world_id, weight])

    with open(overrides_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["world_id", "target_type", "target_id", "field", "value"])
        for world_id, day, _ in rows:
            writer.writerow(
                [world_id, "purchase_order", po, "receipt_date", day.isoformat()]
            )

    return rows


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_date(s):
    return date.fromisoformat(s)


def main():
    parser = argparse.ArgumentParser(
        description="TEMPORARY stage 1 triangular worlds generator."
    )
    parser.add_argument("--earliest", type=_parse_date, default="2026-11-11")
    parser.add_argument("--mode",     type=_parse_date, default="2026-11-17")
    parser.add_argument("--latest",   type=_parse_date, default="2026-11-21")
    parser.add_argument("--total",    type=int,         default=1000)
    parser.add_argument("--po",       default="PO01")
    parser.add_argument("--out-dir",  default="data")
    args = parser.parse_args()

    weights = triangular_day_weights(
        args.earliest, args.mode, args.latest, args.total
    )
    rows = write_worlds(weights, args.po, args.out_dir)

    print("TEMPORARY stage 1 generator - worlds written to", args.out_dir)
    print()
    print(f"{'world_id':<10} {'receipt_date':<14} {'weight':>8}")
    print("-" * 34)
    for world_id, day, weight in rows:
        print(f"{world_id:<10} {day.isoformat():<14} {weight:>8}")
    print("-" * 34)
    print(f"{'total':<10} {'':<14} {sum(w for _, w in weights):>8}")


if __name__ == "__main__":
    main()
