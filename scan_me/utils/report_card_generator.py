# Copyright (c) 2026, Tushar Patel and contributors
# For license information, please see license.txt
"""Bulk-generate Student Report Card docs from submitted Education results.

One ``Student Report Card`` exists per student per academic year and is kept in
sync with the submitted ``Student Term Report`` / ``Student Year Report`` records.
Because the card itself is the QR-signed document, its content hash covers the
actual academic data — regenerating a card after results change flips any
previously signed QR to "tampered" until the card is signed again, which is the
intended audit trail.

Sync is idempotent and cheap to re-run: each card stores a fingerprint of the
source data it was built from, and unchanged cards are skipped entirely (no
save, no ``modified`` bump), so valid signatures stay valid across runs.

Entry points:
- ``scheduled_sync``            — daily scheduler hook.
- ``enqueue_sync``              — whitelisted manual trigger (background job).
- ``refresh_report_card``       — whitelisted single-card rebuild (form button).
- ``bulk_generate_qr``          — whitelisted Verified QR generation for selected cards.
"""

import hashlib
import json

import frappe

YEAR_PERIOD = "Year"

def _term_rank(academic_term):
	"""Display order for a term label. Labels look like '2018 E.C. (First Semester)',
	so match by substring rather than exact value; unknown labels sort last."""
	label = (academic_term or "").lower()
	if "first" in label:
		return 1
	if "second" in label:
		return 2
	return 99


def _term_sort_key(term_row):
	return (_term_rank(term_row.get("academic_term")), term_row.get("academic_term") or "")


def _dedupe_terms(terms):
	"""Keep only the most recently modified submitted report per (student, year, term).

	Duplicate submissions exist in the wild (same student+year+term twice); without
	this, a card would list the same semester twice and double its scores.
	"""
	latest = {}
	for t in terms:
		key = (t.student, t.academic_year, t.academic_term)
		if key not in latest or str(t.modified or "") > str(latest[key].modified or ""):
			latest[key] = t
	return list(latest.values())


def _fetch_source_rows(academic_year=None, students=None):
	"""Bulk-load submitted term/year reports and their course child rows."""
	filters = {"docstatus": 1}
	if academic_year:
		filters["academic_year"] = academic_year
	if students:
		filters["student"] = ("in", students)

	terms = frappe.get_all(
		"Student Term Report",
		filters=filters,
		fields=[
			"name",
			"student",
			"academic_year",
			"academic_term",
			"term_average",
			"rank_in_group",
			"student_group",
			"custom_first_semester_remarks",
			"custom_second_semester_remarks",
			"custom_final_result",
			"custom_remark",
			"modified",
		],
	)
	terms = _dedupe_terms(terms)
	years = frappe.get_all(
		"Student Year Report",
		filters=filters,
		fields=[
			"name",
			"student",
			"academic_year",
			"year_average",
			"rank_in_group",
			"student_group",
			"custom_remark",
		],
	)

	term_courses = {}
	if terms:
		rows = frappe.get_all(
			"Course Term Summary",
			filters={"parenttype": "Student Term Report", "parent": ("in", [t.name for t in terms])},
			fields=["parent", "course", "total_score_for_term", "total_maximum_score", "percentage"],
			order_by="parent, idx",
		)
		for r in rows:
			term_courses.setdefault(r.parent, []).append(r)

	year_courses = {}
	if years:
		rows = frappe.get_all(
			"Course Year Summary",
			filters={"parenttype": "Student Year Report", "parent": ("in", [y.name for y in years])},
			fields=["parent", "course", "total_year_score", "total_year_max_score", "year_average_percentage"],
			order_by="parent, idx",
		)
		for r in rows:
			year_courses.setdefault(r.parent, []).append(r)

	return terms, years, term_courses, year_courses


def build_payloads(academic_year=None, students=None):
	"""Return ``{(student, academic_year): payload}`` for every student with results.

	The payload mirrors the Student Report Card field layout: parent scalars plus
	``semesters`` and ``scores`` child-row lists.
	"""
	terms, years, term_courses, year_courses = _fetch_source_rows(academic_year, students)

	payloads = {}

	def entry(student, year):
		return payloads.setdefault(
			(student, year),
			{
				"student": student,
				"academic_year": year,
				"student_group": None,
				"year_average": None,
				"year_rank": None,
				"year_remark": None,
				"semesters": [],
				"scores": [],
			},
		)

	for t in sorted(terms, key=_term_sort_key):
		p = entry(t.student, t.academic_year)
		p["student_group"] = p["student_group"] or t.student_group
		p["semesters"].append(
			{
				"academic_term": t.academic_term,
				"term_average": t.term_average,
				"rank_in_group": t.rank_in_group,
				"remark": t.custom_remark,
				"first_semester_remarks": t.custom_first_semester_remarks,
				"second_semester_remarks": t.custom_second_semester_remarks,
				"final_result": t.custom_final_result,
				"source_report": t.name,
			}
		)
		for c in term_courses.get(t.name, []):
			p["scores"].append(
				{
					"period": t.academic_term,
					"course": c.course,
					"score": c.total_score_for_term,
					"max_score": c.total_maximum_score,
					"percentage": c.percentage,
				}
			)

	for y in years:
		p = entry(y.student, y.academic_year)
		p["student_group"] = p["student_group"] or y.student_group
		p["year_average"] = y.year_average
		p["year_rank"] = y.rank_in_group
		p["year_remark"] = y.custom_remark
		for c in year_courses.get(y.name, []):
			p["scores"].append(
				{
					"period": YEAR_PERIOD,
					"course": c.course,
					"score": c.total_year_score,
					"max_score": c.total_year_max_score,
					"percentage": c.year_average_percentage,
				}
			)

	return payloads


