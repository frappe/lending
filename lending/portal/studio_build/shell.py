# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Portal frame pieces placed beside page content: a Studio component cannot wrap children."""

from lending.portal.studio_build.app import upsert_component
from lending.portal.studio_build.blocks import (
	any_row,
	badge,
	block,
	brand_style,
	button,
	click,
	column,
	container,
	fallback,
	icon,
	instance,
	muted,
	repeater,
	root,
	row,
	slot,
	spacer,
	text,
)

HEADER = "borrower_header"
FOOTER = "borrower_footer"
ALERTS = "borrower_alerts"
SEARCH = "borrower_search"

# The bare Dialog's title is only used as the overlay's `data-dialog`, the one styling hook.
PALETTE_TITLE = "Borrower search"
PALETTE_CSS = f"""
.dialog-overlay[data-dialog="{PALETTE_TITLE}"] {{ background-color: rgba(56, 56, 56, 0.8); }}
.dialog-overlay[data-dialog="{PALETTE_TITLE}"] .dialog-content {{
	max-width: 575px;
	margin: 28px 0 0;
	border: 1px solid #ededed;
	border-radius: 12px;
	box-shadow: 0 5px 10px rgba(0, 0, 0, 0.1);
	background-color: #fff;
}}
"""

PALETTE_TEXT = {"fontSize": "13px", "lineHeight": "19.5px", "letterSpacing": "0.02em", "color": "#171717"}
FOOT_TEXT = {
	"fontSize": "12px",
	"lineHeight": "18px",
	"letterSpacing": "0.02em",
	"color": "#525252",
	"whiteSpace": "nowrap",
}

KEYCAP = {"borderRadius": "4px", "backgroundColor": "#ededed", "color": "#525252", "flexShrink": "0"}
GLYPH_KEY = dict(KEYCAP, width="18px", height="18px", padding="3px", justifyContent="center")
WORD_KEY = dict(
	KEYCAP, padding="2px 4px", fontSize="10px", lineHeight="15px", letterSpacing="0.02em", whiteSpace="nowrap"
)
ICON_KEYS = ("arrow-up", "arrow-down", "corner-down-left")

CRUMB_TYPE = "text-lg-medium"
CRUMB_BOX = {"display": "flex", "alignItems": "center", "padding": "4px 2px"}

# Not hooks.portal_menu_items, whose routes are Builder's; the last column keeps a row lit on detail pages.
NAV_ITEMS = (
	("Account overview", "/overview", "layout-dashboard", None),
	("Loan account", "/loans", "wallet", "/loan/"),
	("Application", "/applications", "file-text", "/application/"),
	("Statement of account", "/statement", "receipt", None),
	("Interest certificate", "/certificate", "award", None),
	("Personal details", "/profile", "user", None),
)

# `typeof` guard: the canvas has no page-script bindings, and a bare name would hide the rail's text.
EXPANDED = "{{ typeof sidebarCollapsed === 'undefined' || !sidebarCollapsed }}"

# Not a negated EXPANDED, which would read as shut on the canvas.
COLLAPSED = "typeof sidebarCollapsed !== 'undefined' && sidebarCollapsed"

MARK = {"width": "28px", "height": "28px", "flexShrink": "0", "borderRadius": "6px"}


def brand(data):
	"""Not SidebarHeader, whose Dropdown chevron cannot be hidden."""
	logo = block(
		"ImageView",
		props={"image": "{{ %s.brand_logo }}" % data, "alt": "", "shape": "square", "size": "lg"},
		# ImageView sizes start at 128px; the styles override them and `size` only picks the corner.
		styles=dict(MARK, overflow="hidden"),
		visible="{{ %s.brand_logo }}" % data,
	)
	letter = text(
		"{{ (%s.brand_name || '').charAt(0) }}" % data,
		size="text-base",
		styles=dict(
			MARK,
			display="flex",
			alignItems="center",
			justifyContent="center",
			textTransform="uppercase",
			backgroundColor="var(--portal-primary, var(--surface-gray-4))",
			color="var(--portal-primary-ink, var(--ink-gray-7))",
		),
		visible="{{ %s.show_wordmark }}" % data,
	)
	name = text(
		fallback("{{ %s.brand_name }}" % data, "''"),
		size="text-base",
		styles={
			"flex": "1 1 0%",
			"fontWeight": "500",
			"color": "var(--ink-gray-8)",
			"minWidth": "0px",
			"overflow": "hidden",
			"textOverflow": "ellipsis",
			"whiteSpace": "nowrap",
		},
		visible=EXPANDED,
	)

	# Centring only takes effect once the name is hidden; if it hides while open, the mark drifts.
	return row(
		[logo, letter, name],
		gap="8px",
		styles={
			"height": "48.8px",
			"marginTop": "-8px",
			"flexShrink": "0",
			"justifyContent": "center",
			"padding": "0 6px",
		},
	)


