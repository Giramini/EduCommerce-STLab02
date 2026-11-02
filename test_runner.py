"""Data-driven test runner for the EduCommerce application (STLab02 homework).

Pipeline for every CSV row:
    read row -> validate -> build an isolated fixture -> dispatch to an operation
    -> compare expected and actual (return value AND resulting state)
    -> PASS / FAIL / BLOCKED -> CSV, Excel and HTML reports.

Status meaning:
    PASS     every expected check matched the observed behaviour
    FAIL     the application behaved differently from the expected result
    BLOCKED  the test itself could not run (bad test data, failed setup, no oracle yet).
             BLOCKED is never counted as a product defect.

Usage:
    python test_runner.py
    python test_runner.py --cases test_cases.csv --out reports
"""
import argparse
import base64
import csv
import datetime
import html
import json
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd

from ecommerce_app import Cart, D, fixture

ROOT = Path(__file__).resolve().parent
PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

REQUIRED_COLUMNS = [
    "test_case_id", "requirement_id", "condition_id", "scenario_id", "title", "priority",
    "precondition", "fixture_key", "input_json", "expected_type", "expected_json",
    "execution_status", "actual_result", "error_message", "evidence_reference",
    "operation",
]
ALLOWED_EXPECTED_KEYS = {
    "error", "stock", "orders", "charges", "charge_amount", "used_codes", "lines",
    "order_status", "order_id", "shipping", "discount", "total",
}
TARGETS = {
    "cart_add_sequence": "ecommerce_app.py::Cart.add",
    "shipping_calc": "ecommerce_app.py::Shipping.calculate",
    "place_sequence": "ecommerce_app.py::Checkout.place",
}


class BlockedError(Exception):
    """The test cannot be executed (bad data or failed setup). Not a product defect."""


# ----------------------------------------------------------------------------
# 1. Fixture: every call builds brand-new objects, so no test can affect another.
# ----------------------------------------------------------------------------
def build_state(fixture_key, setup):
    """Return (app, user, cart). Uses the original fixture() and adds optional overrides.

    fixture_key "empty" gives a logged-in customer with an empty cart.
    setup may contain: prices, stock, inactive, used_codes, authenticated, cart.
    """
    try:
        if fixture_key == "empty":
            app, user, _ = fixture("300k")
            cart = Cart(app.catalog)
        else:
            app, user, cart = fixture(fixture_key)
        for sku, price in setup.get("prices", {}).items():
            app.catalog.products[sku].price = D(price)
        for sku, stock in setup.get("stock", {}).items():
            app.catalog.products[sku].stock = int(stock)
        for sku in setup.get("inactive", []):
            app.catalog.products[sku].active = False
        user.used_codes.update(setup.get("used_codes", []))
        if "authenticated" in setup:
            user.authenticated = bool(setup["authenticated"])
        if "cart" in setup:
            cart = Cart(app.catalog)
            for sku, quantity in setup["cart"]:
                cart.add(sku, quantity)
    except Exception as exc:
        raise BlockedError(f"SETUP_FAILED: {type(exc).__name__}: {exc}")
    return app, user, cart


def snapshot(app, user, cart):
    """Capture every piece of state a requirement may talk about."""
    charges = app.payments.charges
    return {
        "stock": {sku: p.stock for sku, p in app.catalog.products.items()},
        "orders": len(app.orders),
        "charges": len(charges),
        "charge_amount": charges[-1]["amount"] if charges else None,
        "used_codes": sorted(user.used_codes),
        "lines": [[line.sku, line.quantity] for line in cart.lines],
    }


# ----------------------------------------------------------------------------
# 2. Operations: each one calls the real business function(s) under test.
# ----------------------------------------------------------------------------
def run_action(action):
    """Run one business call. ValueError is a business error; anything else is a crash."""
    try:
        return action(), ""
    except ValueError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"CRASH:{type(exc).__name__}:{exc}"


def op_cart_add_sequence(app, user, cart, params):
    error = ""
    for sku, quantity in params["steps"]:
        _, error = run_action(lambda: cart.add(sku, quantity))
        if error:
            break
    return {}, error


def op_shipping_calc(app, user, cart, params):
    try:
        subtotal = D(params["subtotal"])
    except Exception as exc:
        raise BlockedError(f"INVALID_TEST_DATA subtotal={params.get('subtotal')!r}: {type(exc).__name__}")
    value, error = run_action(lambda: app.shipping.calculate(subtotal, params["area"]))
    return ({} if error else {"shipping": value}), error


