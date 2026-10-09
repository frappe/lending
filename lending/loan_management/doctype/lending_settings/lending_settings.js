// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const SETTINGS = "lending.loan_management.doctype.lending_settings.lending_settings";
const CUSTOM = "Custom";
const PREVIEW_STYLE_ID = "lending-theme-preview";
const PREVIEW_PARAM = "lending_preview";

// The preview runs in the Desk session, so the portal drops Log out and Appearance from its menu and
// keeps navigation to the made-up borrower's pages; see guardPreview in lending/portal/studio_build/app.py.

const THEME_DESCRIPTIONS = {
	Ocean: __("Two shades of blue"),
	"Navy & Teal": __("Navy header with teal buttons"),
	Forest: __("Deep and bright greens"),
	"Teal & Orange": __("Teal header with orange buttons"),
	Royal: __("Violet header with magenta buttons"),
	Plum: __("Deep and soft purples"),
	Indigo: __("Deep and bright violets"),
	Graphite: __("Charcoal header with blue buttons"),
	[CUSTOM]: __("Define your own palette"),
};

const PREVIEW_PAGES = [
	{ label: __("Account overview"), route: "/borrower-portal/overview" },
	{ label: __("Loan account"), route: "/borrower-portal/loans" },
	{ label: __("Application"), route: "/borrower-portal/applications" },
	{ label: __("Statement of account"), route: "/borrower-portal/statement" },
	{ label: __("Interest certificate"), route: "/borrower-portal/certificate" },
	{ label: __("Personal details"), route: "/borrower-portal/profile" },
	{ label: __("Apply"), route: "/borrower-portal/apply", public_apply: true },
	{ label: __("Track an application"), route: "/borrower-portal/track" },
];

