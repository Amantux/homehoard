"""Home-inventory report: a valuation + insurance summary over the household's
items, using the value / insured / warranty data already on each item.

`GET /reports`               — index of the registered reports (id + title).
`GET /reports/<id>`           — one registered report (summary + breakdowns + items).
`GET /reports/inventory.csv` — the item rows as CSV (for a spreadsheet / insurer).

Read-only and group-scoped. Value is the DOCUMENTED value (purchase price ×
quantity) — the data we actually hold; no depreciation/replacement is invented.

The report itself — payload construction, valuation, warranty and group scoping —
is registered as the ``inventory`` spec in :mod:`app.api.reports_registry`; this
module is the HTTP layer and delegates to it.
"""
import csv
import io

from flask import Blueprint, Response, abort, jsonify

from ..auth import current_group, login_required
from ..extensions import db
from ..services.csv_io import _csv_safe
from .reports_registry import REPORTS, ReportSpec


bp = Blueprint("reports", __name__)


def _spec(report_id: str) -> ReportSpec:
    for spec in REPORTS:
        if spec.id == report_id:
            return spec
    abort(404, description=f"Unknown report: {report_id}")


@bp.get("/reports")
@login_required
def reports_index():
    """Index of the registered reports: one ``{"id", "title"}`` entry each."""
    return jsonify([{"id": spec.id, "title": spec.title} for spec in REPORTS])


@bp.get("/reports/<report_id>")
@login_required
def report(report_id):
    """One registered report by id, or 404 when the id is not registered."""
    spec = _spec(report_id)
    group = current_group()
    return jsonify(spec.build(db, group.id))


@bp.get("/reports/inventory")
@login_required
def inventory_report():
    group = current_group()
    return jsonify(_spec("inventory").build(db, group.id))


@bp.get("/reports/inventory.csv")
@login_required
def inventory_report_csv():
    spec = _spec("inventory")
    group = current_group()
    payload = spec.build(db, group.id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(spec.csv_columns)
    for r in payload["items"]:
        # Neutralize spreadsheet formula injection on the free-text cells (CWE-1236).
        w.writerow([_csv_safe(r["name"]), _csv_safe(r["location"]),
                    _csv_safe("; ".join(r["labels"])), _csv_safe(r["serialNumber"]),
                    _csv_safe(r["purchaseFrom"]), r["purchaseDate"] or "",
                    r["purchasePrice"], r["quantity"], r["lineValue"],
                    "yes" if r["insured"] else "no", r["warrantyStatus"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":
                             'attachment; filename="homehoard-inventory-report.csv"'})
