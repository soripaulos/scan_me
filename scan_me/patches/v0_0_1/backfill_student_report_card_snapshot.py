# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Backfill report_card_data on existing Student Verified QRs.

QRs signed before the Student snapshot capture existed have an empty
``report_card_data`` field, so the public verify page shows only the date. This
populates them from the current academic records so they display immediately.
``update_modified=False`` keeps the content hash / tamper state untouched.
"""

import frappe

from scan_me.utils.report_card_snapshot import build_student_report_card_snapshot


def execute():
	rows = frappe.get_all(
		"Verified QR",
		filters={
			"ref_doctype": "Student",
			"report_card_data": ["in", [None, ""]],
		},
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