def op_place_sequence(app, user, cart, params):
    """Call Checkout.place() once or several times. Only the LAST call is judged;
    if an earlier call fails, the precondition is broken and the case is BLOCKED."""
    calls = params["calls"]
    observed, error = {}, ""
    for index, call in enumerate(calls):
        kwargs = {k: call[k] for k in ("area", "voucher", "method", "approved", "key") if k in call}
        order, error = run_action(lambda: app.place(user, cart, **kwargs))
        if error and index < len(calls) - 1:
            raise BlockedError(f"PRECONDITION_CALL_{index + 1}_FAILED: {error}")
        if order is not None:
            observed = {"order_id": order.order_id, "order_status": order.status,
                        "shipping": order.shipping, "discount": order.discount, "total": order.total}
    return observed, error


OPERATIONS = {
    "cart_add_sequence": op_cart_add_sequence,
    "shipping_calc": op_shipping_calc,
    "place_sequence": op_place_sequence,
}


# ----------------------------------------------------------------------------
# 3. Assertions: compare the returned error/value AND the state after the call.
# ----------------------------------------------------------------------------
def same_value(want, got):
    numeric = (int, float, Decimal)
    if (isinstance(want, numeric) and isinstance(got, numeric)
            and not isinstance(want, bool) and not isinstance(got, bool)):
        return Decimal(str(want)) == Decimal(str(got))
    return want == got


def compare(expected, observed, error, before, after):
    """Return a list of checks. A missing "error" key means: NO error is expected,
    so an unexpected exception fails the case, and a missing exception fails it too."""
    checks = []
    want_error = expected.get("error")
    got_error = error or None
    checks.append({"check": "error", "ok": want_error == got_error,
                   "expected": want_error, "actual": got_error})
    values = dict(observed)
    values.update({k: after[k] for k in ("orders", "charges", "charge_amount", "used_codes", "lines")})
    for key, want in expected.items():
        if key == "error":
            continue
        if key == "stock":
            if want == "unchanged":
                checks.append({"check": "stock", "ok": after["stock"] == before["stock"],
                               "expected": before["stock"], "actual": after["stock"]})
            else:
                actual = {sku: after["stock"].get(sku) for sku in want}
                checks.append({"check": "stock", "ok": all(same_value(v, actual[s]) for s, v in want.items()),
                               "expected": want, "actual": actual})
            continue
        got = values.get(key, "NOT_OBSERVED")
        checks.append({"check": key, "ok": same_value(want, got), "expected": want, "actual": got})
    return checks


