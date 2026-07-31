# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Build a public-safe report-card snapshot for a Student.

The snapshot is captured at QR sign time and stored on ``Verified QR.report_card_data``
so the public ``/verify_document`` page can display a student's academic results to
guests WITHOUT granting any read permission on the locked source doctypes.

Scope is deliberately "academic + basic identity" — name, Student ID, government ID,
grade/section and all term/year results. Personal details shown on the printed card
but irrelevant to a public authenticity check (date of birth, age, gender, home
address, photo) are intentionally excluded so a leaked QR can't expose a minor's PII.

Queries mirror the ``Student Report Card - Comprehensive`` print format (doctype
``Student``) so the web page matches the paper.
"""

import frappe
from frappe.utils import flt


def build_transcript_doc_snapshot(tc):
	"""Snapshot a ``Student Transcript`` doc for ``Verified QR.report_card_data``.

	Distinct ``type`` so the verify page can tell a multi-year transcript from a
	single report card and render it accordingly. Reads only the signed transcript,
	so the snapshot and the tamper hash cover the same data.
	"""
	years = []
	for yr in tc.get("years") or []:
		subs = [r for r in (tc.get("subjects") or []) if r.year_label == yr.year_label]
		firsts = [flt(r.first_sem) for r in subs]
		seconds = [flt(r.second_sem) for r in subs]
		avgs = [flt(r.average) for r in subs]
		count = len(subs)
		years.append(
			{
				"grade": yr.grade,
				"academic_year": yr.academic_year,
				"is_current": 1 if yr.is_current else 0,
				"conduct": {
					"first": yr.conduct_first,
					"second": yr.conduct_second,
					"average": yr.conduct_average,
				},
				"rank": {
					"first": yr.rank_first,
					"second": yr.rank_second,
					"average": yr.rank_average,
				},
				"subjects": [
					{
						"subject": r.subject,
						"first_sem": r.first_sem,
						"second_sem": r.second_sem,
						"average": r.average,
					}
					for r in subs
				],
				"total": {
					"first": round(sum(firsts), 2),
					"second": round(sum(seconds), 2),
					"average": round(sum(avgs), 2),
				}
				if count
				else None,
				"average_pct": {
					"first": round(sum(firsts) / count, 2),
					"second": round(sum(seconds) / count, 2),
					"average": round(sum(avgs) / count, 2),
				}
				if count
				else None,
			}
		)

	if not years:
		return None

	return {
		"type": "transcript",
		"student_name": tc.student_name,
		"student_id": tc.student,
		"government_student_id": tc.government_student_id or None,
		"current_grade": tc.current_grade,
		"current_academic_year": tc.current_academic_year,
		"behavior": tc.behavior,
		"years": years,
	}


def build_report_card_doc_snapshot(card):
	"""Snapshot a ``Student Report Card`` doc for ``Verified QR.report_card_data``.

	Same output shape as :func:`build_student_report_card_snapshot` so the public
	verify page renders both without any JS changes. Unlike the Student variant this
	reads only the signed card itself — the snapshot and the tamper hash therefore
	cover exactly the same data.
	"""
	from scan_me.utils.report_card_generator import YEAR_PERIOD

	def courses_for(period):
		return [
			{
				"course": r.course,
				"score": r.score,
				"maximum": r.max_score,
				"percentage": r.percentage,
			}
			for r in (card.get("scores") or [])
			if r.period == period
		]

	semesters = [
		{
			"academic_year": card.academic_year,
			"academic_term": s.academic_term,
			"term_average": s.term_average,
			"rank_in_group": s.rank_in_group,
			"remark": s.remark or None,
			"first_semester_remarks": s.first_semester_remarks,
			"second_semester_remarks": s.second_semester_remarks,
			"final_result": s.final_result,
			"courses": courses_for(s.academic_term),
		}
		for s in (card.get("semesters") or [])
	]

	year_courses = courses_for(YEAR_PERIOD)
	year_reports = []
	if card.year_average or year_courses:
		year_reports.append(
			{
				"academic_year": card.academic_year,
				"year_average": card.year_average,
				"rank_in_group": card.year_rank,
				"remark": card.year_remark or None,
				"courses": year_courses,
			}
		)

	if not semesters and not year_reports:
		return None

	return {
		"student_name": card.student_name,
		"student_id": card.student,
		"government_student_id": card.government_student_id or None,
		"student_group": card.student_group,
		"academic_year": card.academic_year,
		"semesters": semesters,
		"year_reports": year_reports,
	}


# Semester display order — matches the print format's CASE ordering.
_TERM_ORDER_SQL = (
	"CASE academic_term WHEN 'First Semester' THEN 1 WHEN 'Second Semester' THEN 2 ELSE 3 END ASC"
)


def _term_courses(term_name):
	rows = frappe.db.sql(
		"""SELECT course, total_score_for_term, total_maximum_score, percentage
		   FROM `tabCourse Term Summary`
		   WHERE parent = %s AND parenttype = 'Student Term Report'
		   ORDER BY idx ASC""",
		(term_name,),
		as_dict=True,
	)
	return [
		{
			"course": r.course,
			"score": r.total_score_for_term,
			"maximum": r.total_maximum_score,
			"percentage": r.percentage,
		}
		for r in rows
	]


def _year_courses(year_name):
	rows = frappe.db.sql(
		"""SELECT course, total_year_score, total_year_max_score, year_average_percentage
		   FROM `tabCourse Year Summary`
		   WHERE parent = %s AND parenttype = 'Student Year Report'
		   ORDER BY idx ASC""",
		(year_name,),
		as_dict=True,
	)
	return [
		{
			"course": r.course,
			"score": r.total_year_score,
			"maximum": r.total_year_max_score,
			"percentage": r.year_average_percentage,
		}
		for r in rows
	]


def build_student_report_card_snapshot(student_name):
	"""Return a dict snapshot of a Student's academic record, or ``None``.

	``None`` is returned when the student has neither a term nor a year report — there's
	nothing to verify, so no snapshot is stored. Raising is left to the caller's
	try/except; this function reads only via parameterised SQL.
	"""
	terms = frappe.db.sql(
		"""SELECT name, academic_year, academic_term, term_average, rank_in_group, student_group,
			  custom_first_semester_remarks, custom_second_semester_remarks, custom_final_result,
			  custom_remark
		   FROM `tabStudent Term Report`
		   WHERE student = %s
		   ORDER BY academic_year ASC, """
		+ _TERM_ORDER_SQL,
		(student_name,),
		as_dict=True,
	)
	years = frappe.db.sql(
		"""SELECT name, academic_year, year_average, rank_in_group, custom_remark
		   FROM `tabStudent Year Report`
		   WHERE student = %s
		   ORDER BY academic_year ASC""",
		(student_name,),
		as_dict=True,
	)

	if not terms and not years:
		return None

	semesters = []
	for t in terms:
		semesters.append(
			{
				"academic_year": t.academic_year,
				"academic_term": t.academic_term,
				"term_average": t.term_average,
				"rank_in_group": t.rank_in_group,
				"remark": t.custom_remark or None,
				"first_semester_remarks": t.custom_first_semester_remarks,
				"second_semester_remarks": t.custom_second_semester_remarks,
				"final_result": t.custom_final_result,
				"courses": _term_courses(t.name),
			}
		)

	year_reports = []
	for y in years:
		year_reports.append(
			{
				"academic_year": y.academic_year,
				"year_average": y.year_average,
				"rank_in_group": y.rank_in_group,
				"remark": y.custom_remark or None,
				"courses": _year_courses(y.name),
			}
		)

	student_row = frappe.db.get_value(
		"Student",
		student_name,
		["student_name", "custom_government_student_id"],
		as_dict=True,
	)
	# Grade/section: the print format takes it from the first term report row.
	student_group = terms[0].student_group if terms else None

	return {
		"student_name": student_row.student_name if student_row else None,
		"student_id": student_name,
		"government_student_id": (student_row.custom_government_student_id or None) if student_row else None,
		"student_group": student_group,
		"semesters": semesters,
		"year_reports": year_reports,
	}
