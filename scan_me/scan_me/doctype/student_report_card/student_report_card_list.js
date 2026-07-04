// Copyright (c) 2026, Tushar Patel and contributors
// For license information, please see license.txt

frappe.listview_settings["Student Report Card"] = {
	onload(listview) {
		// Rebuild every card from submitted Student Term/Year Reports (background job).
		listview.page.add_inner_button(__("Generate / Update All"), () => {
			frappe.prompt(
				[
					{
						fieldname: "academic_year",
						fieldtype: "Data",
						label: __("Academic Year (leave blank for all)"),
					},
				],
				(values) => {
					frappe.call({
						method: "scan_me.utils.report_card_generator.enqueue_sync",
						args: { academic_year: values.academic_year || null },
						callback: (r) => {
							frappe.show_alert({
								message: (r.message && r.message.message) || __("Generation started."),
								indicator: "green",
							});
						},
					});
				},
				__("Generate / Update Report Cards"),
				__("Start")
			);
		});

		// Bulk-sign selected cards with Verified QRs.
		listview.page.add_actions_menu_item(__("Generate Verified QR"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Select at least one report card."));
				return;
			}

			const fields = [];
			if (frappe.user.has_role("System Manager")) {
				fields.push({
					fieldname: "resign",
					fieldtype: "Check",
					label: __("Re-sign updated cards (deletes their old QRs first)"),
					default: 0,
				});
			}

			const run = (values) => {
				frappe.call({
					method: "scan_me.utils.report_card_generator.bulk_generate_qr",
					args: { names: names, resign: (values && values.resign) || 0 },
					freeze: true,
					freeze_message: __("Generating Verified QRs..."),
					callback: (r) => {
						const s = r.message || {};
						let msg = __("Created: {0}, already signed: {1}", [s.created || 0, s.existing || 0]);
						if (s.resigned) {
							msg += ", " + __("re-signed: {0}", [s.resigned]);
						}
						if (s.errors && s.errors.length) {
							msg += ", " + __("errors: {0}", [s.errors.length]);
						}
						frappe.msgprint({ title: __("Bulk Verified QR"), message: msg, indicator: s.errors && s.errors.length ? "orange" : "green" });
						listview.refresh();
					},
				});
			};

			if (fields.length) {
				frappe.prompt(fields, run, __("Generate Verified QR for {0} cards", [names.length]), __("Generate"));
			} else {
				run(null);
			}
		});
	},
};
