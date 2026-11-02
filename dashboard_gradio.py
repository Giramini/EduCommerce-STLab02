"""Gradio dashboard: result chart and detail table side by side.

Run test_runner.py first (it writes reports/test_execution.csv), then:
    pip install gradio
    python dashboard_gradio.py
Do not publish real customer data through the temporary share link.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPORT_CSV = Path(__file__).resolve().parent / "reports" / "test_execution.csv"
STATUSES = ["PASS", "FAIL", "BLOCKED"]
COLORS = ["#16a34a", "#dc2626", "#d97706"]
TABLE_COLUMNS = ["test_case_id", "requirement_id", "scenario_id", "expected_json", "error_message", "execution_status"]


def load_report():
    return pd.read_csv(REPORT_CSV, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def dashboard_view(req="ALL", status="ALL", report=None):
    df = (load_report() if report is None else report).copy()
    if req != "ALL":
        df = df[df["requirement_id"] == req]
    if status != "ALL":
        df = df[df["execution_status"] == status]
    counts = df["execution_status"].value_counts().reindex(STATUSES, fill_value=0)
    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(counts.index, counts.values, color=COLORS)
    ax.bar_label(bars, padding=3)
    ax.set_title("Test execution results")
    ax.set_ylabel("Test cases")
    ax.set_ylim(0, max(2, int(counts.max()) + 2))
    fig.tight_layout()
    line = f"Executed: {len(df)} | PASS: {counts['PASS']} | FAIL: {counts['FAIL']} | BLOCKED: {counts['BLOCKED']}"
    return fig, df[TABLE_COLUMNS], line


def build_demo():
    import gradio as gr
    report = load_report()
    with gr.Blocks(title="EduCommerce - STLab02 Test Dashboard") as demo:
        gr.Markdown("# EduCommerce - Requirement Traceability and Test Results")
        with gr.Row():
            req_filter = gr.Dropdown(["ALL"] + sorted(report["requirement_id"].unique().tolist()), value="ALL", label="Requirement")
            status_filter = gr.Dropdown(["ALL"] + STATUSES, value="ALL", label="Test status")
        status_line = gr.Markdown()
        with gr.Row(equal_height=True):
            with gr.Column(scale=1, min_width=300):
                chart = gr.Plot(label="Result distribution")
            with gr.Column(scale=2, min_width=420):
                table = gr.Dataframe(label="Test execution details", interactive=False, wrap=True)
        gr.File(value=str(REPORT_CSV.parent / "test_report.xlsx"), label="Download Excel report")
        outputs = [chart, table, status_line]
        req_filter.change(dashboard_view, [req_filter, status_filter], outputs)
        status_filter.change(dashboard_view, [req_filter, status_filter], outputs)
        demo.load(dashboard_view, [req_filter, status_filter], outputs)
    return demo


if __name__ == "__main__":
    build_demo().launch(share=True, debug=False)
