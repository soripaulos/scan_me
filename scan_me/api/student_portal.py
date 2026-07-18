# Copyright (c) 2026, Tushar Patel and contributors
# For license information, please see license.txt
"""Student-facing report card view/download for the mobile app.

Students have no read/print permission on Student Report Card, so the desk
print pipeline is unreachable for them. This module lets the logged-in student
open their OWN card, rendered with the "Report Card with QR" format and no
letterhead.

Flow (the app hands the browser a plain URL with no auth headers, so the
handoff has to work for an unauthenticated GET):

1. ``request_report_card_download`` (authenticated) — resolves the session
   user to their Student, finds the card, refuses unsigned cards, and parks a
   short-lived key pointing at the card. No PDF is rendered here, so opening
   the card never depends on the (heavier) Chromium PDF pipeline.
2. ``report_card_page`` (guest GET) — renders the report card itself as HTML
   (the same print format, no Chromium needed) with a small "Download PDF"
   button pinned at the bottom.
3. ``download_report_card`` (guest GET) — renders the card to PDF via the
   Chromium pipeline and streams it as an attachment (a direct download).

Ownership is proven once, in step 1; the parked key is the capability the
guest steps ride on. Rendering runs with ``ignore_print_permissions`` set
because the student holds no rights on the card doctype.
"""

import json
import re
import uuid

import frappe

REPORT_CARD_DOCTYPE = "Student Report Card"
REPORT_CARD_PRINT_FORMAT = "Report Card with QR"
DOWNLOAD_KEY_TTL = 900  # seconds the parked key stays valid (view + download window)
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
	"""Validate the student's card and return the URL of its view/download page.

	``academic_year`` narrows to that year's card; omitted, the newest card wins.
	Unsigned cards (no Verified QR) are refused — the card only leaves the
	system once the school has signed it. No PDF is rendered here.
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
		"download_url": f"/api/method/scan_me.api.student_portal.report_card_page?key={key}",
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


def _html_response(html, status=200):
	from werkzeug.wrappers import Response

	return Response(html, status=status, mimetype="text/html")


def _safe_filename(payload):
	label = re.sub(
		r"[^\w\- .]", "-", f"Report Card - {payload['student_name']} - {payload['academic_year']}"
	)
	return f"{label}.pdf"


# Small "Download PDF" button injected into the card's own HTML. Fixed to the
# bottom, deliberately compact, and hidden if the page itself is printed.
_DOWNLOAD_BUTTON = """
<style>
  #scanme-dl-bar {{
    position: fixed; left: 0; right: 0; bottom: 0; text-align: center;
    padding: 10px; z-index: 9999; pointer-events: none;
  }}
  #scanme-dl-bar a {{
    pointer-events: auto; display: inline-block;
    background: #1a3a6b; color: #fff; text-decoration: none;
    padding: 9px 20px; border-radius: 8px; font: 600 14px/1
      -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    box-shadow: 0 3px 12px rgba(0,0,0,.25);
  }}
  #scanme-dl-bar a:active {{ opacity: .85; }}
  body {{ padding-bottom: 64px; }}
  @media print {{ #scanme-dl-bar {{ display: none !important; }} }}
</style>
<div id="scanme-dl-bar"><a href="{dl_url}" download>Download PDF</a></div>
"""

_VIEWPORT_META = '<meta name="viewport" content="width=device-width, initial-scale=1">'


@frappe.whitelist(allow_guest=True, methods=["GET"])
def report_card_page(key=None):
	"""Render the student's report card as HTML with a Download PDF button.

	This is the card itself (same print format), not a separate landing page.
	It renders without Chromium, so a student can always open their card; only
	the Download PDF button routes through the PDF pipeline.
	"""
	payload = _load_parked(key)
	if not payload:
		body = (
			"<!doctype html><meta charset='utf-8'>" + _VIEWPORT_META
			+ "<div style=\"font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;"
			"max-width:420px;margin:15vh auto;text-align:center;padding:0 20px;color:#1a3a6b\">"
			"<h1 style='font-size:20px'>Link expired</h1>"
			"<p style='color:#667'>This report card link has expired. Open the app and tap "
			"<b>Download Report Card</b> again.</p></div>"
		)
		return _html_response(body, status=410)

	safe_key = (key or "").strip().lower()
	dl_url = f"/api/method/scan_me.api.student_portal.download_report_card?key={safe_key}"

	frappe.flags.ignore_print_permissions = True
	html = frappe.get_print(
		REPORT_CARD_DOCTYPE,
		payload["card"],
		print_format=REPORT_CARD_PRINT_FORMAT,
		no_letterhead=True,
	)

	button = _DOWNLOAD_BUTTON.format(dl_url=dl_url)
	if "</head>" in html:
		html = html.replace("</head>", _VIEWPORT_META + "</head>", 1)
	if "</body>" in html:
		html = html.replace("</body>", button + "</body>", 1)
	else:
		html += button

	return _html_response(html)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def download_report_card(key=None):
	"""Render the student's report card to PDF and stream it as a download.

	Guest access is safe: keys are 122-bit random UUIDs with a short TTL, and
	the key format is validated before touching the cache. The key stays valid
	for its TTL so the student can view then download; it expires on its own.
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

	frappe.local.response.filename = _safe_filename(payload)
	frappe.local.response.filecontent = pdf_bytes
	frappe.local.response.content_type = "application/pdf"
	# "download" -> Content-Disposition: attachment, so the browser saves the
	# file instead of opening the browser print flow.
	frappe.local.response.type = "download"
