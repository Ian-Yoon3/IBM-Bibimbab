"""
demo.py — MVP 1 demo of the Supply Chain Recovery Decision Agent engine.

Run from the repo root:
    python3 demo.py
No arguments required.
"""
import sys

# Windows consoles and pipes may use a legacy code page (e.g. cp949) that
# cannot print "─", "—" or "→".  Replace such characters instead of crashing.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from engine.tools import (
    get_disruption,
    get_impact,
    compare_scenarios,
    get_priority_view,
    explore_purchase_qty,
    propose_action,
)
from engine.simulate import build_scenario_actions
from engine.loader import load_all

_DB = load_all()

SEP = "─" * 70


def _header(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def _kv(key: str, value) -> None:
    print(f"  {key:<32} {value}")


# ── Step 1: Understand the disruption ─────────────────────────────────────────
_header("STEP 1 · get_disruption('D01')")
print("  Tool: get_disruption  |  Input: disruption_id='D01'\n")

dis = get_disruption("D01")
_kv("Disruption ID:", dis["disruption_id"])
_kv("Reason:", dis["reason"])
_kv("Affected PO:", dis["po_id"])
_kv("Component:", f"{dis['component_id']}  (qty {dis['qty']} units)")
_kv("Original receipt date:", dis["original_receipt_date"])
_kv("Revised receipt date:", dis["revised_receipt_date"])
_kv("Delay:", f"{dis['delay_days']} days")

# ── Step 2: Quantify the impact with no action ─────────────────────────────────
_header("STEP 2 · get_impact('D01')  [WAIT scenario — no recovery actions]")
print("  Tool: get_impact  |  Input: disruption_id='D01'\n")

imp = get_impact("D01")
_kv("First late order:", imp["first_late_order_id"])
_kv("First order late by:", f"{imp['first_late_days']} days")
_kv("Total late orders:", len(imp["late_orders"]))
late_ids = [r["order_id"] for r in imp["late_orders"]]
print(f"  {'Late order IDs:':<32} {', '.join(late_ids)}")

print("\n  C01 shortage at WH01 (first shortage day):")
for row in imp["c01_shortage_by_day"]:
    if row["shortage"] > 0:
        print(
            f"    {row['date']}  available={row['c01_available_wh01']:>3}  "
            f"cumulative_needed={row['c01_cumulative_needed']:>3}  "
            f"shortage={row['shortage']:>3}"
        )

# ── Step 3: Compare all disrupted recovery scenarios ──────────────────────────
_header("STEP 3a · compare_scenarios()  [no budget constraint]")
print("  Tool: compare_scenarios  |  Objective: on_time_orders\n")

comp_all = compare_scenarios(objective="on_time_orders")
bl = comp_all["baseline"]
print(f"  Baseline (NORMAL — no disruption): "
      f"{bl['on_time_orders']} on-time orders, ${bl['total_extra_cost']} extra cost\n")
print(f"  {'Rank':<6} {'Scenario':<12} {'On-time orders':<18} "
      f"{'Total late days':<18} {'Extra cost USD'}")
print(f"  {'─'*4:<6} {'─'*10:<12} {'─'*14:<18} {'─'*15:<18} {'─'*14}")
for r in comp_all["ranked"]:
    print(f"  {r['rank']:<6} {r['scenario_id']:<12} {r['on_time_orders']:<18} "
          f"{r['total_order_days_late']:<18} ${r['total_extra_cost']}")
print(f"\n  Best (no budget): {comp_all['best']}")

_header("STEP 3b · compare_scenarios(budget=500)")
print("  Tool: compare_scenarios  |  Budget: $500  |  Objective: on_time_orders\n")

comp_500 = compare_scenarios(budget=500, objective="on_time_orders")
print(f"  {'Rank':<6} {'Scenario':<12} {'On-time orders':<18} {'Extra cost USD'}")
print(f"  {'─'*4:<6} {'─'*10:<12} {'─'*14:<18} {'─'*14}")
for r in comp_500["ranked"]:
    print(f"  {r['rank']:<6} {r['scenario_id']:<12} {r['on_time_orders']:<18} "
          f"${r['total_extra_cost']}")
print(f"\n  Best within $500 budget: {comp_500['best']}")

# ── Step 4: Priority view for best option (HYBRID) ────────────────────────────
_header("STEP 4 · get_priority_view for HYBRID (best unconstrained option)")
print("  Tool: get_priority_view  |  Scenario: HYBRID\n")

hybrid_actions, hybrid_dis = build_scenario_actions("HYBRID", _DB)
pv = get_priority_view(hybrid_actions, hybrid_dis)
print(f"  Priority-1 orders on time: {pv['on_time_count']} / {pv['total_count']}\n")
print(f"  {'Order':<8} {'Customer':<10} {'Due':<14} {'Delivery':<14} {'Late days'}")
print(f"  {'─'*6:<8} {'─'*8:<10} {'─'*12:<14} {'─'*12:<14} {'─'*9}")
for r in pv["priority_1_orders"]:
    flag = " ← LATE" if r["days_late"] > 0 else ""
    print(f"  {r['order_id']:<8} {r['customer_id']:<10} {r['due_date']:<14} "
          f"{r['delivery_date']:<14} {r['days_late']}{flag}")

# ── Step 5: Explore purchase quantities (with transfers) ───────────────────────
_header("STEP 5 · explore_purchase_qty('OF02', include_transfers=True)  — top 3")
print("  Tool: explore_purchase_qty  |  Offer: OF02 (S02, C01)  "
      "|  include_transfers=True\n")

expl = explore_purchase_qty("OF02", include_transfers=True)
top3 = expl["ranked"][:3]
print(f"  {'Rank':<6} {'Label':<28} {'On-time orders':<18} "
      f"{'Total late days':<18} {'Extra cost USD'}")
print(f"  {'─'*4:<6} {'─'*26:<28} {'─'*14:<18} {'─'*15:<18} {'─'*14}")
for r in top3:
    # Explored options have scenario_id None; their identity is the label.
    print(f"  {r['rank']:<6} {r['label']:<28} {r['on_time_orders']:<18} "
          f"{r['total_order_days_late']:<18} ${r['total_extra_cost']}")

best = expl["best"]
best_label = best["label"] if isinstance(best, dict) else best
print(f"\n  Best option: {best_label}")

# ── Step 6: Propose the best action ───────────────────────────────────────────
_header("STEP 6 · propose_action('HYBRID', reason=...)")
print("  Tool: propose_action  |  Scenario: HYBRID\n")

reason = (
    "HYBRID maximises on-time orders (11/12) within a reasonable "
    "incremental cost ($1,306). Recommended when budget is unconstrained."
)
proposal = propose_action("HYBRID", reason)
_kv("Proposal ID:", proposal["proposal_id"])
_kv("Status:", proposal["status"])
_kv("Disruption applied:", proposal["disruption_id"])
_kv("On-time orders:", proposal["metrics"]["on_time_orders"])
_kv("Total late days:", proposal["metrics"]["total_order_days_late"])
_kv("Extra cost USD:", f"${proposal['metrics']['total_extra_cost']}")
_kv("Reason:", "")
print(f"    {reason}")
print(f"\n  Actions in proposal ({len(proposal['actions'])} total):")
for a in proposal["actions"]:
    if a["type"] == "purchase":
        print(f"    PURCHASE  offer={a['offer_id']}  qty={a['qty']}  "
              f"date={a['action_date']}  warehouse={a['warehouse_id']}")
    else:
        print(f"    TRANSFER  lane={a['lane_id']}  component={a['component_id']}  "
              f"qty={a['qty']}  date={a['action_date']}")

print(f"\n{SEP}")
print("  Demo complete.  All results are read-only — nothing was approved or executed.")
print(SEP)