def collapse_toggle():
	"""Hover-revealed disc on the rail edge; Tailwind picks its classes up from the page JSON."""
	return button(
		"",
		script="sidebarCollapsed.value = !sidebarCollapsed.value",
		variant="ghost",
		props={
			"icon": "{{ %s ? 'lucide-chevron-right' : 'lucide-chevron-left' }}" % COLLAPSED,
			"label": "Toggle sidebar",
			"size": "xs",
		},
		classes=[
			"opacity-0",
			"group-hover:opacity-100",
			"transition-opacity",
			# `!` to outrank the inline background below.
			"hover:!bg-surface-gray-2",
		],
		styles={
			"position": "absolute",
			"right": "-12px",
			"bottom": "80px",
			"borderRadius": "9999px",
			"borderWidth": "1px",
			"borderStyle": "solid",
			"borderColor": "var(--outline-gray-1)",
			"backgroundColor": "var(--surface-sidebar)",
			"boxShadow": "0 1px 4px rgba(0, 0, 0, 0.1)",
		},
	)


def account_menu(data):
	"""Options are an expression because an option's `onClick` must be a function, not JSON."""
	holder = fallback("{{ %s.holder_name }}" % data, "''")
	avatar = block(
		"Avatar",
		props={"label": holder, "size": "md", "shape": "circle"},
		styles={"flexShrink": "0"},
		# Styled by lending.portal.brand.
		classes=["portal-avatar"],
	)
	name = text(
		holder,
		size="text-sm",
		styles={
			"flex": "1 1 0%",
			"minWidth": "0px",
			"color": "var(--ink-gray-7)",
			"overflow": "hidden",
			"textOverflow": "ellipsis",
			"whiteSpace": "nowrap",
		},
		visible=EXPANDED,
	)
	trigger = row(
		[avatar, name],
		gap="8px",
		classes=["hover:bg-surface-gray-2"],
		styles={
			"height": "32px",
			"padding": "0 6px",
			"borderRadius": "8px",
			"cursor": "pointer",
			"justifyContent": "center",
		},
	)

	return block(
		"Dropdown",
		props={
			"options": (
				"{{ [%s.can_switch && { label: 'Switch account', icon: 'lucide-arrow-left-right', "
				"onClick: () => open('/accounts') }, "
				"{ label: 'Log out', icon: 'lucide-log-out', onClick: () => logout() }].filter(Boolean) }}"
			)
			% data,
			"side": "top",
			"align": "start",
		},
		slots=slot("trigger", [trigger]),
	)


def sidebar(data):
	"""Collapses to frappe-ui's icon rail, not away as on the desk: there is no dock to reopen from."""
	nav_items = [
		block(
			"SidebarItem",
			props={"label": title, "icon": "lucide-%s" % icon, "to": route, "active": is_current(route, detail)},
		)
		for title, route, icon, detail in NAV_ITEMS
	]

	sidebar_children = [
		block(
			"div",
			styles={"display": "flex", "height": "100%", "flexDirection": "column", "padding": "0.5rem"},
			children=[
				brand(data),
				# Room for the active row's shadow inside the clip.
				block(
					"div",
					styles={
						"flex": "1 1 0%",
						"overflowY": "auto",
						"overflowX": "hidden",
						"margin": "0 -4px",
						"padding": "2px 4px",
					},
					children=nav_items,
				),
				block("div", styles={"marginTop": "auto"}, children=[account_menu(data)]),
			],
		),
		collapse_toggle(),
	]

	# Sidebar hides overflow-x, which would clip the toggle disc straddling the border.
	return block(
		"Sidebar",
		props={"collapsed": {"$type": "variable", "name": "sidebarCollapsed"}},
		children=sidebar_children,
		classes=["group"],
		styles={
			"position": "relative",
			"overflowX": "visible",
			"borderRight": "1px solid var(--outline-gray-1)",
		},
		mobile={"display": "none"},
	)


