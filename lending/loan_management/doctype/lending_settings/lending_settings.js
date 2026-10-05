// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const SETTINGS = "lending.loan_management.doctype.lending_settings.lending_settings";
const CUSTOM = "Custom";
const PREVIEW_STYLE_ID = "lending-theme-preview";
const PREVIEW_PARAM = "lending_preview";
const SCREEN_STYLE_ID = "lending-preview-screen";

// The portal renders at a desktop size, then shrinks to the form's width, so it never falls to its narrow layout.
// It cannot be clicked: it runs in the Desk session, where Log out or Appearance would act on the admin,
// and a link would leave the made-up borrower's pages.
const SCREEN = { width: 1440, height: 900 };

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
		// The layout is built once, so a save that publishes or unpublishes pages must reload the frame.
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

// The grid repaints on every colour change; the preview frame is built once so it keeps its page.
function build_layout(frm, $wrapper) {
	if ($wrapper.find('[data-region="swatches"]').length) return;

	$wrapper.html(`
		<div data-region="swatches" style="display: grid; gap: 16px;
			grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));"></div>

		<div style="margin-top: var(--margin-xl);">
			<div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
				gap: 12px; margin-bottom: var(--margin-sm);">
				<div>
					<div style="font-weight: 600; color: var(--text-color);">${__("Preview")}</div>
					<div style="font-size: var(--text-sm); color: var(--text-muted);">
						${__("The portal with the colours on this form, saved or not, filled with a made-up borrower.")}
					</div>
				</div>
				<div style="display: flex; gap: 8px; align-items: center;">
					<select class="form-control input-xs" data-control="page" style="width: auto;"></select>
					<div class="btn-group" role="group">
						<button type="button" class="btn btn-xs btn-default" data-mode="light">${__("Light")}</button>
						<button type="button" class="btn btn-xs btn-default" data-mode="dark">${__("Dark")}</button>
					</div>
				</div>
			</div>
			<div data-region="screen" style="position: relative; overflow: hidden;
				aspect-ratio: ${SCREEN.width} / ${SCREEN.height}; border: 1px solid var(--border-color);
				border-radius: var(--radius); background: var(--card-bg);">
				<iframe scrolling="no" tabindex="-1" style="position: absolute; top: 0; left: 0; border: 0;
					width: ${SCREEN.width}px; height: ${SCREEN.height}px; transform-origin: 0 0;
					pointer-events: none;"></iframe>
				<div data-region="unpublished" style="display: none; height: 100%; align-items: center;
					justify-content: center; color: var(--text-muted); font-size: var(--text-sm);">
					${__("Save to publish the portal, then the preview appears here.")}
				</div>
			</div>
		</div>
	`);

	frm.theme_preview = { $wrapper, mode: "light" };
	fit_screen($wrapper);

	$wrapper.find('[data-control="page"]').on("change", () => load_page(frm));
	$wrapper.find("[data-mode]").on("click", function () {
		frm.theme_preview.mode = $(this).attr("data-mode");
		apply_preview(frm);
	});

	load_page(frm);
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

function load_page(frm) {
	const $wrapper = frm.theme_preview?.$wrapper;
	if (!$wrapper) return;

	const $picker = $wrapper.find('[data-control="page"]');
	const chosen = $picker.val();
	const pages = published_pages(frm);
	$picker.html(
		pages
			.map((page) => `<option value="${page.route}">${frappe.utils.escape_html(page.label)}</option>`)
			.join("")
	);
	$picker.val(pages.some((page) => page.route === chosen) ? chosen : pages[0]?.route);

	const frame = $wrapper.find("iframe")[0];
	const live = Boolean(frm.portal_published?.portal);
	$wrapper.find('[data-region="unpublished"]').css("display", live ? "none" : "flex");
	$(frame).toggle(live);
	if (!live) {
		frame.src = "about:blank";
		return;
	}

	frame.onload = () => {
		hide_scrollbars(frame.contentDocument);
		watch_portal_styles(frame.contentDocument);
		apply_preview(frm);
	};
	// The flag rides on the page's own URL, so its API calls carry it as their Referer; see preview.py.
	frame.src = `${$picker.val()}?${PREVIEW_PARAM}=1`;
}

// The portal's pages are published only when the settings are saved, so an unsaved switch would 404.
function published_pages(frm) {
	const published = frm.portal_published || {};
	return PREVIEW_PAGES.filter((page) => !page.public_apply || published.apply);
}

// Fetch the unsaved theme's stylesheet and lay it over the portal page in the frame.
function apply_preview(frm) {
	const preview = frm.theme_preview;
	if (!preview) return;

	const { $wrapper, mode } = preview;
	$wrapper.find("[data-mode]").each(function () {
		$(this).toggleClass("active", $(this).attr("data-mode") === mode);
	});

	const doc = $wrapper.find("iframe")[0]?.contentDocument;
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

function fit_screen($wrapper) {
	const screen = $wrapper.find('[data-region="screen"]')[0];
	const frame = screen.querySelector("iframe");
	const fit = () => {
		frame.style.transform = `scale(${screen.clientWidth / SCREEN.width})`;
	};

	fit();
	new ResizeObserver(fit).observe(screen);
}

// A still screen: the inner panes would otherwise show their own scrollbars.
function hide_scrollbars(doc) {
	if (!doc?.head || doc.getElementById(SCREEN_STYLE_ID)) return;

	const style = doc.createElement("style");
	style.id = SCREEN_STYLE_ID;
	style.textContent = `
		html, body { overflow: hidden !important; }
		* { scrollbar-width: none !important; }
		*::-webkit-scrollbar { display: none !important; }
	`;
	doc.head.appendChild(style);
}

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
