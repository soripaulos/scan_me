# Copyright (c) 2026, Tushar Patel and contributors
# License: MIT
import frappe
from frappe import _


@frappe.whitelist()
def get_academic_year():
    """Return the configured academic year from Scan Me Settings, or default."""
    try:
        year = frappe.db.get_single_value("Scan Me Settings", "default_academic_year")
        return year or "2018 E.C."
    except Exception:
        return "2018 E.C."


@frappe.whitelist()
def get_student_groups():
    """Return distinct student groups from Student doctype."""
    try:
        groups = frappe.db.sql_list("""
            SELECT DISTINCT student_group
            FROM tabStudent
            WHERE student_group IS NOT NULL AND student_group != ''
            ORDER BY student_group
        """)
        return groups
    except Exception:
        return []


@frappe.whitelist()
def get_students(student_group):
    """Return students in a given group."""
    try:
        students = frappe.get_list(
            "Student",
            filters={"student_group": student_group},
            fields=["name", "student_name", "student_group"],
            order_by="student_name",
        )
        return [s.as_dict() for s in students]
    except Exception:
        return []


@frappe.whitelist()
def create_report_card(student, academic_year):
    """Generate or update a Report Card for a student and auto-create Verified QR."""
    student_doc = frappe.get_doc("Student", student)

    # Check if Report Card already exists for this student+year
    existing = frappe.db.get_value(
        "Report Card",
        {"student": student, "academic_year": academic_year},
        "name",
    )
    if existing:
        # Delete and recreate to refresh data
        frappe.delete_doc("Report Card", existing, force=True, ignore_permissions=True)

    # Gather Student Term Reports for both semesters
    strs = frappe.get_all(
        "Student Term Report",
        filters={
            "student": student,
            "academic_year": academic_year,
        },
        fields=["name", "academic_term", "student_name", "student_group",
                "term_average", "rank_in_group", "custom_first_semester_remarks",
                "custom_second_semester_remarks", "custom_final_result"],
        order_by="academic_term",
    )

    semester_reports = []
    for str_doc in strs:
        # Get course data from child table
        courses = []
        str_details = frappe.get_doc("Student Term Report", str_doc.name)
        for row in (str_details.get("course_summary") or []):
            courses.append({
                "doctype": "Report Card Course",
                "course": row.get("course"),
                "score": row.get("total_score_for_term"),
                "maximum": row.get("total_maximum_score"),
                "percentage": row.get("percentage"),
            })

        term_label = str_doc.get("academic_term") or "First Semester"
        promotion = str_doc.get("custom_final_result", "")

        semester_reports.append({
            "doctype": "Report Card Semester",
            "academic_term": term_label,
            "term_average": str_doc.get("term_average"),
            "rank_in_group": str_doc.get("rank_in_group"),
            "promotion_decision": promotion,
            "first_semester_remarks": str_doc.get("custom_first_semester_remarks", "")
                                   if term_label == "First Semester" else "",
            "second_semester_remarks": str_doc.get("custom_second_semester_remarks", "")
                                     if term_label == "Second Semester" else "",
            "courses": courses,
        })

    # Gather Student Year Reports if they exist
    year_reports = []
    syrs = frappe.get_all(
        "Student Year Report",
        filters={"student": student, "academic_year": academic_year},
        fields=["name", "year_average", "rank_in_group"],
        order_by="creation",
    )
    for syr_doc in syrs:
        year_courses = []
        syr_details = frappe.get_doc("Student Year Report", syr_doc.name)
        for row in (syr_details.get("course_summary") or []):
            year_courses.append({
                "doctype": "Report Card Course",
                "course": row.get("course"),
                "score": row.get("total_score_for_year"),
                "maximum": row.get("total_maximum_score_year"),
                "percentage": row.get("percentage"),
            })
        year_reports.append({
            "doctype": "Report Card Year",
            "year_average": syr_doc.get("year_average"),
            "rank_in_group": syr_doc.get("rank_in_group"),
            "courses": year_courses,
        })

    # Create the Report Card document
    report_card = frappe.get_doc({
        "doctype": "Report Card",
        "student": student,
        "academic_year": academic_year,
        "student_name": student_doc.get("student_name", ""),
        "student_group": student_doc.get("student_group", ""),
        "photo": student_doc.get("photo", ""),
        "is_final": True if len(year_reports) > 0 else False,
        "semester_reports": semester_reports,
        "year_reports": year_reports,
    })
    report_card.insert(ignore_permissions=True)
    report_card_name = report_card.name

    # Auto-create Verified QR for the Report Card
    qr_result = None
    try:
        from scan_me.utils.generate_qr import generate_verified_qr
        qr_result = generate_verified_qr("Report Card", report_card_name)
    except Exception as e:
        # Log but don't fail the whole operation
        frappe.log_error(f"Failed to create Verified QR for Report Card {report_card_name}: {e}", "Report Card Generator")

    return {
        "report_card_name": report_card_name,
        "student_name": student_doc.get("student_name", student),
        "qr_created": qr_result.get("unique_id") if qr_result else None,
        "semesters_found": len(semester_reports),
        "years_found": len(year_reports),
    }