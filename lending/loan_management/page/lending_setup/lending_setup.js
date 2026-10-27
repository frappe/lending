// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.pages["lending-setup"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Lending Setup"),
		single_column: true,
	});
	$(`<div class="lending-setup">
		<div class="lending-setup-head">
			<div class="lending-setup-title">${__("What do you lend against?")}</div>
			<div class="lending-setup-subtitle">${__(
				"Pick one to see its setup steps. You can come back for another."
			)}</div>
		</div>
		<div class="lending-setup-kinds"></div>
	</div>`).appendTo(page.main);
};

frappe.pages["lending-setup"].on_page_show = function (wrapper) {
	const $kinds = $(wrapper).find(".lending-setup-kinds");
	frappe
		.xcall("lending.loan_management.page.lending_setup.lending_setup.get_collateral_kinds")
		.then((kinds) => $kinds.empty().append(kinds.map(make_kind)));
};

function make_kind(kind) {
	const ready = !!kind.workspace;
	const $kind = $(`<button type="button" class="lending-setup-kind">
		<span class="lending-setup-icon">${frappe.utils.icon(kind.icon, "md")}</span>
		<span class="lending-setup-text">
			<span class="lending-setup-label"></span>
			<span class="lending-setup-description"></span>
		</span>
		<span class="lending-setup-status"></span>
	</button>`);
	$kind.find(".lending-setup-label").text(kind.label);
	$kind.find(".lending-setup-description").text(kind.description);

	if (!ready) {
		$kind.prop("disabled", true);
		return $kind;
	}

	const status =
		kind.done === kind.total
			? __("Set up")
			: __("{0} of {1} steps done", [kind.done, kind.total]);
	$kind.find(".lending-setup-status").append(
		$("<span></span>").text(status),
		frappe.utils.icon("arrow-right", "sm")
	);
	$kind.on("click", () => frappe.set_route(`/desk/${frappe.router.slug(kind.workspace)}`));
	return $kind;
}
