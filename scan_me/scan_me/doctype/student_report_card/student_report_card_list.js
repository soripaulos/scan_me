// Copyright (c) 2026, Tushar Patel and contributors
// For license information, please see license.txt

frappe.listview_settings["Student Report Card"] = {
	onload(listview) {
		// Rebuild cards from submitted Student Term/Year Reports (background job),
		// scoped to a chosen academic year and optionally a program or student group.
		listview.page.add_inner_button(__("Generate / Update Cards"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Generate / Update Report Cards"),
				fields: [
					{
						fieldname: "academic_year",
						fieldtype: "Link",
						label: __("Academic Year"),
						options: "Academic Year",
						reqd: 1,
					},
					{
						fieldname: "scope_help",
						fieldtype: "HTML",
						options: `<p class="text-muted small">${__(
							"Narrow to a program or a single student group. Leave both blank to process every group in the year."
						)}</p>`,
					},
					{
						fieldname: "program",
						fieldtype: "Link",
						label: __("Program (optional)"),
						options: "Program",
						onchange() {
							// Reset a now-inconsistent group when the program changes.
							dialog.set_value("student_group", "");
						},
					},
					{
						fieldname: "student_group",
						fieldtype: "Link",
						label: __("Student Group (optional)"),
						options: "Student Group",
						get_query() {
							const filters = {};
							const ay = dialog.get_value("academic_year");
							const program = dialog.get_value("program");
							if (ay) filters.academic_year = ay;
							if (program) filters.program = program;
							return { filters };
						},
					},
				],
				primary_action_label: __("Start"),
				primary_action(values) {
					frappe.call({
						method: "scan_me.utils.report_card_generator.enqueue_sync",
						args: {
							academic_year: values.academic_year,
							program: values.program || null,
							student_group: values.student_group || null,
						},
						callback: (r) => {
							frappe.show_alert({
								message: (r.message && r.message.message) || __("Generation started."),
								indicator: "green",
							});
						},
					});
					dialog.hide();
				},
			});
			dialog.show();
		});

		// Bulk-sign selected cards with Verified QRs.
		listview.page.add_actions_menu_item(__("Generate Verified QR"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Select at least one report card."));
				return;
			}

			const fields = [
				{
					fieldname: "director",
					fieldtype: "Link",
					label: __("Signing Director"),
					options: "School Director",
					get_query() {
						return { filters: { disabled: 0 } };
					},
					description: __(
						"The director's name, position and signature are printed on each card and covered by the QR's tamper hash."
					),
				},
			];
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
					args: {
						names: names,
						resign: (values && values.resign) || 0,
						director: (values && values.director) || null,
					},
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

			frappe.prompt(fields, run, __("Generate Verified QR for {0} cards", [names.length]), __("Generate"));
		});
	},
};
