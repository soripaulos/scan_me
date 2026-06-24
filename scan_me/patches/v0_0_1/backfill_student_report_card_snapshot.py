# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Backfill/refresh report_card_data on all Student Verified QRs.

Re-runs for every Student-type Verified QR so new snapshot fields (government_student_id,
per-term/year remark) are populated retroactively. ``update_modified=False`` keeps the
content hash and tamper-detection state untouched.
"""

import frappe

from scan_me.utils.report_card_snapshot import build_student_report_card_snapshot


def execute():
	rows = frappe.get_all(
		"Verified QR",
		filters={"ref_doctype": "Student"},
		fields=["name", "ref_docname"],
	)
	for row in rows:
		try:
			snapshot = build_student_report_card_snapshot(row.ref_docname)
		except Exception:
			snapshot = None
		if not snapshot:
			continue
		frappe.db.set_value(
			"Verified QR",
			row.name,
			"report_card_data",
			frappe.as_json(snapshot),
			update_modified=False,
		)
	frappe.db.commit()
