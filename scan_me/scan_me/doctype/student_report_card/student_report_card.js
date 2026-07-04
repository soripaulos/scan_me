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

		frm.add_custom_button(
			__("Generate Verified QR"),
			() => {
				frappe.call({
					method: "scan_me.utils.report_card_generator.bulk_generate_qr",
					args: { names: [frm.doc.name] },
					freeze: true,
					callback: (r) => {
						const s = r.message || {};
						if (s.errors && s.errors.length) {
							frappe.msgprint({
								title: __("Verified QR"),
								indicator: "red",
								message: frappe.utils.escape_html(s.errors[0].error || __("Failed")),
							});
						} else if (s.existing) {
							frappe.show_alert({ message: __("A Verified QR already exists."), indicator: "orange" });
						} else {
							frappe.show_alert({ message: __("Verified QR created."), indicator: "green" });
						}
					},
				});
			},
			__("Actions")
		);
	},
});
