// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Loan Decision", {
	setup(frm) {
		frm.set_query("strategy", () => ({
			filters: { strategy_type: "Underwriting", disabled: 0 },
		}));

		frm.set_query("bureau_report", () => {
			const filters = { docstatus: 1 };

			if (frm.doc.applicant_type && frm.doc.applicant) {
				filters.applicant_type = frm.doc.applicant_type;
				filters.applicant = frm.doc.applicant;
			}

			return { filters };
		});
	},

	refresh(frm) {
		if (!frm.doc.loan_application) return;

		frm.add_custom_button(__("Test Run"), () => test_run(frm));
	},
});

function test_run(frm) {
	frappe.call({
		method: "lending.loan_origination.decisioning.compare_strategies",
		args: {
			loan_application: frm.doc.loan_application,
			// What is on the form, so the dry run compares what this decision would.
			strategy: frm.doc.strategy,
			scorecard: frm.doc.scorecard,
			bureau_report: frm.doc.bureau_report,
		},
		freeze: true,
		freeze_message: __("Running every strategy…"),
		callback: ({ message }) => message && show_comparison(message),
	});
}

function show_comparison(result) {
	const dialog = new frappe.ui.Dialog({
		title: __("Test Run"),
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "comparison", options: render(result) }],
		primary_action_label: __("Close"),
		primary_action: () => dialog.hide(),
	});

	dialog.show();
}

function render(result) {
	return `
		<p class="text-muted small">
			${__("Nothing below has been saved. No Loan Decision was created and {0} was not touched.", [
				escape(result.loan_application),
			])}
		</p>
		${render_applicant(result)}
		${render_strategies(result)}
	`;
}

function render_applicant(result) {
	const facts = [
		[__("Scorecard"), escape(result.scorecard) || dash()],
		[__("Bureau Report"), escape(result.bureau_report) || dash()],
		[__("Bureau Score"), result.bureau_score || dash()],
		[__("Score"), result.score],
		[__("Grade"), escape(result.grade) || dash()],
	];

	return `
		<h5>${__("What the engine sees")}</h5>
		<p class="text-muted small">
			${__("The same for every strategy below. Only the rules differ, so each log covers its rules alone.")}
		</p>
		<table class="table table-bordered small">
			<tbody>
				${facts.map(([label, value]) => `<tr><td width="30%">${label}</td><td>${value}</td></tr>`).join("")}
				<tr>
					<td>${__("Variables")}</td>
					<td>${render_variables(result.variable_snapshot)}</td>
				</tr>
			</tbody>
		</table>
	`;
}

function render_variables(snapshot) {
	let variables;

	try {
		variables = JSON.parse(snapshot || "{}");
	} catch (e) {
		return dash();
	}

	const names = Object.keys(variables).sort();

	if (!names.length) {
		return `<span class="text-danger">${__("Nothing was collected for this applicant.")}</span>`;
	}

	return names
		.map((name) => `<code>${escape(name)}</code> ${escape(String(variables[name]))}`)
		.join("&nbsp; · &nbsp;");
}

function render_strategies(result) {
	if (!result.rows.length) {
		return `
			<h5>${__("Strategies")}</h5>
			<p class="text-danger">
				${__("No enabled Underwriting strategy applies to {0}, so this application cannot be decided at all.", [
					escape(result.loan_product),
				])}
			</p>
		`;
	}

	return `
		<h5>${__("Strategies")}</h5>
		<p class="text-muted small">
			${__("Every enabled Underwriting strategy that applies to {0}. Strategies for other loan products are left out because they can never run here.", [
				escape(result.loan_product),
			])}
		</p>
		<div class="table-responsive">
			<table class="table table-bordered small">
				<thead>
					<tr>
						<th>${__("Strategy")}</th>
						<th>${__("Priority")}</th>
						<th>${__("Decision")}</th>
						<th>${__("Reason Codes")}</th>
						<th>${__("Recommended Terms")}</th>
						<th>${__("Log")}</th>
					</tr>
				</thead>
				<tbody>${result.rows.map(render_row).join("")}</tbody>
			</table>
		</div>
	`;
}

function render_row(row) {
	const name = row.selected
		? `<b>${escape(row.strategy)}</b><br><span class="text-muted">${__("this is the one that runs")}</span>`
		: escape(row.strategy);

	return `
		<tr>
			<td>${name}</td>
			<td>${row.priority || 0}</td>
			<td>${render_decision(row.decision)}</td>
			<td>${row.reason_codes.map(escape).join("<br>") || dash()}</td>
			<td>${render_terms(row)}</td>
			<td>${render_log(row.decision_log)}</td>
		</tr>
	`;
}

function render_decision(decision) {
	if (!decision) {
		return `<span class="es-badge">${__("No verdict")}</span>
			<br><span class="text-muted">${__("no rule matched")}</span>`;
	}

	const theme = { Approve: "green", Decline: "red", Refer: "amber" }[decision];

	return `<span class="es-badge" ${theme ? `data-theme="${theme}"` : ""}>${__(decision)}</span>`;
}

function render_terms(row) {
	const terms = [];

	if (row.recommended_roi) {
		terms.push(`${__("Rate")} ${frappe.format(row.recommended_roi, { fieldtype: "Percent" })}`);
	}

	if (row.recommended_amount) {
		terms.push(
			`${__("Amount capped at")} ${frappe.format(row.recommended_amount, { fieldtype: "Currency" })}`
		);
	}

	if (row.recommended_tenure) {
		terms.push(`${__("Tenure capped at")} ${row.recommended_tenure}`);
	}

	return terms.join("<br>") || dash();
}

function render_log(log) {
	if (!log) return dash();

	return `
		<details>
			<summary class="text-muted">${__("Show")}</summary>
			<div style="white-space: pre-wrap">${escape(log)}</div>
		</details>
	`;
}

function escape(value) {
	return value ? frappe.utils.escape_html(String(value)) : "";
}

function dash() {
	return `<span class="text-muted">—</span>`;
}