def _fingerprint(payload):
	"""Stable hash of the source data a card was built from (skip-if-unchanged)."""
	return hashlib.sha256(
		json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
	).hexdigest()


def _apply_payload(doc, payload, fingerprint):
	doc.student = payload["student"]
	doc.academic_year = payload["academic_year"]
	doc.student_group = payload["student_group"]
	doc.year_average = payload["year_average"]
	doc.year_rank = payload["year_rank"]
	doc.year_remark = payload["year_remark"]
	doc.set("semesters", payload["semesters"])
	doc.set("scores", payload["scores"])
	doc.last_generated_on = frappe.utils.now()
	doc.source_fingerprint = fingerprint


def sync_report_cards(academic_year=None, students=None):
	"""Upsert Student Report Cards from submitted results. Returns a summary dict.

	Runs with ignore_permissions: callers are gated (scheduler, or the whitelisted
	wrappers below which check roles/permissions first).
	"""
	payloads = build_payloads(academic_year, students)

	existing = {
		(r.student, r.academic_year): r
		for r in frappe.get_all(
			"Student Report Card",
			fields=["name", "student", "academic_year", "source_fingerprint"],
		)
	}

	summary = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}
	for key, payload in payloads.items():
		fingerprint = _fingerprint(payload)
		current = existing.get(key)
		try:
			if current:
				if current.source_fingerprint == fingerprint:
					# No source change: don't touch the doc, so signed QRs stay valid.
					summary["unchanged"] += 1
					continue
				doc = frappe.get_doc("Student Report Card", current.name)
				_apply_payload(doc, payload, fingerprint)
				doc.save(ignore_permissions=True)
				summary["updated"] += 1
			else:
				doc = frappe.new_doc("Student Report Card")
				_apply_payload(doc, payload, fingerprint)
				doc.insert(ignore_permissions=True)
				summary["created"] += 1
		except Exception:
			frappe.db.rollback()
			summary["errors"].append({"student": key[0], "academic_year": key[1]})
			frappe.log_error(
				title="Student Report Card sync failed",
				message=f"student={key[0]} academic_year={key[1]}\n{frappe.get_traceback()}",
			)
			continue
		if (summary["created"] + summary["updated"]) % 100 == 0:
			frappe.db.commit()

	frappe.db.commit()
	return summary


def scheduled_sync():
	"""Daily scheduler entry point. No-op on sites without the Education doctypes."""
	if not frappe.db.table_exists("Student Term Report"):
		return
	summary = sync_report_cards()
	if summary["created"] or summary["updated"] or summary["errors"]:
		frappe.logger("scan_me").info(f"Student Report Card sync: {summary}")


@frappe.whitelist()
def enqueue_sync(academic_year=None):
	"""Manual trigger: rebuild all report cards (optionally one academic year) in the background."""
	frappe.only_for(("System Manager", "Academics User"))
	frappe.enqueue(
		"scan_me.utils.report_card_generator.sync_report_cards",
		queue="long",
		timeout=3600,
		job_id="scan_me_report_card_sync",
		deduplicate=True,
		academic_year=academic_year or None,
	)
	return {"message": "Report card generation started in the background."}


@frappe.whitelist()
def refresh_report_card(name):
	"""Rebuild a single card from its student's submitted results (form button)."""
	doc = frappe.get_doc("Student Report Card", name)
	if not doc.has_permission("write"):
		frappe.throw(frappe._("Not permitted to update this report card."), frappe.PermissionError)

	summary = sync_report_cards(academic_year=doc.academic_year, students=[doc.student])
	return summary


@frappe.whitelist()
def bulk_generate_qr(names, resign=0):
	"""Generate Verified QRs for the given Student Report Cards.

	``resign=1`` (System Manager only) first deletes existing QRs for a card whose
	content changed since signing, so an updated card can be re-signed in one pass.
	Per-card failures are collected, not raised, so one bad card doesn't stop the run.
	"""
	from scan_me.utils.generate_qr import generate_verified_qr

	if isinstance(names, str):
		names = frappe.parse_json(names)
	resign = frappe.utils.cint(resign)
	if resign:
		frappe.only_for("System Manager")

	summary = {"created": 0, "existing": 0, "resigned": 0, "errors": []}
	for name in names or []:
		try:
			if resign:
				old_qrs = frappe.get_all(
					"Verified QR",
					filters={"ref_doctype": "Student Report Card", "ref_docname": name},
					pluck="name",
				)
				if old_qrs:
					for qr_name in old_qrs:
						frappe.delete_doc("Verified QR", qr_name, ignore_permissions=True, force=True)
					summary["resigned"] += 1

			result = generate_verified_qr("Student Report Card", name)
			if result.get("existing"):
				summary["existing"] += 1
			else:
				summary["created"] += 1
		except Exception as e:
			summary["errors"].append({"name": name, "error": str(e)})

	frappe.db.commit()
	return summary
