"""Retest helper: applies the proposed fix for DEF-001 to a TEMPORARY copy of the app
(the real ecommerce_app.py is never modified) and re-runs the whole suite.

Run:  python verify_fix.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OLD = "        payment_state=self.payments.collect(total,method,approved,key)\n"
NEW = ("        try:\n"
       "            payment_state=self.payments.collect(total,method,approved,key)\n"
       "        except ValueError:\n"
       "            self.inventory.release(cart.lines)\n"
       "            raise\n")

source = (ROOT / "ecommerce_app.py").read_text(encoding="utf-8")
assert source.count(OLD) == 1, "unexpected application source"
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "ecommerce_app.py").write_text(source.replace(OLD, NEW), encoding="utf-8")
    for name in ("test_runner.py", "test_cases.csv", "design_catalog.csv"):
        shutil.copy(ROOT / name, tmp / name)
    done = subprocess.run([sys.executable, "test_runner.py", "--out", "out"], cwd=tmp, capture_output=True, text=True, check=True)
    print("\n".join(done.stdout.splitlines()[:3]))
    after = pd.read_csv(tmp / "out" / "test_execution.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    print("REQ-16 after fix:", after[after.requirement_id == "REQ-16"].set_index("test_case_id")["execution_status"].to_dict())
    before = pd.read_csv(ROOT / "reports" / "test_execution.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    merged = before.merge(after, on="test_case_id", suffixes=("_before", "_after"))
    regress = merged[(merged.execution_status_before == "PASS") & (merged.execution_status_after != "PASS")]
    print("Cases that were PASS before and are not PASS after the fix (regression):", regress.test_case_id.tolist())
