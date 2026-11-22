# Synthetic Baseline V1 contribution

John (Jonghyun) prepared the Synthetic Baseline V1 materials for the IBM SkillsBuild Supply Chain Recovery Decision Agent. The baseline models NovaTech Manufacturing and gives the team a reproducible dataset for evaluating recovery decisions.

- [Baseline inputs](../data/) define the synthetic products, components, suppliers, orders, and inventory. The [bill of materials](../data/bom.csv) maps each product to the components needed to build it.
- The [disruption record](../data/disruptions.csv) captures the six-day delay of PO01. The [scenario definitions](../data/scenarios.csv) cover the undisrupted baseline, waiting, stock transfers, alternate purchasing, and a combination of transfers and alternate purchasing.
- The [data dictionary](../reference/data_dictionary.md) describes the inputs. The [expected results](../tests/expected/) record the scenario summaries, order-level outcomes, inventory movements, and validation checks.

Run `python3 reference/verify.py` from the repository root to replay the five scenarios and validate the BOM, 60 expected order starts, costs, and inventory conservation. The [baseline README](../reference/README.md) describes the simulation assumptions and results.
