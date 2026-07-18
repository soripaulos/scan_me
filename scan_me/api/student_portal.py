# Copyright (c) 2026, Tushar Patel and contributors
# For license information, please see license.txt
"""Student-facing report card download for the mobile app.

Students have no read/print permission on Student Report Card, so the desk
print pipeline is unreachable for them. This module lets the logged-in student
open their OWN card as a PDF, rendered with the "Report Card with QR" format
and no letterhead.

Two steps, because the app hands the browser a plain URL with no auth headers:

1. ``request_report_card_download`` (authenticated) — resolves the session
   user to their Student, finds the card, refuses unsigned cards, and parks a
   short-lived key pointing at it. Returns the guest PDF URL.
2. ``download_report_card`` (guest GET) — renders the parked card to PDF and
   returns it inline, so the browser shows the report card exactly as before.

Ownership is proven once, in step 1; the parked key is the capability the
guest step rides on. Rendering runs with ``ignore_print_permissions`` because
the student holds no rights on the card doctype.
"""

import json
import re
import uuid

import frappe

REPORT_CARD_DOCTYPE = "Student Report Card"
REPORT_CARD_PRINT_FORMAT = "Report Card with QR"
DOWNLOAD_KEY_TTL = 900  # seconds the parked key stays claimable
CACHE_KEY_PREFIX = "scan_me_report_card_download::"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _get_session_student():
	"""Map the session user to their Student record, or throw.

	Student user accounts link back via ``Student.user`` (and historically via
	``student_email_id``); either match proves ownership.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(frappe._("Please log in to open your report card."), frappe.PermissionError)

	student = frappe.db.get_value("Student", {"user": user}, "name") or frappe.db.get_value(
		"Student", {"student_email_id": user}, "name"
	)
	if not student:
		frappe.throw(
			frappe._("No student profile is linked to your account."),
			frappe.PermissionError,
		)
	return student


@frappe.whitelist(allow_guest=False, methods=["POST"])
def request_report_card_download(academic_year=None):
	"""Validate the student's card and return the guest URL that serves its PDF.

	``academic_year`` narrows to that year's card; omitted, the newest card wins.
	Unsigned cards (no Verified QR) are refused — the card only leaves the
	system once the school has signed it.
	"""
	student = _get_session_student()

	filters = {"student": student}
	if academic_year:
		filters["academic_year"] = academic_year
	cards = frappe.get_all(
		REPORT_CARD_DOCTYPE,
		filters=filters,
		fields=["name", "student_name", "academic_year"],
		order_by="academic_year desc, modified desc",
		limit=1,
	)
	if not cards:
		frappe.throw(
			frappe._("No report card is available for you yet. Please check back later."),
			frappe.DoesNotExistError,
		)
	card = cards[0]

	if not frappe.db.exists(
		"Verified QR", {"ref_doctype": REPORT_CARD_DOCTYPE, "ref_docname": card.name}
	):
		frappe.throw(
			frappe._(
				"Your report card has not been finalized by the school yet. "
				"Please try again once it has been signed."
			),
			frappe.ValidationError,
		)

	key = str(uuid.uuid4())
	frappe.cache().set_value(
		CACHE_KEY_PREFIX + key,
		json.dumps(
			{
				"card": card.name,
				"student_name": card.student_name or student,
				"academic_year": card.academic_year,
			}
		),
		expires_in_sec=DOWNLOAD_KEY_TTL,
	)

	return {
		"download_url": f"/api/method/scan_me.api.student_portal.download_report_card?key={key}",
		"expires_in": DOWNLOAD_KEY_TTL,
	}


def _load_parked(key):
	"""Validate the key format and return the parked payload dict, or None."""
	key = (key or "").strip().lower()
	if not UUID_RE.match(key):
		return None
	raw = frappe.cache().get_value(CACHE_KEY_PREFIX + key)
	if not raw:
		return None
	return json.loads(raw)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def download_report_card(key=None):
	"""Render the student's report card to PDF and return it inline.

	Serving inline (not as an attachment) means the browser shows the report
	card exactly as it did before — a PDF preview with the viewer's own save
	control. Guest access is safe: keys are 122-bit random UUIDs with a short
	TTL and the format is validated before touching the cache. The key stays
	valid for its TTL, then expires on its own.
	"""
	payload = _load_parked(key)
	if not payload:
		frappe.throw(
			frappe._("This link has expired. Please open the report card again."),
			frappe.DoesNotExistError,
		)

	from scan_me.api.pdf.generator import _generate_pdf_bytes

	# Ownership was proven when the key was issued; render bypasses the
	# print-permission gate on purpose. No letterhead, default options.
	frappe.flags.ignore_print_permissions = True
	pdf_bytes, _opts = _generate_pdf_bytes(
		REPORT_CARD_DOCTYPE,
		payload["card"],
		print_format=REPORT_CARD_PRINT_FORMAT,
		letter_head=None,
		options=None,
	)

	label = re.sub(
		r"[^\w\- .]", "-", f"Report Card - {payload['student_name']} - {payload['academic_year']}"
	)
	frappe.local.response.filename = f"{label}.pdf"
	frappe.local.response.filecontent = pdf_bytes
	frappe.local.response.type = "pdf"
