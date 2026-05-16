/* global frappe */
frappe.provide("scan_me.pages");

frappe.pages["report-card-generator"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Report Card Generator"),
		single_column: true,
	});
	scan_me.pages.rcg = new ReportCardGenerator(page);
};

frappe.pages["report-card-generator"].on_page_show = function () {
	if (scan_me.pages.rcg) scan_me.pages.rcg.on_show();
};

class ReportCardGenerator {
	constructor(page) {
		this.page = page;
		this.$wrapper = $(page.body);
		this.academic_year = null;
		this.selected_students = [];
		this.generated = [];
		this.init();
	}

	async init() {
		this.inject_styles();
		this.render();
		this.academic_year = await this.get_academic_year();
		this.$wrapper.find("[data-field='academic_year']").val(this.academic_year || "2018 E.C.");
		this.fetch_student_groups();
	}

	async get_academic_year() {
		try {
			const r = await frappe.call("scan_me.page.report_card_generator.report_card_generator.get_academic_year");
			return r.message || "2018 E.C.";
		} catch { return "2018 E.C."; }
	}

	inject_styles() {
		if (document.getElementById("rcg-styles")) return;
		const s = document.createElement("style");
		s.id = "rcg-styles";
		s.textContent = `
.rcg-root { padding: 24px 20px; max-width: 860px; margin: 0 auto; }
.rcg-header { margin-bottom: 28px; }
.rcg-header h2 { margin: 0 0 6px; font-size: 20px; font-weight: 600; }
.rcg-header p { color: #666; margin: 0; font-size: 13px; }
.rcg-card { background: #fff; border: 1px solid #d1d8dd; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
.rcg-card-title { font-size: 14px; font-weight: 600; margin-bottom: 16px; color: #333; }
.rcg-form-row { display: flex; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.rcg-form-row .form-group { flex: 1 1 200px; min-width: 160px; }
.rcg-form-row label { display: block; font-size: 12px; color: #555; margin-bottom: 4px; font-weight: 500; }
.rcg-form-row select, .rcg-form-row input { width: 100%; height: 34px; padding: 0 10px; border: 1px solid #d1d8dd; border-radius: 4px; font-size: 13px; }
.rcg-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 18px; background: #2490ef; color: #fff; border: none; border-radius: 4px; font-size: 13px; cursor: pointer; }
.rcg-btn:hover { background: #1a7bd4; }
.rcg-btn:disabled { background: #a0a5aa; cursor: not-allowed; }
.rcg-btn-secondary { background: #fff; color: #333; border: 1px solid #d1d8dd; }
.rcg-btn-secondary:hover { background: #f5f6f7; }
.rcg-btn-green { background: #2490ef; }
.rcg-info { font-size: 12px; color: #666; margin-top: 10px; }
.rcg-error { color: #e03e38; font-size: 13px; margin-top: 10px; }
.rcg-success { color: #2490ef; font-size: 13px; margin-top: 10px; }
.rcg-progress { display: none; margin-top: 14px; }
.rcg-progress-bar { height: 4px; background: #e9ecef; border-radius: 2px; overflow: hidden; }
.rcg-progress-fill { height: 100%; background: #2490ef; width: 0%; transition: width 0.3s; }
.rcg-progress-text { font-size: 12px; color: #666; margin-top: 6px; }
.rcg-results { margin-top: 20px; display: none; }
.rcg-results h4 { font-size: 13px; font-weight: 600; margin-bottom: 12px; color: #333; }
.rcg-result-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: #f8f9fa; border-radius: 4px; margin-bottom: 6px; font-size: 13px; }
.rcg-result-item .student-name { font-weight: 500; }
.rcg-result-item .doc-link a { color: #2490ef; font-size: 12px; }
.rcg-result-item .qr-status { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.rcg-result-item .qr-status.done { background: #e3fdeb; color: #1a7a3a; }
.rcg-result-item .qr-status.pending { background: #fff3cd; color: #856404; }
.rcg-result-item .qr-status.error { background: #fde8e8; color: #c0392b; }
.rcg-checklist { border: 1px solid #d1d8dd; border-radius: 8px; overflow: hidden; }
.rcg-checklist-header { display: flex; align-items: center; padding: 10px 14px; background: #f8f9fa; cursor: pointer; font-size: 13px; font-weight: 600; }
.rcg-checklist-header input[type="checkbox"] { margin-right: 8px; }
.rcg-checklist-body { padding: 0 14px; max-height: 280px; overflow-y: auto; }
.rcg-student-row { display: flex; align-items: center; padding: 7px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.rcg-student-row:last-child { border-bottom: none; }
.rcg-student-row input[type="checkbox"] { margin-right: 8px; }
.rcg-student-row .sname { flex: 1; }
.rcg-student-row .sgroup { color: #888; font-size: 12px; }
.rcg-empty { text-align: center; padding: 28px; color: #888; font-size: 13px; }
		`;
		document.head.appendChild(s);
	}

