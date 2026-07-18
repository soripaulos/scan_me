# Copyright (c) 2026, Tushar Patel and contributors
# For license information, please see license.txt
"""Student-facing report card download for the mobile app.

Students have no read/print permission on Student Report Card, so the desk
print pipeline is unreachable for them. This module gives the logged-in
student exactly one thing: a PDF of their OWN card, rendered through the same
Chromium pipeline as Advanced Print, hardwired to the "Report Card with QR"
format with no letterhead.

Flow (the app hands the browser a plain URL with no auth headers, so the
handoff has to work for an unauthenticated GET):

1. ``request_report_card_download`` (authenticated) — resolves the session
   user to their Student, finds the card, refuses unsigned cards, renders the
   PDF, parks the bytes in Redis under a random key, and returns the URL of a
   small landing page.
2. ``report_card_page`` (guest GET) — a minimal HTML page with a "Download
   PDF" button that force-downloads the file (and auto-starts the download),
   so the student gets the actual PDF instead of a browser print dialog.
3. ``download_report_card`` (guest GET) — streams the parked PDF as an
   attachment. The parked key stays valid for its short TTL (so the button
   and the auto-trigger can both fire) and then expires on its own.
"""

import base64
import json
import re
import uuid

import frappe

REPORT_CARD_DOCTYPE = "Student Report Card"
REPORT_CARD_PRINT_FORMAT = "Report Card with QR"
DOWNLOAD_KEY_TTL = 600  # seconds a parked PDF stays claimable
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
	"""Render the logged-in student's report card and return a landing-page URL.

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

	label = re.sub(r"[^\w\- .]", "-", f"Report Card - {card.student_name or student} - {card.academic_year}")
	key = str(uuid.uuid4())
	frappe.cache().set_value(
		CACHE_KEY_PREFIX + key,
		json.dumps(
			{
				"file_name": f"{label}.pdf",
				"title": card.student_name or student,
				"subtitle": card.academic_year,
				"content": base64.b64encode(pdf_bytes).decode("ascii"),
			}
		),
		expires_in_sec=DOWNLOAD_KEY_TTL,
	)

	return {
		"download_url": f"/api/method/scan_me.api.student_portal.report_card_page?key={key}",
		"file_name": f"{label}.pdf",
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


@frappe.whitelist(allow_guest=True, methods=["GET"])
def report_card_page(key=None):
	"""Landing page with a 'Download PDF' button (see module docstring).

	The button force-downloads the PDF and the page also auto-starts the
	download on load, so the student never has to go through the browser's
	print/save flow. Reads the parked payload only to show the student's name
	and file size — it does not consume the key.
	"""
	payload = _load_parked(key)
	esc = frappe.utils.escape_html
	if not payload:
		body = (
			'<div class="card"><h1>Link expired</h1>'
			'<p>This report card link has expired. Please open the app and tap '
			"<b>Download Report Card</b> again.</p></div>"
		)
		return _html_response(_PAGE_SHELL.format(title="Report Card", body=body, script=""), status=410)

	safe_key = (key or "").strip().lower()
	dl_url = f"/api/method/scan_me.api.student_portal.download_report_card?key={safe_key}"
	kb = round(len(base64.b64decode(payload["content"])) / 1024)
	body = (
		'<div class="card">'
		'<div class="tick">&#10003;</div>'
		"<h1>Report Card Ready</h1>"
		f'<p class="who">{esc(payload.get("title", ""))}</p>'
		f'<p class="sub">{esc(payload.get("subtitle", ""))} &middot; PDF, {kb} KB</p>'
		'<p class="hint">Your download should start automatically. If it does not, use the button below.</p>'
		"</div>"
		f'<a class="dl-btn" id="dl" href="{dl_url}" download>Download PDF</a>'
	)
	# Auto-start the download shortly after load without navigating away from
	# this page (an attachment response keeps the page in place).
	script = (
		"<script>setTimeout(function(){var a=document.getElementById('dl');"
		"if(a){a.click();}},600);</script>"
	)
	return _html_response(_PAGE_SHELL.format(title="Report Card", body=body, script=script))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def download_report_card(key=None):
	"""Stream a parked report card PDF as an attachment (forces a download).

	Guest access is safe: keys are 122-bit random UUIDs with a short TTL, and
	the key format is validated before touching the cache. The key is left in
	place for its TTL so the landing page's button and auto-trigger can both
	claim it; it then expires on its own.
	"""
	payload = _load_parked(key)
	if not payload:
		frappe.throw(
			frappe._("This download link has expired. Please request the report card again."),
			frappe.DoesNotExistError,
		)

	frappe.local.response.filename = payload["file_name"]
	frappe.local.response.filecontent = base64.b64decode(payload["content"])
	frappe.local.response.content_type = "application/pdf"
	# "download" -> Content-Disposition: attachment, so the browser saves the
	# file instead of rendering it inline (which would force a print flow).
	frappe.local.response.type = "download"


_PAGE_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#f4f6fb; --fg:#1a3a6b; --muted:#667; --card:#fff; --accent:#1a3a6b; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1420; --fg:#dbe6ff; --muted:#9aa7bd; --card:#182238; --accent:#3b6fd4; }}
  }}
  * {{ box-sizing:border-box; }}
  html, body {{ height:100%; margin:0; }}
  body {{
    background:var(--bg); color:var(--fg);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
    display:flex; flex-direction:column; align-items:center; justify-content:space-between;
    padding:32px 20px; min-height:100%;
  }}
  .card {{
    background:var(--card); border-radius:16px; padding:28px 22px; max-width:420px; width:100%;
    text-align:center; box-shadow:0 6px 24px rgba(0,0,0,.08);
  }}
  .tick {{
    width:52px; height:52px; line-height:52px; border-radius:50%;
    background:#1e8449; color:#fff; font-size:26px; margin:0 auto 12px;
  }}
  h1 {{ font-size:20px; margin:0 0 6px; color:var(--fg); }}
  .who {{ font-size:16px; font-weight:600; margin:0; }}
  .sub {{ font-size:13px; color:var(--muted); margin:2px 0 12px; }}
  .hint {{ font-size:13px; color:var(--muted); margin:0; line-height:1.4; }}
  .dl-btn {{
    display:inline-block; margin:20px auto 8px;
    background:var(--accent); color:#fff; text-decoration:none;
    padding:11px 22px; border-radius:10px; font-size:15px; font-weight:600;
  }}
  .dl-btn:active {{ opacity:.85; }}
</style>
</head>
<body>
{body}
{script}
</body>
</html>"""