frappe.ui.form.on("Lending Settings", {
	// Runs on load and after every save, when the form matches what the portal has published.
	refresh(frm) {
		frm.portal_published = {
			portal: frm.doc.enable_borrower_portal,
			apply: frm.doc.enable_borrower_portal && frm.doc.enable_public_apply,
		};
		load_swatches(frm);
		sync_preview_button(frm);
		// A save that publishes or unpublishes pages must reload an open preview.
		load_page(frm);
	},

	enable_borrower_portal(frm) {
		load_swatches(frm);
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
	if (!frm.doc.enable_borrower_portal) return;

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

	build_layout(frm, field.$wrapper);

	const chosen = frm.doc.portal_theme || CUSTOM;
	const grid = field.$wrapper.find('[data-region="swatches"]');
	grid.html(
		Object.entries(frm.theme_swatches)
			.map(([name, swatch]) => swatch_card(name, swatch, name === chosen))
			.join("")
	);

	grid.find("[data-theme-name]").on("click", function () {
		frm.set_value("portal_theme", $(this).attr("data-theme-name"));
	});
}

function build_layout(frm, $wrapper) {
	if ($wrapper.find('[data-region="swatches"]').length) return;

	$wrapper.html(`
		<div data-region="swatches" style="display: grid; gap: 16px; margin-bottom: var(--margin-xl);
			grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));"></div>
	`);
}

// The portal's pages are published only when the settings are saved, so an unsaved switch would 404.
function sync_preview_button(frm) {
	const $button = preview_button(frm);
	if (!$button) return;

	const live = Boolean(frm.portal_published?.portal);
	$button.prop("disabled", !live).attr("title", live ? "" : __("Save to publish the portal, then preview it."));
}

// Sits in the section's own heading, whose clicks and Enter otherwise fold the section.
function preview_button(frm) {
	const $head = frm.fields_dict.portal_theme_section?.head;
	if (!$head) return null;

	let $button = $head.find('[data-control="preview"]');
	if ($button.length) return $button;

	$head.css({ display: "flex", "align-items": "center", gap: "4px" });
	$button = $(`
		<button type="button" class="btn btn-sm btn-default" data-control="preview" style="margin-left: auto;">
			${frappe.utils.icon("maximize", "sm")} ${__("Preview")}
		</button>
	`).appendTo($head);

	$button.on("click keydown keyup keypress", (event) => event.stopPropagation());
	$button.on("click", () => open_preview(frm));

	return $button;
}

function swatch_card(name, swatch, selected) {
	const border = selected
		? "border: 1px solid var(--text-color); box-shadow: 0 0 0 1px var(--text-color);"
		: "border: 1px solid var(--border-color); box-shadow: var(--shadow-sm);";
	const label = name === CUSTOM ? __("Custom") : __(name);
	const description = THEME_DESCRIPTIONS[name] || "";

	return `
		<button type="button" data-theme-name="${frappe.utils.escape_html(name)}" aria-pressed="${selected}"
			style="display: block; width: 100%; padding: 16px; text-align: left; cursor: pointer;
				background: var(--card-bg); border-radius: var(--radius); ${border}">
			<div style="display: flex; gap: 10px;">
				${palette_strip(swatch?.light)}
				${palette_strip(swatch?.dark)}
			</div>
			<div style="margin-top: 12px; font-size: var(--text-base); color: var(--text-color);
				font-weight: ${selected ? 600 : 500};">
				${frappe.utils.escape_html(label)}
			</div>
			<div style="margin-top: 2px; font-size: var(--text-sm); color: var(--text-muted);">
				${frappe.utils.escape_html(description)}
			</div>
		</button>
	`;
}

// Primary, button and page colour for one mode; greys stand in until Custom has colours.
function palette_strip(mode) {
	const colours = mode
		? [mode.primary, mode.button, mode.page]
		: ["var(--gray-200)", "var(--gray-300)", "var(--gray-400)"];

	return `
		<div style="flex: 1; display: flex; height: 40px; border-radius: var(--radius);
			overflow: hidden; border: 1px solid var(--border-color);">
			${colours.map((colour) => `<div style="flex: 1; background: ${colour};"></div>`).join("")}
		</div>
	`;
}

function open_preview(frm) {
	if (frm.theme_preview || !frm.portal_published?.portal) return;

	const $overlay = $(`
		<div role="dialog" aria-modal="true" aria-label="${__("Portal theme preview")}"
			style="position: fixed; inset: 0; z-index: 1050; display: flex; flex-direction: column;
				background: var(--bg-color);">
			${preview_toolbar(frm)}
			<iframe style="flex: 1; width: 100%; border: 0;"></iframe>
		</div>
	`).appendTo(document.body);

	const on_key = (event) => event.key === "Escape" && close_preview(frm);
	frm.theme_preview = { $overlay, mode: "light", on_key };
	$(document).on("keydown", on_key);
	$("body").css("overflow", "hidden");
	// The overlay sits on <body>, so Back would otherwise leave it over the next page.
	frappe.router.once("change", () => close_preview(frm));

	$overlay.find('[data-control="page"]').on("change", () => load_page(frm));
	$overlay.find('[data-control="close"]').on("click", () => close_preview(frm));
	$overlay.find("[data-mode]").on("click", function () {
		frm.theme_preview.mode = $(this).attr("data-mode");
		apply_preview(frm);
	});

	load_page(frm);
}

function preview_toolbar(frm) {
	const theme = frm.doc.portal_theme || CUSTOM;
	const unsaved = frm.is_dirty() ? frappe.ui.badge.html({ label: __("Not saved"), theme: "orange" }) : "";

	return `
		<div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;
			height: 48px; flex-shrink: 0; padding: 0 12px 0 16px; background: var(--card-bg);
			border-bottom: 1px solid var(--border-color); box-shadow: var(--shadow-sm); position: relative;">
			<div style="display: flex; align-items: center; gap: 8px; min-width: 0;">
				<span style="font-weight: 600; color: var(--text-color);"
					title="${__("Filled with a made-up borrower")}">${__("Preview")}</span>
				${frappe.ui.badge.html({ label: theme === CUSTOM ? __("Custom") : __(theme) })}
				${unsaved}
				<select class="form-control input-xs" data-control="page" aria-label="${__("Page")}"
					style="width: 220px; margin-left: 8px;"></select>
			</div>
			<div style="display: flex; align-items: center; gap: 8px;">
				<div class="btn-group" role="group" aria-label="${__("Appearance")}">
					${mode_button("light", "sun", __("Light"))}
					${mode_button("dark", "moon", __("Dark"))}
				</div>
				<button type="button" class="btn btn-xs btn-default icon-btn" data-control="close"
					title="${__("Close")}" aria-label="${__("Close")}">
					${frappe.utils.icon("x", "sm")}
				</button>
			</div>
		</div>
	`;
}

function mode_button(mode, icon, label) {
	return `
		<button type="button" class="btn btn-xs btn-default" data-mode="${mode}"
			style="display: inline-flex; align-items: center; gap: 4px;">
			${frappe.utils.icon(icon, "sm")} ${label}
		</button>
	`;
}

function close_preview(frm) {
	const preview = frm.theme_preview;
	if (!preview) return;

	$(document).off("keydown", preview.on_key);
	$("body").css("overflow", "");
	preview.$overlay.remove();
	delete frm.theme_preview;
}

function load_page(frm) {
	const $overlay = frm.theme_preview?.$overlay;
	if (!$overlay) return;

	if (!frm.portal_published?.portal) {
		close_preview(frm);
		return;
	}

	const $picker = $overlay.find('[data-control="page"]');
	const chosen = $picker.val();
	const pages = published_pages(frm);
	$picker.html(
		pages
			.map((page) => `<option value="${page.route}">${frappe.utils.escape_html(page.label)}</option>`)
			.join("")
	);
	$picker.val(pages.some((page) => page.route === chosen) ? chosen : pages[0]?.route);

	const frame = $overlay.find("iframe")[0];
	frame.onload = () => {
		watch_portal_styles(frame.contentDocument);
		apply_preview(frm);
	};
	// The flag rides on the page's own URL, so its API calls carry it as their Referer; see preview.py.
	frame.src = `${$picker.val()}?${PREVIEW_PARAM}=1`;
}

function published_pages(frm) {
	const published = frm.portal_published || {};
	return PREVIEW_PAGES.filter((page) => !page.public_apply || published.apply);
}

// Fetch the unsaved theme's stylesheet and lay it over the portal page in the frame.
function apply_preview(frm) {
	const preview = frm.theme_preview;
	if (!preview) return;

	const { $overlay, mode } = preview;
	$overlay.find("[data-mode]").each(function () {
		$(this).toggleClass("active", $(this).attr("data-mode") === mode);
	});

	const doc = $overlay.find("iframe")[0]?.contentDocument;
	if (!doc?.documentElement) return;

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
