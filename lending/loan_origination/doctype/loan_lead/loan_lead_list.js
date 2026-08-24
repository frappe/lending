frappe.listview_settings["Loan Lead"] = {
	onload(listview) {
		listview.page.add_actions_menu_item(__("Send OTP to All"), () => {
			const loan_leads = listview.get_checked_items(true);

			if (!loan_leads.length) {
				frappe.msgprint(__("Select one or more leads first."));
				return;
			}

			frappe.prompt(
				[
					{
						fieldname: "email",
						label: __("Email"),
						fieldtype: "Check",
					},
					{
						fieldname: "sms",
						label: __("SMS"),
						fieldtype: "Check",
					},
				],
				({ email, sms }) => {
					const mediums = [email && "Email", sms && "SMS"].filter(Boolean);

					if (!mediums.length) {
						frappe.msgprint(__("Select at least one medium."));
						return;
					}

					frappe.dom.freeze(__("Sending OTP..."));

					Promise.all(
						mediums.map((medium) =>
							frappe
								.xcall(
									"lending.loan_origination.doctype.loan_lead.loan_lead.bulk_send_otp",
									{ loan_leads, medium }
								)
								.then((result) => ({ medium, ...result }))
						)
					)
						.then((outcomes) => {
							show_bulk_otp_result(outcomes, loan_leads.length);
							listview.refresh();
						})
						.finally(() => frappe.dom.unfreeze());
				},
				__("Send OTP to All"),
				__("Send")
			);
		});
	},
};

function show_bulk_otp_result(outcomes, total) {
	const results = outcomes.map((outcome) => describe_medium_outcome(outcome, total));

	if (results.every((r) => r.ok)) {
		frappe.show_alert({
			message: results.map((r) => frappe.utils.escape_html(r.summary)).join(" · "),
			indicator: "green",
		});
		return;
	}

	// Red only when nothing went out at all: a partly delivered batch is a report,
	// not an error.
	frappe.msgprint({
		title: __("Send OTP"),
		indicator: results.some((r) => r.ok) ? "blue" : "red",
		message: `<div style="display: flex; flex-direction: column; gap: 8px;">
			${results.map(render_medium_result).join("")}
		</div>`,
	});
}

function render_medium_result({ ok, summary, details }) {
	// Escaped here because both summary and details carry server text.
	const escape = frappe.utils.escape_html;

	const lines = [
		`<div><span class="indicator ${ok ? "green" : "red"}">${escape(summary)}</span></div>`,
	];

	for (const detail of details || []) {
		lines.push(
			`<div class="text-muted" style="margin-left: 16px;">${escape(detail)}</div>`
		);
	}

	return `<div>${lines.join("")}</div>`;
}

function describe_medium_outcome({ medium, sent = [], failed = [] }, total) {
	if (!failed.length) {
		return { ok: true, summary: __("{0}: sent to all {1} leads.", [medium, total]) };
	}

	const leads_by_reason = group_by_reason(failed);

	// A single reason that stopped the whole batch is the whole story for this medium.
	if (!sent.length && leads_by_reason.size === 1) {
		return { ok: false, summary: `${medium}: ${leads_by_reason.keys().next().value}` };
	}

	return {
		ok: false,
		summary: sent.length
			? __("{0}: sent to {1} of {2} leads.", [medium, sent.length, total])
			: __("{0}: not sent.", [medium]),
		details: Array.from(leads_by_reason, ([error, leads]) =>
			leads.length === total ? error : name_affected_leads(error, leads)
		),
	};
}

function name_affected_leads(error, leads) {
	return __("{0} for {1}.", [error.replace(/\.\s*$/, ""), leads.join(", ")]);
}

function group_by_reason(failed) {
	const leads_by_reason = new Map();

	for (const { loan_lead, error } of failed) {
		if (!leads_by_reason.has(error)) leads_by_reason.set(error, []);
		leads_by_reason.get(error).push(loan_lead);
	}

	return leads_by_reason;
}