	render() {
		this.$wrapper.html(`
<div class="rcg-header">
  <h2>📋 Report Card Generator</h2>
  <p>Select students and generate their annual report cards with Verified QR codes.</p>
</div>

<div class="rcg-card">
  <div class="rcg-card-title">Academic Year &amp; Class</div>
  <div class="rcg-form-row">
    <div class="form-group">
      <label>Academic Year</label>
      <input type="text" data-field="academic_year" placeholder="e.g. 2018 E.C." />
    </div>
    <div class="form-group">
      <label>Grade / Class</label>
      <select data-field="student_group"></select>
    </div>
  </div>
</div>

<div class="rcg-card">
  <div class="rcg-card-title">Select Students</div>
  <div class="rcg-checklist">
    <div class="rcg-checklist-header">
      <input type="checkbox" id="rcg-select-all" />
      <label for="rcg-select-all">Select All</label>
      <span id="rcg-count" style="margin-left: auto; font-weight: 400; font-size: 12px; color: #888;"></span>
    </div>
    <div class="rcg-checklist-body" id="rcg-student-list">
      <div class="rcg-empty">Select a class to see students</div>
    </div>
  </div>
  <div class="rcg-info" id="rcg-info"></div>
</div>

<div class="rcg-card">
  <div class="rcg-form-row" style="align-items: center;">
    <button class="rcg-btn rcg-btn-green" id="rcg-generate" disabled>
      ▶ Generate Report Cards
    </button>
    <span id="rcg-status" style="font-size:12px; color:#666;"></span>
  </div>
  <div class="rcg-progress" id="rcg-progress">
    <div class="rcg-progress-bar"><div class="rcg-progress-fill" id="rcg-progress-fill"></div></div>
    <div class="rcg-progress-text" id="rcg-progress-text"></div>
  </div>
  <div id="rcg-messages"></div>
</div>

<div class="rcg-results" id="rcg-results">
  <h4>✅ Generated Report Cards</h4>
  <div id="rcg-results-body"></div>
</div>
		`);
		this.bind_events();
	}

	bind_events() {
		const $root = this.$wrapper;

		$root.on("change", "[data-field='student_group']", () => this.load_students());
		$root.on("click", "#rcg-select-all", () => this.toggle_all());
		$root.on("click", ".rcg-student-row input", (e) => { e.stopPropagation(); this.update_count(); });
		$root.on("click", ".rcg-student-row", (e) => {
			if (e.target.tagName === "INPUT" || e.target.tagName === "LABEL") return;
			$(e.currentTarget).find("input").prop("checked", (_, v) => !v);
			this.update_count();
		});
		$root.on("click", "#rcg-generate", () => this.generate());
	}

