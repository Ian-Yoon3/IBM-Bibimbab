# ADR 0002. Weights for the uncertain receipt date of PO01 (stage 1)

- **Status:** Accepted for stage 1. Temporary. Replaced by the stage 2 Monte Carlo engine.
- **Date:** 2026-11-11
- **Branch:** `feature/extension-trial-ian`
- **Decision owner:** Sunghyuk (Ian) Yoon

## Context

The supplier of PO01 announced a new receipt date of 2026-11-17.
The original planned date was 2026-11-11.
A delay notice rarely gives one certain date, so stage 1 evaluates every option over a set of possible receipt dates.

Possible situations are stored as worlds.
A world is a set of overrides on the base data, with an integer weight.
`data/worlds.csv` holds `world_id,weight`.
`data/world_overrides.csv` holds `world_id,target_type,target_id,field,value`.
The engine divides each weight by the total weight.
In stage 1 each world overrides one value, the receipt date of PO01.

Two kinds of output come from these worlds.
Results per receipt date need no weights. "If PO01 arrives on 11-12, TRANSFER keeps every order on time" holds whatever the weights are.
Summary numbers need weights. These are expected late orders and the chance of no late order.
This record is about the weights only.

No delivery history exists for this supplier in the demo data.
The weights must therefore come from a stated rule, not from data.

## Options considered

| Option | Information used | Shape |
|---|---|---|
| Equal weights | Range only (11-11 to 11-21) | Flat |
| Triangular three-point estimate | Earliest, most likely, latest date | Peak at the announced date, linear tails |
| PERT (beta) three-point estimate | Same three dates | Peak at the announced date, thinner tails |
| Hand-picked numbers | Judgment only | Any |

## Selection logic

1. **Hand-picked numbers are excluded.** They cannot be traced to a rule. A reviewer cannot check them.
2. **Equal weights ignore known information.** Equal weights are the maximum entropy choice when only the range is known (Jaynes 1957). The announced date 11-17 is also known. Equal weights treat 11-11 as likely as 11-17, which contradicts the notice.
3. **A three-point estimate uses exactly what is known.** Earliest, most likely and latest values are the standard input for a duration estimate without data (Malcolm et al. 1959). Expert elicitation reviews describe the same practice of fitting a distribution to a few judged values (Garthwaite, Kadane and O'Hagan 2005).
4. **Triangular is chosen over PERT.** It needs one formula and can be checked by hand. Simulation textbooks recommend it when no data exist (Law 2015). PERT adds a beta function and changes the result only a little (see below).

## Decision

Use a triangular distribution with these three dates.

| Point | Date | Source |
|---|---|---|
| Earliest | 2026-11-11 | Original planned receipt date of PO01 |
| Most likely | 2026-11-17 | Date announced by the supplier (disruption D01) |
| Latest | 2026-11-21 | Last day of the simulation window |

Each day d stands for the interval from d minus half a day to d plus half a day.
The continuous triangle therefore runs from 10.5 to 21.5 (day of November) with its peak at 17.
The weight of a day is the area of the triangle over that day, from the closed-form distribution function.
Areas are scaled to integers that sum to 1000 by the largest remainder method.
1000 matches the form of Monte Carlo output, which is a count of samples.

| Date | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Weight | 14 | 42 | 70 | 98 | 126 | 154 | 173 | 141 | 101 | 61 | 20 |

Command that writes the two data files:

```
python -m scripts.stage1_triangular_worlds --earliest 2026-11-11 --mode 2026-11-17 --latest 2026-11-21 --total 1000
```

## Expected results

Computed in advance with the current engine (commit f9d5989). Stage 1 tests confirm them.

| Option | Extra cost | Expected late orders | Worst case | Chance of no late order |
|---|---|---|---|---|
| WAIT | $0 | 6.53 | 11 | 1.4% |
| TRANSFER | $416 | 3.73 | 8 | 5.6% |
| ALT_BUY | $1,250 | 2.99 | 7 | 1.4% |
| HYBRID | $1,306 | 1.36 | 5 | 35.0% |

For comparison, PERT weights with the same three dates give 6.93, 4.03, 3.21 and 1.51 expected late orders.
The order of the options is the same.

Equal weights give 6.0, 3.55, 3.0 and 1.55.
They match the table in `docs/extension-plan.md` and stay in the tests as a known answer.

## Limitations

1. **The latest date is not a judgment.** It is the end of the simulation window. The right tail is cut there. The mean of the distribution (11-16.3) falls before the announced date, while real delays more often slip later. Stage 2 separates the window from the order horizon and removes this cut.
2. **The shape is an assumption.** The triangle is a rule for the case without data. It is not evidence about this supplier.
3. **Only PO01 is uncertain in stage 1.** Lead times of the alternative supplier and the transfer lanes stay fixed.

## Temporary status

`scripts/stage1_triangular_worlds.py` and its test file exist only for stage 1.
Nothing in `engine/`, `agent/` or other scripts imports them.
When the stage 2 Monte Carlo engine writes `data/worlds.csv` and `data/world_overrides.csv`, both files are deleted and this record is marked superseded.
The data file format does not change.

## References

- E. T. Jaynes, "Information Theory and Statistical Mechanics," *Physical Review* 106(4), 620–630, 1957. [doi:10.1103/PhysRev.106.620](https://doi.org/10.1103/PhysRev.106.620)
  Founding paper of the maximum entropy principle. Cited tens of thousands of times and taught in standard statistical mechanics and probability texts.
- D. G. Malcolm, J. H. Roseboom, C. E. Clark, W. Fazar, "Application of a Technique for Research and Development Program Evaluation," *Operations Research* 7(5), 646–669, 1959. [doi:10.1287/opre.7.5.646](https://doi.org/10.1287/opre.7.5.646)
  Original PERT paper that introduced the three-point estimate. Standard in operations research and project management textbooks.
- P. H. Garthwaite, J. B. Kadane, A. O'Hagan, "Statistical Methods for Eliciting Probability Distributions," *Journal of the American Statistical Association* 100(470), 680–701, 2005. [doi:10.1198/016214505000000105](https://doi.org/10.1198/016214505000000105)
  Review article in a leading statistics journal. Widely cited reference on turning expert judgment into probability distributions.
- A. M. Law, *Simulation Modeling and Analysis*, 5th ed., McGraw-Hill, 2015. ISBN 978-0-07-340132-4. [Publisher page](https://www.mheducation.com/highered/product/simulation-modeling-and-analysis-law.html)
  Standard graduate textbook on simulation. Its section on selecting a distribution in the absence of data uses minimum, most likely and maximum values with a triangular distribution.
