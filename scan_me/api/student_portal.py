# Copyright (c) 2026, Tushar Patel and contributors
# For license information, please see license.txt
"""Student-facing report card download for the mobile app.

Students have no read/print permission on Student Report Card, so the desk
print pipeline is unreachable for them. This module gives the logged-in
student exactly one thing: a PDF of their OWN card, rendered through the same
Chromium pipeline as Advanced Print, hardwired to the "Report Card with QR"
format with no letterhead.

Flow (two steps because mobile apps can't attach auth headers to the system
browser they hand the PDF to):

1. ``request_report_card_download`` (authenticated) — resolves the session
   user to their Student, finds the card, refuses unsigned cards, renders the
   PDF, parks the bytes in Redis under a random one-time key, and returns the
   guest download URL.
2. ``download_report_card`` (guest GET) — swaps the one-time key for the
   parked PDF and streams it inline. The key is deleted before responding and
   expires after ``DOWNLOAD_KEY_TTL`` seconds regardless.
"""

import base64
import json
import re
import uuid

import frappe

REPORT_CARD_DOCTYPE = "Student Report Card"
REPORT_CARD_PRINT_FORMAT = "Report Card with QR"
DOWNLOAD_KEY_TTL = 300  # seconds a parked PDF stays claimable
CACHE_KEY_PREFIX = "scan_me_report_card_download::"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _get_session_student():
	"""Map the session user to their Student record, or throw.

	Student user accounts link back via ``Student.user`` (and historically via
	``student_email_id``); either match proves ownership.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(frappe._("Please log in to download your report card."), frappe.PermissionError)

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
	"""Render the logged-in student's report card and return a one-time download URL.

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

	from scan_me.api.pdf.generator import _generate_pdf_bytes

	# Ownership was proven above; render bypasses the print-permission gate on
	# purpose (students hold no rights on the card doctype). No letterhead and
	# default options, exactly like the school's standard report card print.
	pdf_bytes, _opts = _generate_pdf_bytes(
		REPORT_CARD_DOCTYPE,
		card.name,
		print_format=REPORT_CARD_PRINT_FORMAT,
		letter_head=None,
		options=None,
	)

	file_label = re.sub(r"[^\w\- .]", "-", f"Report Card - {card.student_name or student} - {card.academic_year}")
	key = str(uuid.uuid4())
	frappe.cache().set_value(
		CACHE_KEY_PREFIX + key,
		json.dumps(
			{
				"file_name": f"{file_label}.pdf",
				"content": base64.b64encode(pdf_bytes).decode("ascii"),
			}
		),
		expires_in_sec=DOWNLOAD_KEY_TTL,
	)

	return {
		"download_url": f"/api/method/scan_me.api.student_portal.download_report_card?key={key}",
		"file_name": f"{file_label}.pdf",
		"expires_in": DOWNLOAD_KEY_TTL,
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def download_report_card(key=None):
	"""Stream a parked report card PDF for a one-time key (see module docstring).

	Guest access is safe: keys are single-use 122-bit random UUIDs with a
	5-minute TTL, and the key format is validated before touching the cache.
	"""
	key = (key or "").strip().lower()
	if not UUID_RE.match(key):
		frappe.throw(frappe._("Invalid download link."), frappe.ValidationError)

	cache_key = CACHE_KEY_PREFIX + key
	raw = frappe.cache().get_value(cache_key)
	if not raw:
		frappe.throw(
			frappe._("This download link has expired. Please request the report card again."),
			frappe.DoesNotExistError,
		)
	# One-time: burn the key before responding.
	frappe.cache().delete_value(cache_key)

	payload = json.loads(raw)
	frappe.local.response.filename = payload["file_name"]
	frappe.local.response.filecontent = base64.b64decode(payload["content"])
	frappe.local.response.type = "pdf"