def is_current(route, detail=None):
	"""Explicit because SidebarItem's own match compares route names and misses detail pages."""
	condition = "route.path === '%s'" % route
	if detail:
		condition += " || route.path.startsWith('%s')" % detail
	return "{{ typeof route !== 'undefined' && (%s) }}" % condition


def header_tree():
	crumb_node = row(
		[
			text(
				"{{ dataItem.label }}",
				size=CRUMB_TYPE,
				styles={**CRUMB_BOX, "color": "var(--ink-gray-5)", "cursor": "pointer"},
				classes=["hover:text-ink-gray-7"],
				events=click("open(dataItem.route)"),
				visible="{{ dataItem.route }}"
			),
			text(
				"{{ dataItem.label }}",
				size=CRUMB_TYPE,
				styles={
					**CRUMB_BOX,
					"color": "var(--ink-gray-9)",
					"minWidth": "0px",
					"overflow": "hidden",
					"textOverflow": "ellipsis",
					"whiteSpace": "nowrap",
				},
				visible="{{ !dataItem.route }}"
			),
			text(
				"/",
				size="text-base",
				styles={"margin": "0px 2px", "color": "var(--ink-gray-4)"},
				visible="{{ dataItem.route }}"
			),
		],
		gap="0px",
		styles={"alignItems": "center", "minWidth": "0px"}
	)

	breadcrumbs = repeater(
		"{{ inputs.breadcrumbs }}",
		crumb_node,
		# Explicit zero gap: Studio's Repeater wrapper carries `gap-5`.
		styles={
			"display": "flex",
			"flexDirection": "row",
			"alignItems": "center",
			"minWidth": "0px",
			"gap": "0px",
		},
		visible="{{ inputs.breadcrumbs && inputs.breadcrumbs.length > 0 }}"
	)

	# `text-lg` plus a weight, not `text-lg-semibold`, to keep frappe-ui's regular tracking.
	titles = text(
		"{{ inputs.crumb }}",
		tag="h1",
		size="text-lg",
		styles={
			"fontWeight": "600",
			"color": "var(--ink-gray-9)",
			"minWidth": "0px",
			"overflow": "hidden",
			"textOverflow": "ellipsis",
			"whiteSpace": "nowrap",
		},
		visible="{{ !inputs.breadcrumbs || inputs.breadcrumbs.length === 0 }}"
	)
	status = badge(
		"{{ inputs.status }}",
		theme="{{ tone(inputs.status_tone) }}",
		visible="{{ inputs.status }}",
	)
	bell = button(
		"",
		script="showAlerts.value = true; alerts.reload()",
		variant="ghost",
		props={"icon": "lucide-bell", "label": "Notifications"},
	)
	action = button(
		"{{ inputs.action_label }}",
		script="open(inputs.action_route)",
		variant="solid",
		visible="{{ inputs.action_label }}",
	)

	return row(
		[
			row(
				[breadcrumbs, titles, status],
				gap="8px",
				styles={"alignItems": "center", "minWidth": "0px"},
			),
			spacer(),
			bell,
			action,
		],
		gap="10px",
		# Styled by lending.portal.brand.
		classes=["portal-header"],
		styles={
			"padding": "0 20px",
			"width": "100%",
			"minHeight": "48.8px",
			"alignItems": "center",
			# Spelled out: `border-b`'s default colour comes from preflight, which blocks do not get.
			"borderBottom": "1px solid var(--outline-gray-1)",
		},
	)


