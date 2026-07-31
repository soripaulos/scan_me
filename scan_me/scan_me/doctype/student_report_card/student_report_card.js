// Copyright (c) 2026, Tushar Patel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Student Report Card", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(
			__("Refresh from Results"),
			() => {
				frappe.call({
					method: "scan_me.utils.report_card_generator.refresh_report_card",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Rebuilding report card from submitted results..."),
					callback: () => {
						frappe.show_alert({ message: __("Report card refreshed."), indicator: "green" });
						frm.reload_doc();
					},
				});
			},
			__("Actions")
		);

		// Signing is handled by Scan Me's shared "Generate Verified QR" button, which
		// prompts for the School Director because this doctype links to one.
	},
});
