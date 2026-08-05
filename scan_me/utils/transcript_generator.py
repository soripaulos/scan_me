# Copyright (c) 2026, Tushar Patel and contributors
# For license information, please see license.txt
"""Populate a Student Transcript's *current* year from official results.

A transcript spans several academic years. Previous years are typed in by hand
(older results may predate the system), but the current year is pulled from the
submitted ``Student Term Report`` / ``Student Year Report`` records so it matches
the official record and cannot drift. Only the current year is fetched; manually
entered previous years are left untouched.

The current-year rows carry ``is_current = 1`` on the Years table so the form can
show them read-only and re-running this simply refreshes them.
"""

import frappe

from scan_me.utils.report_card_generator import (
	FIRST_SEMESTER,
	SECOND_SEMESTER,
	YEAR_PERIOD,
	build_payloads,
)


def _pivot_subjects(scores):
	"""Turn flat period/score rows into per-subject {first_sem, second_sem, average}."""
	order = []
	by_course = {}
	for sc in scores:
		course = sc.get("course")
		if course not in by_course:
			by_course[course] = {"first_sem": None, "second_sem": None, "average": None}
			order.append(course)
		if sc.get("period") == FIRST_SEMESTER:
			by_course[course]["first_sem"] = sc.get("score")
		elif sc.get("period") == SECOND_SEMESTER:
			by_course[course]["second_sem"] = sc.get("score")
		elif sc.get("period") == YEAR_PERIOD:
			by_course[course]["average"] = sc.get("percentage")
	return order, by_course


@frappe.whitelist()
def fetch_current_year(name):
	"""Fill the current academic year of a Student Transcript from official results.

	Replaces any existing current-year rows (and their subjects); leaves manually
	entered previous years alone. Returns a short summary for the UI.
	"""
	tc = frappe.get_doc("Student Transcript", name)
	if not tc.has_permission("write"):
		frappe.throw(frappe._("Not permitted to update this transcript."), frappe.PermissionError)
	if not tc.current_academic_year:
		frappe.throw(frappe._("Set the Current Academic Year first."))

	year = tc.current_academic_year
	payloads = build_payloads(academic_year=year, students=[tc.student])
	payload = payloads.get((tc.student, year))
	if not payload:
		frappe.throw(
			frappe._("No submitted term or year results found for {0} in {1}.").format(tc.student, year)
		)

	# Identity from the Student record (kept on the transcript so it is self-contained).
	srow = frappe.db.get_value(
		"Student",
		tc.student,
		["student_name", "custom_government_student_id", "custom_school_id", "gender", "age"],
		as_dict=True,
	)
	if srow:
		tc.student_name = srow.student_name
		tc.government_student_id = srow.custom_government_student_id
		tc.school_id = srow.custom_school_id
		tc.gender = srow.gender
		tc.age = str(srow.age) if srow.age is not None else None

	grade = payload.get("student_group") or tc.current_grade
	label = "{0} ({1})".format(grade, year) if grade else str(year)

	# Drop the previous current-year rows (by flag) and this label's rows, then rebuild.
	stale_labels = {r.year_label for r in (tc.years or []) if r.is_current}
	stale_labels.add(label)
	tc.set("years", [r for r in (tc.years or []) if not r.is_current and r.year_label != label])
	tc.set("subjects", [r for r in (tc.subjects or []) if r.year_label not in stale_labels])

	sem_by_term = {s.get("academic_term"): s for s in payload.get("semesters", [])}
	sem1 = sem_by_term.get(FIRST_SEMESTER)
	sem2 = sem_by_term.get(SECOND_SEMESTER)

	def _rank(sem, key="rank_in_group"):
		return str(sem[key]) if sem and sem.get(key) else None

	tc.append(
		"years",
		{
			"year_label": label,
			"grade": grade,
			"academic_year": year,
			"is_current": 1,
			"rank_first": _rank(sem1),
			"rank_second": _rank(sem2),
			"rank_average": str(payload["year_rank"]) if payload.get("year_rank") else None,
		},
	)

	order, by_course = _pivot_subjects(payload.get("scores", []))
	for course in order:
		vals = by_course[course]
		avg = vals["average"]
		if avg is None:
			fs, ss = vals["first_sem"], vals["second_sem"]
			if fs is not None and ss is not None:
				avg = round((float(fs) + float(ss)) / 2, 2)
			else:
				avg = fs if fs is not None else ss
		tc.append(
			"subjects",
			{
				"year_label": label,
				"subject": course,
				"first_sem": vals["first_sem"],
				"second_sem": vals["second_sem"],
				"average": avg,
			},
		)

	if not tc.current_grade:
		tc.current_grade = grade
	tc.last_generated_on = frappe.utils.now()
	tc.save()

	return {
		"message": frappe._("Fetched {0} subjects for {1}.").format(len(order), label),
		"year_label": label,
		"subjects": len(order),
	}