def parse_json(row, column):
    raw = (row.get(column) or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BlockedError(f"INVALID_JSON in {column}: {exc.msg} at position {exc.pos}")
    if not isinstance(value, dict):
        raise BlockedError(f"{column} must be a JSON object")
    return value


def execute_row(row):
    """Execute one CSV row and return the row plus its result columns."""
    result = dict(row)
    started = time.perf_counter()
    checks, actual, before, after = [], {}, {}, {}
    try:
        reason = (row.get("blocked_reason") or "").strip()
        if reason:
            raise BlockedError(f"BLOCKED_BY_DESIGN: {reason}")
        inputs = parse_json(row, "input_json")
        expected = parse_json(row, "expected_json")
        unknown = set(expected) - ALLOWED_EXPECTED_KEYS
        if unknown:
            raise BlockedError(f"UNKNOWN_EXPECTED_KEYS: {sorted(unknown)}")
        operation = row.get("operation", "")
        if operation not in OPERATIONS:
            raise BlockedError(f"UNKNOWN_OPERATION: {operation!r}")
        app, user, cart = build_state(row.get("fixture_key", ""), inputs.get("setup", {}))
        before = snapshot(app, user, cart)
        observed, error = OPERATIONS[operation](app, user, cart, inputs)
        after = snapshot(app, user, cart)
        checks = compare(expected, observed, error, before, after)
        failed = [c for c in checks if not c["ok"]]
        status = FAIL if failed else PASS
        message = "; ".join(f"{c['check']}: expected {c['expected']} but got {c['actual']}" for c in failed)
        actual = {"error": error or None, **observed, **after}
    except BlockedError as exc:
        status, message = BLOCKED, str(exc)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    result.update({
        "execution_status": status,
        "actual_result": json.dumps(actual, default=str, sort_keys=True),
        "error_message": message,
        "evidence_reference": f"test_execution.csv#{row.get('test_case_id', '')} | target={TARGETS.get(row.get('operation', ''), 'n/a')}",
        "execution_time_ms": elapsed_ms,
        "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "checks_json": json.dumps(checks, default=str),
        "state_before": json.dumps(before, default=str, sort_keys=True),
        "state_after": json.dumps(after, default=str, sort_keys=True),
    })
    return result


# ----------------------------------------------------------------------------
# 4. Suite: load, validate completeness, run, report.
# ----------------------------------------------------------------------------
def count_raw_records(path):
    """Count data records straight from the file, independently of pandas."""
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def load_cases(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"MISSING_COLUMNS: {missing}")
    duplicated = df.loc[df["test_case_id"].duplicated(), "test_case_id"].tolist()
    if duplicated:
        raise ValueError(f"DUPLICATE_TEST_IDS: {duplicated}")
    return df


def load_catalog(path):
    path = Path(path)
    if not path.exists():
        return {}
    cat = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return dict(zip(cat["id"], cat["title"]))


def build_summaries(df, raw_rows):
    summary = (df.groupby(["requirement_id", "execution_status"]).size()
               .unstack(fill_value=0).reindex(columns=[PASS, FAIL, BLOCKED], fill_value=0))
    summary["total"] = summary.sum(axis=1)
    summary["pass_rate_pct"] = (100 * summary[PASS] / summary["total"]).round(1)
    cover = df.groupby("requirement_id").agg(conditions=("condition_id", "nunique"),
                                             scenarios=("scenario_id", "nunique"))
    summary = summary.join(cover).reset_index()
    counts = df["execution_status"].value_counts()
    total = len(df)
    totals = pd.DataFrame([{
        "csv_records": raw_rows,
        "executed_rows": total,
        "data_completeness": "COMPLETE" if raw_rows == total else "INCOMPLETE",
        "passed": int(counts.get(PASS, 0)),
        "failed": int(counts.get(FAIL, 0)),
        "blocked": int(counts.get(BLOCKED, 0)),
        "pass_rate_pct": round(100 * counts.get(PASS, 0) / total, 1) if total else 0.0,
        "requirements": df["requirement_id"].nunique(),
        "conditions": df["condition_id"].nunique(),
        "scenarios": df["scenario_id"].nunique(),
        "run_finished_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }])
    return summary, totals


def make_chart(summary, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.2))
    bottom = [0] * len(summary)
    for status, color in ((PASS, "#16a34a"), (FAIL, "#dc2626"), (BLOCKED, "#d97706")):
        values = summary[status].tolist()
        ax.bar(summary["requirement_id"], values, bottom=bottom, color=color, label=status)
        for x, (b, v) in enumerate(zip(bottom, values)):
            if v:
                ax.text(x, b + v / 2, str(v), ha="center", va="center", color="white", fontsize=9)
        bottom = [b + v for b, v in zip(bottom, values)]
    ax.set_title("Test results by requirement")
    ax.set_ylabel("Test cases")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def style_workbook(path):
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill
    wb = load_workbook(path)
    fills = {PASS: "C6F6D5", FAIL: "FED7D7", BLOCKED: "FEEBC8"}
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="16385E")
        for col in ws.columns:
            longest = max(len(str(c.value)) if c.value is not None else 0 for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(60, longest + 2)
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if cell.value in fills:
                    cell.fill = PatternFill("solid", fgColor=fills[cell.value])
    wb.save(path)


CSS = ("body{font:14px Arial,sans-serif;margin:30px;color:#14233c}h1{color:#17385f}"
       "table{border-collapse:collapse;width:100%;margin:12px 0}td,th{border:1px solid #cbd5e1;padding:6px 8px;"
       "text-align:left;vertical-align:top}th{background:#16385e;color:#fff}"
       ".metric{display:inline-block;margin:6px 10px 6px 0;padding:12px 18px;border-radius:10px;background:#edf3f9;font-size:20px}"
       ".PASS{background:#c6f6d5}.FAIL{background:#fed7d7}.BLOCKED{background:#feebc8}"
       "img{max-width:100%;border:1px solid #cbd5e1}code{font-size:12px}")


def write_html(df, summary, totals, out):
    t = totals.iloc[0]
    chart = base64.b64encode((out / "chart_by_requirement.png").read_bytes()).decode("ascii")
    req_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r[c]))}</td>" for c in
                         ["requirement_id", "conditions", "scenarios", "total", PASS, FAIL, BLOCKED, "pass_rate_pct"]) + "</tr>"
        for _, r in summary.iterrows())
    detail_cols = ["test_case_id", "requirement_id", "scenario_id", "test_type", "expected_json",
                   "error_message", "execution_status", "execution_time_ms"]
    detail_rows = "".join(
        "<tr>" + "".join(
            f'<td class="{html.escape(str(r[c]))}">{html.escape(str(r[c]))}</td>' if c == "execution_status"
            else f"<td>{html.escape(str(r[c]))}</td>" for c in detail_cols) + "</tr>"
        for _, r in df.iterrows())
    page = (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>EduCommerce STLab02 Test Report</title>"
            f"<style>{CSS}</style></head><body><h1>EduCommerce STLab02 - Automated Test Execution</h1>"
            f"<div class='metric'>Total: {t['executed_rows']}</div><div class='metric'>PASS: {t['passed']}</div>"
            f"<div class='metric'>FAIL: {t['failed']}</div><div class='metric'>BLOCKED: {t['blocked']}</div>"
            f"<div class='metric'>Pass rate: {t['pass_rate_pct']}%</div>"
            f"<p>Data completeness: <b>{t['data_completeness']}</b> ({t['executed_rows']} executed of {t['csv_records']} CSV records). "
            f"Finished at {t['run_finished_at_utc']} UTC.</p>"
            f"<h2>Summary by requirement</h2><table><tr><th>Requirement</th><th>Conditions</th><th>Scenarios</th>"
            f"<th>Total</th><th>PASS</th><th>FAIL</th><th>BLOCKED</th><th>Pass rate %</th></tr>{req_rows}</table>"
            f"<h2>Chart</h2><img alt='results by requirement' src='data:image/png;base64,{chart}'>"
            f"<h2>Execution details</h2><table><tr><th>Case</th><th>REQ</th><th>Scenario</th><th>Type</th>"
            f"<th>Expected</th><th>Failed checks / reason</th><th>Status</th><th>ms</th></tr>{detail_rows}</table>"
            f"</body></html>")
    (out / "test_dashboard.html").write_text(page, encoding="utf-8")


