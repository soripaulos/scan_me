/* global Html5Qrcode */
(function () {
	"use strict";

	var scanner = null;
	var $scanWrap = document.getElementById("scanner-wrap");
	var $scanBtn = document.getElementById("scan-btn");
	var $scanLabel = document.getElementById("scan-btn-label");
	var $stopBtn = document.getElementById("stop-btn");
	var $input = document.getElementById("uuid-input");
	var $form = document.getElementById("manual-form");
	var $result = document.getElementById("result");

	$scanBtn.addEventListener("click", startScan);
	$stopBtn.addEventListener("click", stopScan);
	$form.addEventListener("submit", function (e) {
		e.preventDefault();
		var value = ($input.value || "").trim();
		if (!value) {
			flashInput();
			return;
		}
		verify(value);
	});

	// ---- scanning ------------------------------------------------------

	function startScan() {
		if (typeof Html5Qrcode === "undefined") {
			renderState("invalid", {
				message: "QR scanner failed to load. Use the manual entry option below.",
			});
			return;
		}
		if (scanner) return;
		$scanWrap.innerHTML = "";
		$scanWrap.classList.add("active");
		scanner = new Html5Qrcode("scanner-wrap");

		Html5Qrcode.getCameras()
			.then(function (cameras) {
				if (!cameras || !cameras.length) {
					renderState("invalid", {
						message: "No camera detected. Use the manual entry option below.",
					});
					cleanupScanner();
					return;
				}
				var cameraId = pickCameraId(cameras);
				setScanButton(true);
				scanner
					.start(
						cameraId,
						{ fps: 10, qrbox: { width: 240, height: 240 } },
						function (qrText) {
							stopScan().then(function () {
								verify(qrText);
							});
						},
						function (_err) {
							/* per-frame scan misses — ignore */
						}
					)
					.catch(function () {
						renderState("invalid", {
							message:
								"Unable to start the camera. Please grant permission or use manual entry.",
						});
						cleanupScanner();
					});
			})
			.catch(function () {
				renderState("invalid", {
					message:
						"Unable to access the camera. Please grant permission or use manual entry.",
				});
				cleanupScanner();
			});
	}

	function stopScan() {
		if (!scanner) return Promise.resolve();
		return scanner.stop().then(cleanupScanner).catch(cleanupScanner);
	}

	function cleanupScanner() {
		try {
			if (scanner) scanner.clear();
		} catch (_e) {
			/* ignore */
		}
		scanner = null;
		$scanWrap.classList.remove("active");
		$scanWrap.innerHTML = "";
		setScanButton(false);
	}

	function pickCameraId(cameras) {
		for (var i = 0; i < cameras.length; i++) {
			var label = (cameras[i].label || "").toLowerCase();
			if (
				label.indexOf("back") >= 0 ||
				label.indexOf("rear") >= 0 ||
				label.indexOf("environment") >= 0
			) {
				return cameras[i].id;
			}
		}
		return cameras[0].id;
	}

	function setScanButton(running) {
		$scanLabel.textContent = running ? "Scanning\u2026" : "Scan QR Code";
		$scanBtn.disabled = running;
		$stopBtn.hidden = !running;
	}

	function flashInput() {
		$input.style.borderColor = "#dc2626";
		setTimeout(function () {
			$input.style.borderColor = "";
		}, 700);
		$input.focus();
	}

	// ---- verify --------------------------------------------------------

	function verify(code) {
		var cleaned = (code || "").trim();
		if (!cleaned) {
			flashInput();
			return;
		}

		renderLoading();

		fetch("/api/method/scan_me.api.verify_document_qr.verify_document_qr", {
			method: "POST",
			credentials: "same-origin",
			headers: { Accept: "application/json" },
			body: new URLSearchParams({ uuid: cleaned }),
		})
			.then(function (res) {
				if (res.status === 429) {
					renderState("invalid", {
						title: "Too Many Attempts",
						message:
							"You've hit the verification rate limit. Please wait a moment and try again.",
					});
					throw new Error("rate_limited");
				}
				return res.json();
			})
			.then(function (r) {
				var d = (r && r.message) || {};
				var status = d.status || "invalid";

				if (status === "valid") {
					renderState("verified", {
						title: d.title || "Document Authentic",
						message:
							d.message ||
							"This document is authentic and has not been modified since signing.",
						details: collectDetails(d),
						reportCardData: d.report_card_data,
					});
				} else if (status === "tampered") {
					renderState("tampered", {
						title: d.title || "Signature Invalidated",
						message:
							d.message ||
							"The document has been modified after signing. The signature is no longer valid.",
						details: collectDetails(d),
						reportCardData: d.report_card_data,
					});
				} else {
					renderState("invalid", {
						title: d.title || "Not Recognised",
						message: d.message || "This code doesn't match any record in our system.",
					});
				}
			})
			.catch(function (err) {
				if (err && err.message === "rate_limited") return;
				renderState("invalid", {
					title: "Verification Unavailable",
					message:
						"The verification service could not be reached. Please try again shortly.",
				});
			});
	}

	function collectDetails(d) {
		var pairs = [];
		if (d.ref_doctype) pairs.push(["Document Type", d.ref_doctype, true]);
		if (d.ref_docname) pairs.push(["Reference", d.ref_docname, true]);
		if (d.signed_on) pairs.push(["Signed On", d.signed_on, true]);
		if (d.signed_by_name) pairs.push(["Signed By", d.signed_by_name, true]);
		if (d.unique_id) pairs.push(["Verification ID", d.unique_id, false]);
		if (d.stored_hash) pairs.push(["Signed Hash", d.stored_hash, false]);
		if (d.current_hash) pairs.push(["Current Hash", d.current_hash, false]);
		return pairs;
	}

	// ---- report card renderer -----------------------------------------

	// Grade badge thresholds \u2014 mirror the print format's scale.
	function gradeFor(pct) {
		if (pct == null) return null;
		var p = Number(pct);
		if (p >= 95) return { label: "A+", cls: "g-ap" };
		if (p >= 90) return { label: "A", cls: "g-a" };
		if (p >= 85) return { label: "B+", cls: "g-bp" };
		if (p >= 80) return { label: "B", cls: "g-b" };
		if (p >= 70) return { label: "C", cls: "g-c" };
		if (p >= 60) return { label: "D", cls: "g-d" };
		return { label: "F", cls: "g-f" };
	}

	function makeStat(valueText, labelText, cls) {
		var box = document.createElement("div");
		box.className = cls;
		var v = document.createElement("span");
		v.className = cls === "rc-rank" ? "rc-rank-value" : "rc-avg-value";
		v.textContent = valueText;
		var l = document.createElement("span");
		l.className = cls === "rc-rank" ? "rc-rank-label" : "rc-avg-label";
		l.textContent = labelText;
		box.appendChild(v);
		box.appendChild(l);
		return box;
	}

	function makeCoursesTable(courses) {
		var table = document.createElement("table");
		table.className = "rc-table";
		var thead = document.createElement("thead");
		var htr = document.createElement("tr");
		["Subject", "Score", "Grade"].forEach(function (h) {
			var th = document.createElement("th");
			th.textContent = h;
			htr.appendChild(th);
		});
		thead.appendChild(htr);
		table.appendChild(thead);

		var tbody = document.createElement("tbody");
		courses.forEach(function (c) {
			var tr = document.createElement("tr");

			var tdSubject = document.createElement("td");
			tdSubject.textContent = c.course || "";
			tr.appendChild(tdSubject);

			var tdScore = document.createElement("td");
			tdScore.textContent =
				(c.score != null ? Number(c.score).toFixed(0) : "-") +
				" / " +
				(c.maximum != null ? Number(c.maximum).toFixed(0) : "-");
			tr.appendChild(tdScore);

			var tdGrade = document.createElement("td");
			var g = gradeFor(c.percentage);
			if (g) {
				var badge = document.createElement("span");
				badge.className = "rc-grade-badge " + g.cls;
				badge.textContent = g.label;
				tdGrade.appendChild(badge);
			} else {
				tdGrade.textContent = "-";
			}
			tr.appendChild(tdGrade);

			tbody.appendChild(tr);
		});
		table.appendChild(tbody);
		return table;
	}

	function makeRemark(label, text) {
		var block = document.createElement("div");
		block.className = "rc-remark";
		var strong = document.createElement("strong");
		strong.textContent = label + " ";
		block.appendChild(strong);
		block.appendChild(document.createTextNode(text));
		return block;
	}

	// Render one term/year block: title, average + rank, courses, remarks.
	function makeReportSection(opts) {
		var section = document.createElement("div");
		section.className = "rc-section";

		var head = document.createElement("div");
		head.className = "rc-section-head";
		head.textContent = opts.title;
		section.appendChild(head);

		var summary = document.createElement("div");
		summary.className = "rc-summary";
		if (opts.average != null) {
			summary.appendChild(
				makeStat(Number(opts.average).toFixed(1) + "%", opts.averageLabel, "rc-avg")
			);
		}
		if (opts.rank != null) {
			summary.appendChild(makeStat(String(opts.rank), "Rank", "rc-rank"));
		}
		if (summary.childNodes.length) section.appendChild(summary);

		if (opts.courses && opts.courses.length) {
			section.appendChild(makeCoursesTable(opts.courses));
		}

		(opts.remarks || []).forEach(function (r) {
			if (r[1]) section.appendChild(makeRemark(r[0], r[1]));
		});

		return section;
	}

	function renderReportCard(data) {
		var parsed;
		try {
			parsed = typeof data === "string" ? JSON.parse(data) : data;
		} catch (_e) {
			return null;
		}

		var hasSections =
			(parsed.semesters && parsed.semesters.length) ||
			(parsed.year_reports && parsed.year_reports.length);
		if (!hasSections && !(parsed.courses && parsed.courses.length)) return null;

		var el = document.createElement("div");
		el.className = "report-card";

		// Header: student name + ID + grade/section
		var header = document.createElement("div");
		header.className = "rc-header";
		var title = document.createElement("h4");
		title.className = "rc-title";
		title.textContent = parsed.student_name || "Report Card";
		header.appendChild(title);
		var meta = document.createElement("div");
		meta.className = "rc-meta";
		var metaItems = [];
		if (parsed.student_id) metaItems.push("ID: " + parsed.student_id);
		if (parsed.student_group) metaItems.push("Grade: " + parsed.student_group);
		if (parsed.academic_year) metaItems.push(parsed.academic_year);
		meta.textContent = metaItems.join(" \u00b7 ");
		header.appendChild(meta);
		el.appendChild(header);

		// Semester sections
		(parsed.semesters || []).forEach(function (sem) {
			var titleParts = [];
			if (sem.academic_term) titleParts.push(sem.academic_term);
			if (sem.academic_year) titleParts.push(sem.academic_year);
			el.appendChild(
				makeReportSection({
					title: titleParts.join(" \u2014 ") || "Semester",
					average: sem.term_average,
					averageLabel: "Average",
					rank: sem.rank_in_group,
					courses: sem.courses,
					remarks: [
						["1st Semester Remarks:", sem.first_semester_remarks],
						["2nd Semester Remarks:", sem.second_semester_remarks],
						["Final Result:", sem.final_result],
					],
				})
			);
		});

		// Year report sections
		(parsed.year_reports || []).forEach(function (yr) {
			el.appendChild(
				makeReportSection({
					title: "Year Report" + (yr.academic_year ? " \u2014 " + yr.academic_year : ""),
					average: yr.year_average,
					averageLabel: "Year Average",
					rank: yr.rank_in_group,
					courses: yr.courses,
				})
			);
		});

		// Legacy flat single-term snapshot fallback.
		if (!hasSections && parsed.courses && parsed.courses.length) {
			el.appendChild(
				makeReportSection({
					title: parsed.academic_term || "Results",
					average: parsed.term_average,
					averageLabel: "Average",
					rank: parsed.rank_in_group,
					courses: parsed.courses,
				})
			);
		}

		return el;
	}

	// ---- render --------------------------------------------------------

	function renderLoading() {
		$result.hidden = false;
		$result.textContent = "";
		var el = document.createElement("div");
		el.className = "state state-muted";
		el.innerHTML =
			'<div class="state-icon" aria-hidden="true">' +
			'<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
			'<circle cx="12" cy="12" r="10"></circle><path d="M12 6v6l4 2"></path>' +
			"</svg></div>";
		var title = document.createElement("h3");
		title.className = "state-title";
		title.textContent = "Checking\u2026";
		el.appendChild(title);
		$result.appendChild(el);
	}

	function renderState(kind, payload) {
		var templateId =
			kind === "verified"
				? "tpl-verified"
				: kind === "tampered"
				? "tpl-tampered"
				: "tpl-invalid";
		var tpl = document.getElementById(templateId);
		var node = tpl.content.firstElementChild.cloneNode(true);

		if (payload.title) {
			var t = node.querySelector(".state-title");
			if (t) t.textContent = payload.title;
		}
		var msg = node.querySelector(".state-message");
		if (msg) msg.textContent = payload.message || "";

		var dl = node.querySelector(".details");
		if (dl) {
			if (payload.details && payload.details.length) {
				payload.details.forEach(function (p) {
					var dt = document.createElement("dt");
					dt.textContent = p[0];
					var dd = document.createElement("dd");
					dd.textContent = p[1];
					if (p[2]) dd.className = "plain";
					dl.appendChild(dt);
					dl.appendChild(dd);
				});
			} else {
				dl.remove();
			}
		}

		// Inject report card display for verified/tampered states
		if (payload.reportCardData) {
			var rcEl = renderReportCard(payload.reportCardData);
			if (rcEl) {
				var wrapper = document.createElement("div");
				wrapper.className = "report-card-wrap";
				wrapper.appendChild(rcEl);
				var again = node.querySelector(".again");
				if (again && again.parentNode) {
					again.parentNode.insertBefore(wrapper, again);
				} else {
					node.appendChild(wrapper);
				}
			}
		}

		var again = node.querySelector(".again");
		if (again) again.addEventListener("click", resetForNext);

		$result.hidden = false;
		$result.textContent = "";
		$result.appendChild(node);
		$result.scrollIntoView({ behavior: "smooth", block: "nearest" });
	}

	function resetForNext() {
		$result.hidden = true;
		$result.textContent = "";
		$input.value = "";
		window.scrollTo({ top: 0, behavior: "smooth" });
	}
})();