def alerts_tree():
	alert_row = row(
		[
			column(
				[
					text("{{ dataItem.title }}", size="text-base"),
					muted("{{ dataItem.note }}"),
				],
				gap="2px",
			),
			spacer(),
			muted("{{ dataItem.when }}"),
		],
		gap="10px",
		styles={"padding": "10px 0", "cursor": "pointer"},
		events=click("open(dataItem.url); showAlerts.value = false"),
	)
	tabs = block(
		"TabButtons",
		props={
			"options": [
				{"label": "Notifications", "value": "attention"},
				{"label": "Activity", "value": "activity"},
			],
			"modelValue": {"$type": "variable", "name": "alertsTab"},
			"size": "sm",
		},
	)
	body = column(
		[
			tabs,
			muted("{{ alertsTab === 'attention' ? alerts.data.attention_note : alerts.data.activity_note }}"),
			repeater(
				"{{ alertsTab === 'attention' ? alerts.data.attention : alerts.data.activity }}",
				alert_row,
				empty="Nothing to read",
			),
			button(
				"Mark all as read",
				script="call('lending.portal.notifications.mark_all_as_read').then(() => alerts.reload())",
			),
		],
		gap="10px",
	)

	return block(
		"Dialog",
		props={
			"modelValue": {"$type": "variable", "name": "showAlerts"},
			"title": "Notifications",
			"size": "md",
		},
		children=[body],
	)


def search_tree():
	"""The Ctrl+K palette; its state is useSearch in utils/portal.ts."""
	# A style element because no block reaches frappe-ui's overlay and panel frame.
	frame_css = block("HTML", props={"html": f"<div><style>{PALETTE_CSS}</style></div>"}, styles={"display": "none"})

	box = row(
		[
			icon("search", size=16, styles={"color": "#525252", "padding": "0 2px 0 10px"}),
			block(
				"TextInput",
				props={
					"placeholder": "Search your loans, applications and pages",
					"variant": "ghost",
					"size": "sm",
					"modelValue": {"$type": "variable", "name": "searchText"},
				},
				styles={"flex": "1", "minWidth": "0px"},
			),
		],
		gap="0px",
		styles={"height": "28px", "margin": "8px 8px 4px"},
	)
	rule = container(styles={"height": "1px", "backgroundColor": "#ededed"})

	result = row(
		[
			text("{{ dataItem.title }}", styles=dict(PALETTE_TEXT, fontWeight="700", whiteSpace="nowrap")),
			text("{{ ' ' + dataItem.kind }}", styles=dict(PALETTE_TEXT, fontWeight="400", whiteSpace="pre")),
			spacer(),
			text(
				"{{ dataItem.note }}",
				styles=dict(
					PALETTE_TEXT,
					color="#7c7c7c",
					minWidth="0px",
					overflow="hidden",
					textOverflow="ellipsis",
					whiteSpace="nowrap",
					paddingLeft="12px",
				),
			),
		],
		gap="0px",
		# `minWidth: 0` so the note truncates instead of widening the row.
		styles={
			"width": "100%",
			"minWidth": "0px",
			"height": "33.5px",
			"padding": "0px 7px",
			"borderRadius": "8px",
			"cursor": "pointer",
			"backgroundColor": "{{ dataIndex === searchIndex ? '#f3f3f3' : 'transparent' }}",
		},
		events={
			**click("chooseResult(dataItem)"),
			"mousemove": {"event": "mousemove", "action": "Run Script", "script": "searchIndex.value = dataIndex"},
		},
	)
	results = repeater(
		"{{ searchResults }}",
		result,
		data_key="url",
		empty="Nothing matches that",
		styles={"display": "flex", "flexDirection": "column", "gap": "5px", "padding": "12px 13px 13px"},
	)

	def hint(keys, label):
		caps = [
			container([icon(key, size=12)], styles=GLYPH_KEY) if key in ICON_KEYS else text(key, styles=WORD_KEY)
			for key in keys
		]
		return row([*caps, text(label, styles=FOOT_TEXT)], gap="5px", styles={"flexShrink": "0"})

	note = text(
		"{{ searchNote }}",
		styles=dict(FOOT_TEXT, minWidth="0px", overflow="hidden", textOverflow="ellipsis"),
	)
	foot = row(
		[
			hint(["arrow-up", "arrow-down"], "to navigate"),
			hint(["corner-down-left"], "to select"),
			hint(["Ctrl+K"], "to close"),
			spacer(),
			note,
		],
		gap="15px",
		styles={"height": "40px", "padding": "10px", "borderTop": "1px solid #ededed"},
	)

	return block(
		"Dialog",
		props={
			"modelValue": {"$type": "variable", "name": "showSearch"},
			"title": PALETTE_TITLE,
			"bare": True,
			"position": "top",
			# Replaces `top`'s 20vh; PALETTE_CSS sets the offset.
			"paddingTop": "0px",
		},
		children=[column([frame_css, box, rule, results, foot], gap="0px")],
	)


