# Copyright (c) 2026, Tushar Patel and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class StudentReportCard(Document):
	def validate(self):
		self._fill_student_details()
		self._check_unique_per_year()

	def _fill_student_details(self):
		"""Denormalize identity fields from Student so the card is self-contained.

		The card (not the Student) is what gets QR-signed, so everything shown on the
		print/verify surface must live on this doc for tamper detection to cover it.
		"""
		if not self.student:
			return
		row = frappe.db.get_value(
			"Student",
			self.student,
			["student_name", "custom_government_student_id", "custom_school_id"],
			as_dict=True,
		)
		if not row:
			return
		self.student_name = row.student_name
		self.government_student_id = row.custom_government_student_id
		self.school_id = row.custom_school_id

	def _check_unique_per_year(self):
		"""One report card per student per academic year.

		The format autoname already enforces this at insert; this guard gives a readable
		error instead of a DuplicateEntryError and also covers renamed docs.
		"""
		existing = frappe.db.get_value(
			"Student Report Card",
			{"student": self.student, "academic_year": self.academic_year, "name": ("!=", self.name)},
			"name",
		)
		if existing:
			frappe.throw(
				frappe._("A report card for {0} in {1} already exists: {2}").format(
					self.student, self.academic_year, existing
				)
			)