	async fetch_student_groups() {
		try {
			const r = await frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Student",
					fields: ["student_group"],
					limit_page_length: 500,
					order_by: "student_group",
				}
			});
			const groups = [...new Map((r.message || []).map(s => [s.student_group, s])).values()];
			const $sel = $root.find("[data-field='student_group']");
			$sel.html('<option value="">— Select Class —</option>');
			groups.forEach(g => {
				if (g.student_group) $sel.append(`<option value="${frappe.utils.escape_html(g.student_group)}">${frappe.utils.escape_html(g.student_group)}</option>`);
			});
		} catch (e) { console.error(e); }
	}

	async load_students() {
		const group = $root.find("[data-field='student_group']").val();
		if (!group) {
			$root.find("#rcg-student-list").html('<div class="rcg-empty">Select a class to see students</div>');
			return;
		}
		$root.find("#rcg-info").text("Loading students...");
		try {
			const r = await frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Student",
					filters: { student_group: group },
					fields: ["name", "student_name", "student_group"],
					limit_page_length: 500,
					order_by: "student_name",
				}
			});
			const students = r.message || [];
			if (!students.length) {
				$root.find("#rcg-student-list").html(`<div class="rcg-empty">No students found in ${frappe.utils.escape_html(group)}</div>`);
				$root.find("#rcg-info").text("");
				return;
			}
			const html = students.map(s => `
<div class="rcg-student-row">
  <input type="checkbox" data-student="${frappe.utils.escape_html(s.name)}" id="rcg-s-${frappe.utils.escape_html(s.name)}" />
  <label for="rcg-s-${frappe.utils.escape_html(s.name)}" class="sname">${frappe.utils.escape_html(s.student_name || s.name)}</label>
  <span class="sgroup">${frappe.utils.escape_html(s.student_group || "")}</span>
</div>`).join("");
			$root.find("#rcg-student-list").html(html);
			$root.find("#rcg-count").text(`${students.length} students`);
			$root.find("#rcg-info").text("");
		} catch (e) {
			$root.find("#rcg-student-list").html(`<div class="rcg-empty">Error loading students</div>`);
		}
	}

	toggle_all() {
		const checked = $root.find("#rcg-select-all").prop("checked");
		$root.find(".rcg-student-row input").prop("checked", checked);
		this.update_count();
	}

	update_count() {
		const total = $root.find(".rcg-student-row input").length;
		const checked = $root.find(".rcg-student-row input:checked").length;
		$root.find("#rcg-count").text(`${checked}/${total} selected`);
		$root.find("#rcg-generate").prop("disabled", checked === 0);
	}

	async generate() {
		const students = $root.find(".rcg-student-row input:checked").map((_, el) => $(el).data("student")).get();
		if (!students.length) return;
		const academic_year = $root.find("[data-field='academic_year']").val();
		const $btn = $root.find("#rcg-generate");
		const $progress = $root.find("#rcg-progress");
		const $fill = $root.find("#rcg-progress-fill");
		const $text = $root.find("#rcg-progress-text");
		const $results = $root.find("#rcg-results");
		const $body = $root.find("#rcg-results-body");
		const $msgs = $root.find("#rcg-messages");

		$btn.prop("disabled", true).text("⏳ Generating...");
		$progress.show();
		$results.hide();
		$msgs.html("");
		$body.html("");

		const results = [];
		for (let i = 0; i < students.length; i++) {
			const student = students[i];
			$fill.css("width", `${((i) / students.length) * 100}%`);
			$text.text(`Processing ${i + 1} of ${students.length}: ${student}...`);

			try {
				const r = await frappe.call({
					method: "scan_me.page.report_card_generator.report_card_generator.create_report_card",
					args: { student, academic_year },
					freeze: false,
				});
				results.push({ student, status: "success", data: r.message });
			} catch (e) {
				results.push({ student, status: "error", message: e.message || "Failed" });
			}
		}

		$fill.css("width", "100%");
		$text.text("Done!");
		$btn.prop("disabled", false).text("▶ Generate Report Cards");
		$progress.hide();

		// Show results
		const success_count = results.filter(r => r.status === "success").length;
		$msgs.html(`<div class="rcg-success">Generated ${success_count} of ${students.length} report cards. Scroll down to see results.</div>`);

		$body.html(results.map(r => {
			const status_class = r.status === "success" ? "done" : "error";
			const status_text = r.status === "success" ? "QR Ready" : "Failed";
			const link = r.status === "success" && r.data && r.data.report_card_name
				? `<a href="/app/report-card/${frappe.utils.escape_html(r.data.report_card_name)}" target="_blank">Open</a>`
				: "";
			const name = r.status === "success" && r.data ? r.data.student_name : r.student;
			return `<div class="rcg-result-item">
  <span class="student-name">${frappe.utils.escape_html(name)}</span>
  <span class="qr-status ${status_class}">${status_text}</span>
  ${link ? `<span class="doc-link">${link}</span>` : `<span style="color:#c0392b; font-size:12px;">${frappe.utils.escape_html(r.message || "")}</span>`}
</div>`;
		}).join(""));
		$results.show();
		$results[0].scrollIntoView({ behavior: "smooth", block: "nearest" });
	}

	on_show() {
		// Refresh state if needed
	}
}

window.ReportCardGenerator = ReportCardGenerator;