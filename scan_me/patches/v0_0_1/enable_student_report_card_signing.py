import frappe


def execute():
	"""Allowlist 'Student Report Card' for QR signing in Scan Me Settings."""
	settings = frappe.get_single("Scan Me Settings")
	for row in settings.get("ref_doctype_info") or []:
		if row.ref_doctype == "Student Report Card":
			if not row.enable:
				row.enable = 1
				settings.save(ignore_permissions=True)
			return

	settings.append("ref_doctype_info", {"ref_doctype": "Student Report Card", "enable": 1})
	settings.save(ignore_permissions=True)