def run_suite(cases_path=None, out_dir=None, catalog_path=None):
    cases_path = Path(cases_path or ROOT / "test_cases.csv")
    out = Path(out_dir or ROOT / "reports")
    out.mkdir(parents=True, exist_ok=True)
    raw_rows = count_raw_records(cases_path)
    cases = load_cases(cases_path)
    results = [execute_row(row) for row in cases.to_dict("records")]
    df = pd.DataFrame(results)
    summary, totals = build_summaries(df, raw_rows)

    df.to_csv(out / "test_execution.csv", index=False, encoding="utf-8-sig")
    catalog = load_catalog(catalog_path or ROOT / "design_catalog.csv")
    trace = df[["requirement_id", "condition_id", "scenario_id", "test_case_id",
                "execution_status", "execution_time_ms"]].copy()
    trace.insert(2, "condition_title", trace["condition_id"].map(catalog).fillna(""))
    trace.insert(4, "scenario_title", trace["scenario_id"].map(catalog).fillna(""))
    trace = trace.rename(columns={"execution_status": "run_status"})
    with pd.ExcelWriter(out / "test_report.xlsx", engine="openpyxl") as xls:
        df.drop(columns=["checks_json"]).to_excel(xls, index=False, sheet_name="Execution")
        trace.to_excel(xls, index=False, sheet_name="Traceability")
        summary.to_excel(xls, index=False, sheet_name="SummaryByReq")
        totals.T.reset_index().rename(columns={"index": "metric", 0: "value"}).to_excel(xls, index=False, sheet_name="Summary")
    style_workbook(out / "test_report.xlsx")
    make_chart(summary, out / "chart_by_requirement.png")
    write_html(df, summary, totals, out)

    t = totals.iloc[0]
    print(f"Run finished at {t['run_finished_at_utc']} UTC | cases file: {cases_path.name}")
    print(f"Data completeness: {t['data_completeness']} ({t['executed_rows']} executed of {t['csv_records']} CSV records)")
    print(f"Executed {t['executed_rows']} | PASS {t['passed']} | FAIL {t['failed']} | BLOCKED {t['blocked']} | pass rate {t['pass_rate_pct']}%")
    print()
    print(df[["test_case_id", "requirement_id", "execution_status", "execution_time_ms"]].to_string(index=False))
    problems = df[df["execution_status"] != PASS]
    if len(problems):
        print()
        print("Non-PASS cases (expected vs actual):")
        for _, r in problems.iterrows():
            print(f"  {r['test_case_id']} [{r['execution_status']}] {r['error_message']}")
    return df, summary, totals, out


def main():
    parser = argparse.ArgumentParser(description="Run the EduCommerce data-driven test suite.")
    parser.add_argument("--cases", default=str(ROOT / "test_cases.csv"))
    parser.add_argument("--out", default=str(ROOT / "reports"))
    args = parser.parse_args()
    run_suite(args.cases, args.out)


if __name__ == "__main__":
    main()
