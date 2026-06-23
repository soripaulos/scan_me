# Copyright (c) 2025, Tushar Patel and contributors
# For license information, please see license.txt
"""Build a public-safe report-card snapshot for a Student.

The snapshot is captured at QR sign time and stored on ``Verified QR.report_card_data``
so the public ``/verify_document`` page can display a student's academic results to
guests WITHOUT granting any read permission on the locked source doctypes.

Scope is deliberately "academic + basic identity" — name, Student ID, grade/section and
all term/year results. Personal details shown on the printed card but irrelevant to a
public authenticity check (date of birth, age, gender, home address, photo) are
intentionally excluded so a leaked QR can't expose a minor's PII.

Queries mirror the ``Student Report Card - Comprehensive`` print format (doctype
``Student``) so the web page matches the paper.
"""

import frappe

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
			  custom_first_semester_remarks, custom_second_semester_remarks, custom_final_result
		   FROM `tabStudent Term Report`
		   WHERE student = %s
		   ORDER BY academic_year ASC, """
		+ _TERM_ORDER_SQL,
		(student_name,),
		as_dict=True,
	)
	years = frappe.db.sql(
		"""SELECT name, academic_year, year_average, rank_in_group
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
				"courses": _year_courses(y.name),
			}
		)

	student_name_value = frappe.db.get_value("Student", student_name, "student_name")
	# Grade/section: the print format takes it from the first term report row.
	student_group = terms[0].student_group if terms else None

	return {
		"student_name": student_name_value,
		"student_id": student_name,
		"student_group": student_group,
		"semesters": semesters,
		"year_reports": year_reports,
	}
