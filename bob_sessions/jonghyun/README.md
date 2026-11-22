# IBM Bob usage record: Jonghyun (John) Moon

Scope: Synthetic Baseline V1 for the IBM SkillsBuild Supply Chain Recovery Decision Agent. See the [baseline contribution record](../../docs/baseline-v1-contribution.md) and [repository setup notes](../dennis/README.md#what-was-not-written-in-bob).

## Sessions

No IBM Bob task export or screenshot is attached to this record. The section below summarizes the baseline work using the project's dataset and validation artifacts.

## Contribution

| File or folder | Work |
|---|---|
| [`data/`](../../data/) | Designed 14 linked CSV inputs for the fictional NovaTech Manufacturing supply chain, covering products, components, suppliers, warehouses, inventory, and orders. |
| [`data/bom.csv`](../../data/bom.csv) | Defined the components and quantities required to assemble each product. |
| [`data/disruptions.csv`](../../data/disruptions.csv) and [`data/scenarios.csv`](../../data/scenarios.csv) | Defined the six-day delay of PO01 and five scenarios covering normal operations, waiting, transfers, alternate purchasing, and combined recovery. |
| [`reference/`](../../reference/) | Documented the dataset and simulation assumptions and provided a Python verifier. |
| [`tests/expected/`](../../tests/expected/) | Prepared expected scenario summaries, order results, inventory movements, and validation checks. |

## Result

Run `python3 reference/verify.py` from the repository root. The reference check passes for the master data, BOM, five scenario replays, 60 expected order starts, costs, and inventory conservation.
