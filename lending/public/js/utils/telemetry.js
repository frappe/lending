frappe.provide("lending.telemetry");

// Lending workspace shown on the desk sidebar.
const LENDING_WORKSPACES = new Set(["Lending"]);

// Key lending doctypes worth tracking navigation into. Kept explicit so we only
// ever emit lending-relevant events and never generic desk traffic.
const LENDING_DOCTYPES = new Set([
	"Loan Lead",
	"Loan Application",
	"Loan",
	"Loan Product",
	"Loan Disbursement",
	"Loan Repayment",
	"Loan Repayment Schedule",
	"Loan Demand",
	"Loan Interest Accrual",
	"Loan Restructure",
	"Loan Adjustment",
	"Loan Write Off",
	"Loan Refund",
	"Loan Security",
	"Loan Security Type",
	"Loan Security Price",
	"Loan Security Assignment",
	"Loan Partner",
	"Collection Case",
	"Dunning Rule",
	"Decision Strategy",
	"Scorecard",
	"Process Loan Interest Accrual",
	"Process Loan Demand",
	"Process Loan Classification",
	"Bulk Repayment Log",
	"Loan Balance Adjustment",
	"Loan Transfer",
	"Loan Security Release",
	"Loan Security Deposit",
	"Loan Category",
	"Loan Classification",
	"Loan Document Type",
	"Loan Purpose",
	"Loan Decision",
	"Credit Bureau Report",
	"Loan NPA Log",
	"Loan Freeze Log",
	"Loan Demand Offset Order",
	"Process Collection Dunning",
	"Process Loan Accounting",
	"Process Loan Security Shortfall",
	"Process Loan Statement of Accounts",
	"Loan Repayment Repost",
	"Loan Accrual Repost",
]);

// Lending reports. Scoped explicitly so we learn which reports get used, without
// capturing unrelated desk report traffic.
const LENDING_REPORTS = new Set([
	"Loan Outstanding Report",
	"Past Cashflow Report",
	"Future Cashflow Report",
	"Loan Repayment and Closure",
	"Loan Security Status",
	"Loan Security Exposure",
	"Applicant-Wise Loan Security Exposure",
	"Loan Security Ledger",
	"Loan Statement of Account",
	"Disbursement Analysis Report",
	"ALM Audit Report",
]);

function lending_capture(event, props) {
	if (!frappe.telemetry?.enabled) return;
	try {
		frappe.telemetry.capture(event, "lending", props || {});
	} catch (e) {
		// telemetry must never break navigation
	}
}

// Turn the current route into a semantic lending event, or null if it's not lending.
function classify(route) {
	if (!route || !route.length) return null;
	const head = route[0];

	if (head === "Workspaces") {
		// ["Workspaces", Name] or ["Workspaces", "private", Name]
		const name = route[route.length - 1];
		return LENDING_WORKSPACES.has(name)
			? { event: "viewed_workspace", props: { workspace: name } }
			: null;
	}

	if (head === "List" && LENDING_DOCTYPES.has(route[1])) {
		return { event: "viewed_list", props: { doctype: route[1], view: route[2] || "List" } };
	}

	if (head === "Form" && LENDING_DOCTYPES.has(route[1])) {
		const name = route[2];
		const is_new = typeof name === "string" && name.startsWith("new-");
		return { event: is_new ? "started_creating" : "viewed_form", props: { doctype: route[1] } };
	}

	if ((head === "query-report" || head === "report") && LENDING_REPORTS.has(route[1])) {
		return { event: "viewed_report", props: { report: route[1] } };
	}

	return null;
}

// The draft the user is currently sitting on, if it is an unsaved lending document.
let pending_draft = null;

// How far into the form the user got, as a count. Values themselves are never
// read, only whether each field holds something.
function count_filled_fields(doctype, draft) {
	try {
		const meta = frappe.get_meta(doctype);
		if (!meta) return null;
		return meta.fields.filter((df) => {
			if (frappe.model.no_value_type.includes(df.fieldtype)) return false;
			const value = draft[df.fieldname];
			return value !== undefined && value !== null && value !== "";
		}).length;
	} catch (e) {
		return null;
	}
}

// A saved document is renamed away from its `new-…` key, so a draft still
// sitting in `locals` when we leave the route was abandoned rather than saved.
function resolve_pending_draft(route) {
	if (!pending_draft) return;

	const { doctype, name } = pending_draft;
	if (route[0] === "Form" && route[1] === doctype && route[2] === name) return;

	const draft = locals?.[doctype]?.[name];
	if (draft) {
		lending_capture("creation_abandoned", {
			doctype,
			fields_filled: count_filled_fields(doctype, draft),
		});
	}
	pending_draft = null;
}

function remember_pending_draft(route) {
	const name = route[2];
	const is_new =
		route[0] === "Form" &&
		LENDING_DOCTYPES.has(route[1]) &&
		typeof name === "string" &&
		name.startsWith("new-");

	pending_draft = is_new ? { doctype: route[1], name } : null;
}

function track_route() {
	const route = frappe.get_route() || [];
	resolve_pending_draft(route);

	const hit = classify(route);
	if (hit) lending_capture(hit.event, hit.props);

	remember_pending_draft(route);
}

function track_landing() {
	try {
		if (sessionStorage.getItem("lending_landing_tracked")) return;
		sessionStorage.setItem("lending_landing_tracked", "1");
	} catch (e) {
		// private mode / storage disabled: still capture once
	}

	const route = frappe.get_route() || [];
	const hit = classify(route);
	lending_capture("landed_on_desk", {
		route_type: route[0] || "",
		landed_in_lending: Boolean(hit),
		...(hit ? hit.props : {}),
	});
}

$(document).on("app_ready", function () {
	if (!frappe.telemetry?.enabled) return;

	// Defer to the next tick so the first route is fully resolved.
	frappe.after_ajax(() => {
		track_landing();
		track_route();
		frappe.router.on("change", track_route);
	});

	// Closing the tab on a half-filled form is abandonment too. Best effort: the
	// event is dropped if the provider has not flushed, so treat it as a floor.
	window.addEventListener("pagehide", () => resolve_pending_draft([]), { capture: true });
});