def footer_tree():
	# core.footer_links is shared with the Builder portal, hence the footer_* keys.
	link = button(
		"{{ dataItem.footer_label }}",
		script="window.location.href = dataItem.footer_href",
		variant="ghost",
		props={"size": "sm"},
		styles={"color": "var(--ink-gray-6)"},
	)

	return row(
		[
			muted("{{ inputs.note }}"),
			spacer(),
			# An empty Repeater prints "No data" whatever it is told.
			repeater(
				"{{ inputs.links }}",
				link,
				data_key="footer_label",
				visible=any_row("{{ inputs.links }}"),
				styles={"display": "flex", "gap": "4px"},
			),
		],
		gap="10px",
		# Styled by lending.portal.brand.
		classes=["portal-footer"],
		styles={
			"height": "49px",
			"flexShrink": "0",
			"padding": "0px 20px",
			"width": "100%",
			"borderWidth": "1px 0px 0px 0px",
			"borderStyle": "solid",
			"borderColor": "var(--outline-gray-2)",
		},
	)


def upsert_frame():
	"""Create or replace the shared frame components. Safe to re-run."""
	upsert_component(
		HEADER,
		"Borrower Page Header",
		header_tree(),
		inputs=(
			("crumb", "What this page is"),
			("breadcrumbs", "List of breadcrumbs"),
			("note", "Who is reading it, and as on when"),
			("status", "How the borrower's accounts stand, where that is worth saying"),
			("status_tone", "'', 'ok', 'warn' or 'danger'"),
			("action_label", "The one thing the page offers to press; empty hides it"),
			("action_route", "Where that button goes, as a data-layer URL"),
		),
	)
	upsert_component(ALERTS, "Borrower Notifications", alerts_tree())
	upsert_component(SEARCH, "Borrower Search", search_tree())
	upsert_component(
		FOOTER,
		"Borrower Footer",
		footer_tree(),
		inputs=(
			("note", "The lender's copyright line"),
			("links", "The policy links, as {footer_label, footer_href} rows"),
		),
	)


def frame(source, content, action_label="", action_route=""):
	"""`source` is the page's data source; every endpoint also returns the frame payload."""
	data = f"{source}.data"
	header = instance(
		HEADER,
		{
			"crumb": "{{ %s.crumb }}" % data,
			"breadcrumbs": "{{ %s.breadcrumbs }}" % data,
			"note": "{{ %s.head_note }}" % data,
			"status": "{{ %s.account_status }}" % data,
			"status_tone": "{{ %s.account_tone }}" % data,
			"action_label": action_label,
			"action_route": action_route,
		},
	)
	footer = instance(
		FOOTER,
		{"note": "{{ %s.copyright_note }}" % data, "links": "{{ %s.footer_links }}" % data},
	)
	body = container(
		content,
		styles={
			"display": "flex",
			"flexDirection": "column",
			"gap": "16px",
			"padding": "20px",
			"width": "100%",
			"flex": "1",
		},
	)
	main = container(
		[header, body, footer, instance(ALERTS), instance(SEARCH)],
		styles={
			"display": "flex",
			"flexDirection": "column",
			"flex": "1",
			"minWidth": "0px",
			"height": "100%",
			"overflowY": "auto",
		},
	)
	# Last, so existing blocks keep the positions the merge matches on.
	return root([sidebar(data), main, brand_style("{{ %s.brand_style }}" % data)])
