"""Command-line entry point: python -m synthetic_history --data DIR --out DIR --seed INT"""

import argparse
import pathlib
import sys

from synthetic_history.generator import generate_history


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic shipment and episode history."
    )
    parser.add_argument("--data", default="data",
                        help="Path to the base data directory (default: data)")
    parser.add_argument("--out", required=True,
                        help="Directory to write output files into")
    parser.add_argument("--seed", required=True, type=int,
                        help="Random seed for reproducibility")
    args = parser.parse_args()

    data_dir = pathlib.Path(args.data)
    out_dir  = pathlib.Path(args.out)

    generate_history(data_dir, out_dir, args.seed)

    print(out_dir / "shipments.csv")
    print(out_dir / "episodes.csv")
    print(out_dir / "period.csv")


if __name__ == "__main__":
    main()
