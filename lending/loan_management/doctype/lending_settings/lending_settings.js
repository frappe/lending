// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const SWATCHES_METHOD =
	"lending.loan_management.doctype.lending_settings.lending_settings.get_theme_swatches";
const CUSTOM = "Custom";

frappe.ui.form.on("Lending Settings", {
	refresh(frm) {
		load_swatches(frm);
	},

	portal_theme(frm) {
		render_swatches(frm);
	},

	// The Custom card shows the button as the portal will paint it, which can differ from the input.
	portal_primary_color: frappe.utils.debounce((frm) => load_swatches(frm), 300),
	portal_secondary_color: frappe.utils.debounce((frm) => load_swatches(frm), 300),
});

function load_swatches(frm) {
	frappe
		.call(SWATCHES_METHOD, {
			primary_color: frm.doc.portal_primary_color,
			secondary_color: frm.doc.portal_secondary_color,
		})
		.then(({ message }) => {
			frm.theme_swatches = message;
			render_swatches(frm);
		});
}

function render_swatches(frm) {
	const field = frm.fields_dict.portal_theme_swatches;
	if (!field || !frm.theme_swatches) return;

	const cards = Object.entries(frm.theme_swatches).map(([name, swatch]) =>
		swatch_card(name, swatch, name === (frm.doc.portal_theme || CUSTOM))
	);

	field.$wrapper.html(`
		<div style="margin-bottom: var(--margin-sm); color: var(--text-muted); font-size: var(--text-sm);">
			${__("Each swatch shows the portal in light mode, then dark mode.")}
		</div>
		<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px;">
			${cards.join("")}
		</div>
	`);

	field.$wrapper.find("[data-theme-name]").on("click", function () {
		frm.set_value("portal_theme", $(this).attr("data-theme-name"));
	});
}

function swatch_card(name, swatch, selected) {
	const ring = selected
		? "box-shadow: 0 0 0 2px var(--text-color);"
		: "box-shadow: 0 0 0 1px var(--border-color);";
	const body = swatch
		? `<div style="display: flex;">${mode_preview(swatch.light)}${mode_preview(swatch.dark)}</div>`
		: `<div style="height: 64px; display: flex; align-items: center; justify-content: center;
			color: var(--text-muted); font-size: var(--text-xs);">${__("Enter your colours")}</div>`;
	const label = name === CUSTOM ? __("Custom") : __(name);

	return `
		<button type="button" data-theme-name="${frappe.utils.escape_html(name)}" aria-pressed="${selected}"
			style="padding: 0; border: none; border-radius: var(--border-radius-md); overflow: hidden;
			background: var(--card-bg); text-align: left; cursor: pointer; ${ring}">
			${body}
			<div style="padding: 6px 10px; font-size: var(--text-sm); color: var(--text-color);">
				${frappe.utils.escape_html(label)}
			</div>
		</button>
	`;
}

function mode_preview({ page, band, primary, button, ink }) {
	return `
		<div style="flex: 1; background: ${page};">
			<div style="height: 18px; background: ${band}; display: flex; align-items: center; padding: 0 6px;">
				<span style="width: 8px; height: 8px; border-radius: 50%; background: ${primary};"></span>
			</div>
			<div style="padding: 10px 6px 12px;">
				<span style="display: inline-block; padding: 3px 8px; border-radius: 6px;
					background: ${button}; color: ${ink}; font-size: 10px; font-weight: 500;">
					${__("Pay EMI")}
				</span>
			</div>
		</div>
	`;
}
