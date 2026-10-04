// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const SETTINGS = "lending.loan_management.doctype.lending_settings.lending_settings";
const CUSTOM = "Custom";
const PREVIEW_STYLE_ID = "lending-theme-preview";

const PREVIEW_PAGES = [
	{ label: __("Account overview"), route: "/borrower-portal/overview" },
	{ label: __("Loan account"), route: "/borrower-portal/loans" },
	{ label: __("Apply"), route: "/borrower-portal/apply" },
	{ label: __("Track an application"), route: "/borrower-portal/track" },
];

frappe.ui.form.on("Lending Settings", {
	refresh(frm) {
		load_swatches(frm);
		frm.add_custom_button(__("Preview Portal"), () => open_preview(frm));
	},

	portal_theme(frm) {
		render_swatches(frm);
		refresh_preview(frm);
	},

	// The Custom swatch shows the button the portal will paint, which can differ from the input.
	portal_primary_color: frappe.utils.debounce((frm) => {
		load_swatches(frm);
		refresh_preview(frm);
	}, 300),
	portal_secondary_color: frappe.utils.debounce((frm) => {
		load_swatches(frm);
		refresh_preview(frm);
	}, 300),
});

function load_swatches(frm) {
	frappe
		.call(`${SETTINGS}.get_theme_swatches`, {
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

	const chosen = frm.doc.portal_theme || CUSTOM;
	const tiles = Object.entries(frm.theme_swatches).map(([name, swatch]) =>
		swatch_tile(name, swatch, name === chosen)
	);

	field.$wrapper.html(`
		<div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;
			margin-bottom: var(--margin-md);">
			<span style="color: var(--text-muted); font-size: var(--text-sm);">
				${__("Each square shows the portal in light mode above and dark mode below.")}
			</span>
			<button type="button" class="btn btn-default btn-xs" data-action="preview">
				${frappe.utils.icon("view", "xs")} ${__("Preview Portal")}
			</button>
		</div>
		<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 16px;">
			${tiles.join("")}
		</div>
	`);

	field.$wrapper.find("[data-theme-name]").on("click", function () {
		frm.set_value("portal_theme", $(this).attr("data-theme-name"));
	});
	field.$wrapper.find('[data-action="preview"]').on("click", () => open_preview(frm));
}

function swatch_tile(name, swatch, selected) {
	const ring = selected
		? "box-shadow: 0 0 0 2px var(--card-bg), 0 0 0 4px var(--text-color);"
		: "box-shadow: 0 0 0 1px var(--border-color);";
	const face = swatch
		? `${mini_portal(swatch.light)}${mini_portal(swatch.dark)}`
		: `<div style="height: 100%; display: flex; align-items: center; justify-content: center;
			padding: 8px; text-align: center; color: var(--text-muted); font-size: var(--text-xs);
			background: var(--subtle-fg);">${__("Enter your colours")}</div>`;
	const label = name === CUSTOM ? __("Custom") : __(name);

	return `
		<button type="button" data-theme-name="${frappe.utils.escape_html(name)}" aria-pressed="${selected}"
			title="${frappe.utils.escape_html(label)}"
			style="padding: 0; border: none; background: none; cursor: pointer; text-align: left;">
			<div style="aspect-ratio: 1 / 1; border-radius: 10px; overflow: hidden; display: flex;
				flex-direction: column; ${ring}">
				${face}
			</div>
			<div style="margin-top: 8px; font-size: var(--text-sm); color: var(--text-color);
				font-weight: ${selected ? 600 : 400};">
				${frappe.utils.escape_html(label)}
			</div>
		</button>
	`;
}

// One half of a tile: a sidebar, a header band and a button, as the portal paints them.
function mini_portal({ page, band, primary, button, ink }) {
	return `
		<div style="flex: 1; display: flex; background: ${page};">
			<div style="width: 22%; background: ${band}; padding: 6px 0 0 5px;">
				<div style="width: 7px; height: 7px; border-radius: 2px; background: ${primary};"></div>
			</div>
			<div style="flex: 1; display: flex; flex-direction: column;">
				<div style="height: 22%; background: ${band};"></div>
				<div style="flex: 1; display: flex; align-items: center; justify-content: center;">
					<div style="width: 58%; height: 11px; border-radius: 3px; background: ${button};
						display: flex; align-items: center; justify-content: center;">
						<div style="width: 55%; height: 2px; border-radius: 1px; background: ${ink};"></div>
					</div>
				</div>
			</div>
		</div>
	`;
}

function open_preview(frm) {
	if (!frm.doc.enable_borrower_portal) {
		frappe.msgprint(__("Enable the borrower portal to preview it."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Portal Preview"),
		size: "extra-large",
		fields: [
			{
				fieldname: "page",
				fieldtype: "Select",
				label: __("Page"),
				options: PREVIEW_PAGES.map((page) => ({ label: page.label, value: page.route })),
				default: PREVIEW_PAGES[0].route,
				change: () => load_page(frm),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Mode"),
				options: [
					{ label: __("Light"), value: "light" },
					{ label: __("Dark"), value: "dark" },
				],
				default: "light",
				change: () => apply_preview(frm),
			},
			{ fieldtype: "Section Break" },
			{ fieldname: "frame", fieldtype: "HTML" },
		],
	});

	dialog.fields_dict.frame.$wrapper.html(`
		<div style="font-size: var(--text-sm); color: var(--text-muted); margin-bottom: 8px;">
			${__("The live portal with the colours on this form, saved or not. You see it as your own user.")}
		</div>
		<iframe style="width: 100%; height: 68vh; border: 1px solid var(--border-color);
			border-radius: var(--border-radius-md); background: var(--card-bg);"></iframe>
	`);

	frm.theme_preview = dialog;
	dialog.$wrapper.on("hidden.bs.modal", () => {
		if (frm.theme_preview === dialog) frm.theme_preview = null;
	});
	dialog.show();
	load_page(frm);
}

function load_page(frm) {
	const dialog = frm.theme_preview;
	if (!dialog) return;

	const frame = dialog.fields_dict.frame.$wrapper.find("iframe")[0];
	frame.onload = () => {
		watch_portal_styles(frame.contentDocument);
		apply_preview(frm);
	};
	frame.src = dialog.get_value("page");
}

// Fetch the unsaved theme's stylesheet and lay it over the portal page in the frame.
function apply_preview(frm) {
	const dialog = frm.theme_preview;
	const doc = dialog?.fields_dict.frame.$wrapper.find("iframe")[0]?.contentDocument;
	if (!doc?.documentElement) return;

	const mode = dialog.get_value("mode");
	doc.documentElement.dataset.appearance = mode;
	doc.documentElement.dataset.theme = mode;

	frappe
		.call(`${SETTINGS}.get_theme_preview`, {
			theme: frm.doc.portal_theme,
			primary_color: frm.doc.portal_primary_color,
			secondary_color: frm.doc.portal_secondary_color,
		})
		.then(({ message }) => {
			let style = doc.getElementById(PREVIEW_STYLE_ID);
			if (!style) {
				style = doc.createElement("style");
				style.id = PREVIEW_STYLE_ID;
				doc.body.appendChild(style);
			}
			// brand_style wraps its rules in <div><style>; only the rules are wanted here.
			style.textContent = $("<div>").html(message || "").find("style").text();
		});
}

const refresh_preview = frappe.utils.debounce((frm) => apply_preview(frm), 300);

// The page renders its own saved theme as it navigates; switch each copy off so only the preview paints.
function watch_portal_styles(doc) {
	if (!doc?.body) return;

	const silence = () =>
		doc.querySelectorAll(".borrower-portal style").forEach((style) => {
			style.media = "not all";
		});

	silence();
	new MutationObserver(silence).observe(doc.body, { childList: true, subtree: true });
}
