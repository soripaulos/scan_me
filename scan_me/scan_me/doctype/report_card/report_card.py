# Report Card controller — auto-populate student name from linked Student
import frappe


def autoname(self):
    # name = {student} - {academic_year}, e.g. "STR-00042 - 2018 E.C."
    if self.student and self.academic_year:
        student_name = self.student_name or ""
        suffix = f" - {self.academic_year}"
        if student_name:
            self.name = f"{self.student}{suffix}"
        else:
            self.name = self.student


def validate(self):
    if self.student:
        # Auto-fill name from Student doctype
        try:
            student_doc = frappe.get_doc("Student", self.student)
            self.student_name = student_doc.get("student_name", "")
            if not self.student_group:
                self.student_group = student_doc.get("student_group", "")
        except Exception:
            pass