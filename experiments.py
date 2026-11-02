"""Experiments that back the Problem Solving and Interview answers with real evidence.

Run:  python experiments.py
Each section is independent and builds its own fresh fixtures.
"""
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

import test_runner as tr
from ecommerce_app import Cart, D, fixture

ROOT = Path(__file__).resolve().parent


def header(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def row(cid, fixture_key, inputs, expected, operation="place_sequence", **extra):
    base = {"test_case_id": cid, "requirement_id": "REQ-X", "condition_id": "COND-X", "scenario_id": "TS-X",
            "title": cid, "priority": "P1", "precondition": "", "fixture_key": fixture_key,
            "input_json": tr.json.dumps(inputs), "expected_type": "", "expected_json": tr.json.dumps(expected),
            "execution_status": "", "actual_result": "", "error_message": "", "evidence_reference": "",
            "operation": operation, "test_type": "", "blocked_reason": ""}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
header("EXP-0  Fidelity check: this app behaves like the reference in the Instruction")
app, user, cart = fixture("600k")
print("Subtotal:", cart.subtotal(), "| stock before:", {k: p.stock for k, p in app.catalog.products.items()})
order = app.place(user, cart, voucher="SAVE10", method="COD", key="DEMO-001")
print("Discount:", order.discount, "| Shipping:", order.shipping, "| Total:", order.total, "| Status:", order.status)
print("Stock after:", {k: p.stock for k, p in app.catalog.products.items()})
print("Instruction section 2.7 expects: 600000 / 60000 / 0 / 540000 / PENDING_COD / A=17")

sample = [
    row("TC-PRO-001", "600k", {"calls": [{"voucher": "SAVE10", "key": "k"}]}, {"error": None, "discount": 60000}),
    row("TC-PRO-002", "500k", {"calls": [{"voucher": "SAVE10", "key": "k"}]}, {"error": None, "discount": 50000}),
    row("TC-PRO-003", "499999", {"calls": [{"voucher": "SAVE10", "key": "k"}]}, {"error": "MIN_SUBTOTAL_NOT_MET"}),
    row("TC-PRO-004", "1500k", {"calls": [{"voucher": "SAVE10", "key": "k"}]}, {"error": None, "discount": 100000}),
    row("TC-PRO-005", "1000k", {"calls": [{"voucher": "SAVE10", "key": "k"}]}, {"error": None, "discount": 100000}),
    row("TC-PRO-006", "300k", {"calls": [{"key": "k"}]}, {"error": None, "discount": 0}),
    row("TC-INV-001", "600k", {"calls": [{"method": "ONLINE", "approved": True, "key": "k"}]}, {"error": None, "order_status": "PAID"}),
    row("TC-INV-002", "600k", {"setup": {"stock": {"A": 0, "B": 0, "C": 0}}, "calls": [{"key": "k"}]}, {"error": "OUT_OF_STOCK"}),
    row("TC-INV-003", "600k", {"calls": [{"method": "ONLINE", "approved": False, "key": "k"}]}, {"error": "PAYMENT_DECLINED", "stock": "unchanged"}),
    row("TC-INV-004", "500k", {"calls": [{"method": "ONLINE", "approved": False, "key": "k"}]}, {"error": "PAYMENT_DECLINED", "stock": "unchanged"}),
    row("TC-IDM-001", "600k", {"calls": [{"key": "K"}, {"key": "K"}]}, {"error": None, "orders": 1, "stock": {"A": 17, "B": 15, "C": 12}}),
    row("TC-IDM-002", "300k", {"calls": [{"key": "K"}, {"key": "K"}]}, {"error": None, "orders": 1, "stock": {"A": 20, "B": 14, "C": 12}}),
]
sample_results = [tr.execute_row(r) for r in sample]
print("Instruction's 12 sample cases re-expressed in this runner:",
      {s: sum(1 for r in sample_results if r["execution_status"] == s) for s in (tr.PASS, tr.FAIL)},
      "| FAIL ids:", [r["test_case_id"] for r in sample_results if r["execution_status"] == tr.FAIL])
print("Instruction section 4.3 reports 7 PASS and 5 FAIL (PRO-002, INV-003, INV-004, IDM-001, IDM-002)")

# ---------------------------------------------------------------------------
header("EXP-1  Problem 3.4: when is the price fixed? (price changes between add-to-cart and checkout)")
app, user, cart = tr.build_state("empty", {})
cart.add("B", 1)
print("CartLine fields:", [f for f in cart.lines[0].__dataclass_fields__])
print("Subtotal right after add-to-cart:", cart.subtotal())
app.catalog.products["B"].price = D(350000)
order = app.place(user, cart, area="inner", method="COD", key="K-PRICE")
print("Catalog price of B changed to 350000 before checkout")
print("Order subtotal-based result -> shipping:", order.shipping, "| total:", order.total)
print("Observation: no price is stored in CartLine, so the price is resolved at checkout time.")

# ---------------------------------------------------------------------------
header("EXP-2  Problem 3.6: shared state between data-driven tests")
shared_app, shared_user, shared_cart = fixture("600k")
shared_app.place(shared_user, shared_cart, method="COD", key="CASE-X")
print("Case X ran first on the SHARED fixture. Stock A is now", shared_app.catalog.products["A"].stock)
case_y_cart = Cart(shared_app.catalog)
case_y_cart.add("A", 3)
shared_app.place(shared_user, case_y_cart, method="COD", key="CASE-Y")
print("Case Y expects stock A = 20 - 3 = 17, observed", shared_app.catalog.products["A"].stock,
      "->", "PASS" if shared_app.catalog.products["A"].stock == 17 else "FAIL (caused by shared state, not by a product bug)")
fresh_app, fresh_user, fresh_cart = fixture("600k")
fresh_app.place(fresh_user, fresh_cart, method="COD", key="CASE-Y")
print("Case Y on a FRESH fixture observes stock A =", fresh_app.catalog.products["A"].stock, "-> PASS")
fixture("499999")
print("After fixture('499999') changed B to 299999, a new fixture('500k') sees B =", fixture("500k")[0].catalog.products["B"].price)

cases = tr.load_cases(ROOT / "test_cases.csv")
records = cases.to_dict("records")
baseline = {r["test_case_id"]: tr.execute_row(r)["execution_status"] for r in records}
same = True
for seed in (1, 2, 3):
    shuffled = records[:]
    random.Random(seed).shuffle(shuffled)
    again = {r["test_case_id"]: tr.execute_row(r)["execution_status"] for r in shuffled}
    same = same and again == baseline
print("Proof of isolation: 3 random execution orders give the same status for all", len(baseline), "cases:", same)

# ---------------------------------------------------------------------------
header("EXP-3  Problem 3.7: 20 CSV rows, 3 rows cannot be parsed, '17 PASS' is not '100%'")
pass_ids = [cid for cid, st in baseline.items() if st == tr.PASS][:20]
twenty = [dict(r) for r in records if r["test_case_id"] in pass_ids]
for r in twenty[:3]:
    r["input_json"] = r["input_json"][:-3]
naive_pass = naive_total = 0
for r in twenty:
    try:
        tr.json.loads(r["input_json"])
        tr.json.loads(r["expected_json"])
    except ValueError:
        continue
    naive_total += 1
    naive_pass += tr.execute_row(r)["execution_status"] == tr.PASS
print(f"Naive runner (skips unparsable rows): executed {naive_total} of {len(twenty)}, PASS {naive_pass}, "
      f"pass rate {100 * naive_pass / naive_total:.0f}%  <- misleading")
good = [tr.execute_row(r) for r in twenty]
counts = pd.Series([g["execution_status"] for g in good]).value_counts().to_dict()
print(f"This runner: executed {len(good)} of {len(twenty)}, {counts}, "
      f"pass rate {100 * counts.get('PASS', 0) / len(good):.0f}%, completeness COMPLETE because BLOCKED rows are kept")
for g in good:
    if g["execution_status"] == tr.BLOCKED:
        print("  ", g["test_case_id"], "->", g["error_message"])

# ---------------------------------------------------------------------------
header("EXP-4  Problem 3.8: free-shipping threshold changes from 500k to 700k (change impact)")
source = (ROOT / "ecommerce_app.py").read_text(encoding="utf-8")
assert source.count("subtotal>=D(500000)") == 1
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "ecommerce_app.py").write_text(source.replace("subtotal>=D(500000)", "subtotal>=D(700000)"), encoding="utf-8")
    for name in ("test_runner.py", "test_cases.csv", "design_catalog.csv"):
        shutil.copy(ROOT / name, tmp / name)
    subprocess.run([sys.executable, "test_runner.py", "--out", "out"], cwd=tmp, capture_output=True, text=True, check=True)
    changed = pd.read_csv(tmp / "out" / "test_execution.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
flipped = changed[changed["test_case_id"].map(baseline) != changed["execution_status"]]
print("Cases whose status changes if only the shipping constant is edited:", len(flipped))
for _, r in flipped.iterrows():
    print(f"  {r['test_case_id']} {baseline[r['test_case_id']]} -> {r['execution_status']} | {r['error_message']}")
print("Cases untouched by the change still pass:",
      int((changed["test_case_id"].map(baseline) == changed["execution_status"]).sum()), "of", len(changed))

# ---------------------------------------------------------------------------
header("EXP-5  Code interview B: false positive when only the return value is checked")
full = {r["test_case_id"]: tr.execute_row(r) for r in records if r["requirement_id"] == "REQ-16"}
print("REQ-16 cases, naive check (only 'error == INVALID_PAYMENT_METHOD') vs full check (error + orders + charges + stock):")
for cid, r in full.items():
    naive = tr.json.loads(r["checks_json"])[0]["ok"]
    print(f"  {cid}: naive={'PASS' if naive else 'FAIL'} | full={r['execution_status']}")
retry = tr.execute_row(sample[10])
print("TC-IDM-001 style retry: order_id is not None ->", tr.json.loads(retry["actual_result"])["order_id"] is not None,
      "(naive PASS) but full check =", retry["execution_status"], "|", retry["error_message"])

# ---------------------------------------------------------------------------
header("EXP-6  Code interview A: expected exception vs unexpected exception")
probes = [
    row("PROBE-a", "empty", {"steps": [["A", 0]]}, {"error": "INVALID_QUANTITY"}, "cart_add_sequence"),
    row("PROBE-b", "empty", {"steps": [["A", 1]]}, {"error": "INVALID_QUANTITY"}, "cart_add_sequence"),
    row("PROBE-c", "empty", {"steps": [["A", 0]]}, {"error": None}, "cart_add_sequence"),
    row("PROBE-d", "empty", {"steps": [["Z", 1]]}, {"error": "INVALID_QUANTITY"}, "cart_add_sequence"),
    row("PROBE-e", "300k", {"subtotal": "abc", "area": "inner"}, {"shipping": 30000}, "shipping_calc"),
    row("PROBE-f", "no_such_fixture", {"steps": [["A", 1]]}, {"error": None}, "cart_add_sequence"),
]
notes = {"a": "expected exception raised", "b": "expected exception NOT raised",
         "c": "unexpected exception raised", "d": "different exception than expected",
         "e": "bad test data", "f": "bad fixture name"}
for p in probes:
    r = tr.execute_row(p)
    print(f"  {p['test_case_id']} ({notes[p['test_case_id'][-1]]}): {r['execution_status']} | {r['error_message']}")

# ---------------------------------------------------------------------------
header("EXP-7  Problems 3.2 and 3.3: a failed call followed by a retry")
app, user, cart = fixture("600k")
stock_a = lambda: app.catalog.products["A"].stock
try:
    app.place(user, cart, voucher="SAVE10", method="ONLINE", approved=False, key="K-A")
except ValueError as exc:
    print("3.2 call 1 (ONLINE declined, SAVE10):", exc, "| used_codes:", sorted(user.used_codes), "| stock A:", stock_a())
order = app.place(user, cart, voucher="SAVE10", method="COD", key="K-B")
print("3.2 call 2 (COD, SAVE10):", order.status, "| used_codes:", sorted(user.used_codes), "| stock A:", stock_a(),
      "| stock A expected after exactly one order: 17")
app, user, cart = fixture("600k")
stock_a = lambda: app.catalog.products["A"].stock
try:
    app.place(user, cart, method="WALLET", key="K-W")
except ValueError as exc:
    print("3.3 call 1 (WALLET):", exc, "| orders:", len(app.orders), "| charges:", len(app.payments.charges),
          "| by_key:", list(app.by_key), "| stock A:", stock_a())
order = app.place(user, cart, method="COD", key="K-W")
print("3.3 call 2 (COD, same key K-W):", order.order_id, order.status, "| stock A:", stock_a(),
      "| stock A expected after exactly one order: 17")
