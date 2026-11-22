# data/history: synthetic records for the demo

The three files in this folder are **synthetic**. They were generated for the demo. They are not recorded shipments.

The Monte Carlo engine estimates its rates from these files (`montecarlo/estimate.py`). It never reads this README and never calls the generator. The world-risk view reads this README only to decide whether to show the line "The history in data/history is synthetic".

## How the files were made

```
python -m synthetic_history --data data --out data/history --seed 20261109
```

The command reproduces the committed files exactly (line endings aside). `tests/test_synthetic_history.py` checks this.

The generator lives in `synthetic_history/`, outside `engine/` and `montecarlo/`. A boundary test makes sure no engine or Monte Carlo module imports it.

## True parameters of the generator

The estimator does not know these values. It sees only the CSV files.

| Source | Unit | Early / on time / late | Mean size of an early or late deviation | Shipments |
|---|---|---|---|---|
| OF01 | business days | 0.20 / 0.30 / 0.50 | 2 | 12 |
| OF02 | business days | 0.10 / 0.60 / 0.30 | 1.5 | 6 |
| LN01 | calendar days | 0.05 / 0.75 / 0.20 | 1.5 | 15 |
| LN02 | calendar days | 0.05 / 0.75 / 0.20 | 1.5 | 10 |

| Cause | Unit | Episodes per year | Mean delay | Mean duration |
|---|---|---|---|---|
| K1 (PO01, OF02) | business days | 4 | 3 days | 3 days |
| K2 (LN01, LN02) | calendar days | 5 | 2 days | 2 days |

The observation period is 2025-11-09 to 2026-11-08 (`period.csv`). The draw with this seed contains 3 K1 episodes and 7 K2 episodes. With so few episodes the estimates differ from the true rates (for example K2 about 8.3 per year against a true 5). The view shows this uncertainty as the range of the average.

## Replacing them with real records

1. Keep the column format of `shipments.csv`, `episodes.csv` and `period.csv`, described in `docs/montecarlo-engine.md` section 6.
2. Replace the three files with real records and set `period.csv` to the real observation window.
3. Edit or delete this README. While it says "synthetic", the view keeps showing the synthetic-history line.
4. Rebuild the run: `python -m montecarlo.run --data data --out runs/demo`. The fingerprint check refuses the old run until then.
