# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The portal's frame: the sidebar, the page header, the notifications, the Ctrl+K
search palette and the footer.

The Builder shell is one component wrapped *around* each page's content: Builder
merges a component into a page through extend_block, so a page can mirror the frame's
tree and drop its own blocks into the well in the middle.

Studio has no such merge. `StudioComponentWrapper` renders the component's own tree and
discards the instance's children, passing only its props, which the component reads as
`{{ inputs.<name> }}`. A frame that wraps content is therefore not expressible, so the
frame is the pieces that sit *beside* the content -- the sidebar down the left, the
header above, the footer below -- and `frame()` assembles them around whatever a page
passes in.

Three of those are Studio Components, so one edit reaches every page. The sidebar is
not: it is frappe-ui's Sidebar placed straight into each page, because a component's
tree cannot be opened on the canvas and a Sidebar buried in one would be a black box.
See `sidebar`.

The notifications panel is a Dialog rather than the Builder panel, and it reads the
page's own `alerts` data source: a component has no data source of its own, and every
authenticated page carries one under that name for this reason.
"""

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

# The Ctrl+K palette is drawn to the desk's awesomebar, measured off a running desk in
# Chromium rather than read out of its stylesheets: a 575px card 28px from the top, a
# 1px #ededed border at 12px, 33.5px rows 5px apart, a 40px footer of 18px keys, and
# the page behind it dimmed with rgb(56, 56, 56) at 0.8. Every number below is one of
# those.
#
# The dialog's `title` is never shown -- the dialog is bare -- but frappe-ui stamps it
# on the overlay as `data-dialog`, and that is the only handle there is on the overlay
# or on the panel's own frame: Dialog renders no element of its own to put a class on.
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

# One line of palette text: the desk's 13px on a 19.5px line, at Inter's 0.02em.
PALETTE_TEXT = {"fontSize": "13px", "lineHeight": "19.5px", "letterSpacing": "0.02em", "color": "#171717"}
FOOT_TEXT = {
	"fontSize": "12px",
	"lineHeight": "18px",
	"letterSpacing": "0.02em",
	"color": "#525252",
	"whiteSpace": "nowrap",
}

# The grey key a shortcut sits on: an 18px square round a 12px glyph, or a padded
# word for the chords.
KEYCAP = {"borderRadius": "4px", "backgroundColor": "#ededed", "color": "#525252", "flexShrink": "0"}
GLYPH_KEY = dict(KEYCAP, width="18px", height="18px", padding="3px", justifyContent="center")
WORD_KEY = dict(
	KEYCAP, padding="2px 4px", fontSize="10px", lineHeight="15px", letterSpacing="0.02em", whiteSpace="nowrap"
)
ICON_KEYS = ("arrow-up", "arrow-down", "corner-down-left")

# The crumb trail, as frappe-ui draws one. `Breadcrumbs.vue` gives every crumb
# `px-0.5 py-1 text-lg-medium`, colours the trail `ink-gray-5` and the last one
# `ink-gray-9`, and sets `/` between them in `text-base ink-gray-4` with `mx-0.5`.
#
# `text-lg-medium` is named rather than unpacked into numbers: the portal's own bundle
# carries the class, so the header takes 16px/500/1.15/0.015em from the same rule the
# desk reads it from, and follows it if the scale is ever retuned. Only what a Studio
# block cannot say as a class -- the padding and the two colours -- is spelled out.
CRUMB_TYPE = "text-lg-medium"
CRUMB_BOX = {"display": "flex", "alignItems": "center", "padding": "4px 2px"}

# The rows of the sidebar, and the routes this app serves them at.
#
# lending.hooks.portal_menu_items is the Builder portal's source for these, read back
# per request so a renamed row needs no rebuild. It cannot be that here: its routes are
# the Builder ones (/borrower/loans), the menu is marked current from the request path,
# and a Studio page's request is an API call rather than the page itself. So the rows
# are declared once, here, and a page added is a line here plus a rebuild.
#
# The last column is the detail page a row stays lit on, where it has one: a loan read
# at /loan/<name> is still "Loan account".
NAV_ITEMS = (
	("Account overview", "/overview", "layout-dashboard", None),
	("Loan account", "/loans", "wallet", "/loan/"),
	("Application", "/applications", "file-text", "/application/"),
	("Statement of account", "/statement", "receipt", None),
	("Interest certificate", "/certificate", "award", None),
	("Personal details", "/profile", "user", None),
)

# Whether the rail is open, as every block in it has to ask.
#
# frappe-ui's Sidebar provides its collapsed state down the tree and its own parts inject
# it; blocks cannot inject anything, so the state is bound out to a page-script ref
# instead -- `collapsed` is a v-model on Sidebar -- and read back through this. Anything
# that is words rather than a glyph leaves the rail while it is shut, rather than being
# clipped by the 48px of it that remain.
#
# The ref starts as null, which is Sidebar's own "collapse on mobile, otherwise not", so
# the second half reads as open until somebody presses the toggle.
#
# The `typeof` guard is what makes the rail survive the Studio canvas. An expression is
# evaluated as `with (context) { return <expr> }`, and the canvas has no context to put
# `sidebarCollapsed` in: a page's bindings come from importing its built setup() module,
# which the editor cannot do for an exported app. A bare `!sidebarCollapsed` is then a
# ReferenceError, the evaluator answers undefined, and `visibilityCondition` reads that
# as false -- so every word in the rail vanished on the canvas while the running portal
# was fine. `typeof` is the one operator that does not throw on a name that was never
# declared, so it answers "undefined" there and the real value everywhere else.
EXPANDED = "{{ typeof sidebarCollapsed === 'undefined' || !sidebarCollapsed }}"

# The same question the other way about, for the blocks that want it that way. Written
# out rather than negating the one above: `!` in front of that guard would make the
# canvas, where the name does not exist, read as shut rather than open.
COLLAPSED = "typeof sidebarCollapsed !== 'undefined' && sidebarCollapsed"

# The square the lender's mark is drawn in, whichever of the two marks it turns out to
# be. The numbers are SidebarHeader's own -- `size-7` at `rounded-[6px]`.
MARK = {"width": "28px", "height": "28px", "flexShrink": "0", "borderRadius": "6px"}


def brand(data):
	"""Whose portal this is: the lender's mark, and the lender's name beside it.

	Not frappe-ui's SidebarHeader. That one is the trigger of a Dropdown and draws the
	chevron that opens it whether or not the menu holds anything, and no prop takes the
	chevron away. This portal has nothing to put in that menu -- one app, one borrower,
	no workspace to switch to -- so the header is the two pieces the desk's own header is
	made of, and none of it is pressable.

	Both marks are written out, and one of them renders: `brand_payload` carries the logo
	and the name together because the page is built once and Lending Settings is read per
	request, so the page cannot know which it will have. `show_wordmark` is that payload's
	own answer to which one this is.
	"""
	logo = block(
		"ImageView",
		props={"image": "{{ %s.brand_logo }}" % data, "alt": "", "shape": "square", "size": "lg"},
		# ImageView's own sizes start at 128px, for a picture on a page rather than a mark
		# in a rail. The styles win over the classes that set them, so `size` here is only
		# choosing the 6px corner that goes with it.
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

	# `flex: 1` is what lets one row serve both states. Open, the name fills the row and
	# the mark is pushed to the left edge regardless of the centring below; shut, the name
	# is gone and the mark is the only thing left to centre.
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

	# The header's own 48.8px, pulled up over the rail's 8px of top padding, so the mark
	# sits in the same band as the page header beside it. 6px
	# in from a rail already padded 8, which is where SidebarHeader's own px-1 + px-1.5
	# put it. Shut, those 6px leave less room than the mark needs and it overflows them
	# evenly either side -- which is the rail's centre, 8 + 6 + 10 of 48.
	#
	# So the centring is load-bearing only once the name has gone, and it reads as a bug
	# the moment the name goes for any other reason: the mark drifts to the middle of an
	# open rail. See EXPANDED for the one that did it.
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
	"""The one control that shuts the rail, drawn where the desk draws it.

	The desk hangs a 24px disc off the sidebar's right edge, half of it out over the
	border, and keeps it invisible until the pointer is somewhere on the sidebar. That is
	the whole affordance: no row in the list, nothing holding space in the column, and
	nothing to read. `SidebarCollapseToggle`, which is a labelled row at the foot of the
	list, is what this replaces.

	Two things a style cannot say are said as classes instead -- appearing on hover of an
	ancestor, and the hover of the disc itself. Tailwind generates both from the exported
	page JSON, because studio's content glob reaches into every app's studio folder, so
	neither has to exist in studio's own source first.
	"""
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
			# `!` because the resting background below is an inline style, and an
			# important declaration in a stylesheet is the only thing that outranks one.
			"hover:!bg-surface-gray-2",
		],
		# `xs` is already the desk's 24px; everything here is the disc the desk cuts out
		# of that square, and where it hangs. -12px is half of it, so it straddles the
		# border rather than sitting inside the rail.
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
	"""Who is signed in, and the menu that signs them out, as the desk's own foot has it.

	The avatar and the name are the Dropdown's trigger slot. Studio forwards the trigger's
	handlers onto the slot's one block, so the row itself is what opens the menu. Shut,
	the name leaves the rail and the avatar is centred in the 48px that remain.

	The options are an expression rather than a list, because an option's `onClick` is a
	function and a block's props are JSON. Only the click calls `logout`, so the canvas,
	where the page script is never loaded, still draws the menu.
	"""
	holder = fallback("{{ %s.holder_name }}" % data, "''")
	avatar = block(
		"Avatar",
		props={"label": holder, "size": "md", "shape": "circle"},
		styles={"flexShrink": "0"},
		# What lending.portal.brand washes in the lender's primary colour.
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
	"""The list of pages, and whose portal it is.

	Laid out as the desk's own sidebar is, which mostly meant leaving it alone: the two
	already agree on the row, down to the number. `text-sm` is 13px at 420 over 1.15 in
	both scales; SidebarItem's `h-7` is the desk's 28px anchor; the label is `ink-gray-6`
	in both; `rounded` resolves to `--radius-4`, which is the desk's 8px; both hover at
	gray-100 and draw the row you are on in white under a small shadow. What the desk has
	and this did not is the hairline down the right of the rail, a header with nothing to
	press, and the disc on the edge that shuts it -- see `collapse_toggle`.

	One thing is deliberately not the desk's. There, collapsing takes the sidebar away
	entirely and the workspace dock becomes the icon rail you reopen it from. This portal
	has no dock, so a rail that left would leave nothing to press to bring it back; it
	keeps frappe-ui's 48px of icons instead, and the disc rides along on that.
	"""
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
				# The list clips, so the current row's shadow would be cut flat at its
				# edges. The padding is room for the shadow inside the clip, and the
				# negative margin hands it back so the rows stay where they were.
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

	# The border is frappe-ui's own `border-r border-outline-gray-1`, which Sidebar draws
	# only for the config-object API it is keeping around for one more release. Written
	# out here because this sidebar is composed rather than configured, and because
	# `--outline-gray-1` is #ededed, which is the desk's `--sidebar-border-color` exactly.
	#
	# The other three all serve the disc on the edge. `relative` is what it is positioned
	# against; `overflow-x` has to be given back, because Sidebar hides it and would cut
	# the disc off at the border it is meant to straddle -- nothing else in the rail
	# reaches the edge, since every label clips itself as it collapses; and `group` is the
	# ancestor whose hover reveals it.
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
	"""Whether a row is the page being read, which SidebarItem draws raised in white.

	Said outright rather than left to SidebarItem's own guess from `to`, which compares
	route names and so goes dark on a loan's own page. `typeof` guards the canvas, which
	has no `route` in scope; see EXPANDED.
	"""
	condition = "route.path === '%s'" % route
	if detail:
		condition += " || route.path.startsWith('%s')" % detail
	return "{{ typeof route !== 'undefined' && (%s) }}" % condition


def header_tree():
	"""The crumb, the day it is being read, and the one thing the page offers to press.

	Every value arrives as an input, so one header serves ten pages. The action hides
	itself where a page passes no label -- the statement and the certificate keep their
	download inside the page, beside the dates it obeys.
	"""
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
		# No gap: frappe-ui sets the crumbs flush against each other and lets the `/` hold
		# them apart on its own -- `mx-0.5` on the separator against `px-0.5` on the crumb
		# either side of it, so 4px of white each way. Zero has to be said out loud, since
		# Studio's Repeater carries `gap-5` on its own wrapper and would stand them 20px
		# apart on its own.
		styles={
			"display": "flex",
			"flexDirection": "row",
			"alignItems": "center",
			"minWidth": "0px",
			"gap": "0px",
		},
		visible="{{ inputs.breadcrumbs && inputs.breadcrumbs.length > 0 }}"
	)

	# A page with no trail says its own name, as frappe-ui's PageHeaderTitle does:
	# `truncate text-lg font-semibold text-ink-gray-9`. `text-lg` rather than
	# `text-lg-semibold` -- the weight is overridden on top of the regular style, so the
	# tracking stays the regular 0.02em, and copying the semibold style would tighten it.
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

	# The badge sits beside the record it describes, not out at the right margin: it
	# reads as part of the title. `gap-2` between them, as the desk header has it --
	# 10px apart on the page, once the last crumb's own 2px of padding is counted.
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
		# What lending.portal.brand paints in the lender's primary colour.
		classes=["portal-header"],
		styles={
			# The content's own 20px inset, so the crumb lines up with the cards and the
			# action does not touch the window's edge.
			"padding": "0 20px",
			"width": "100%",
			"minHeight": "48.8px",
			"alignItems": "center",
			# The rule under the header, as `PageHeader.vue` draws it: plain `border-b`,
			# whose colour is the preset's own `borderColor.DEFAULT`. Spelled out rather
			# than left to the class, because that default is set on Tailwind's preflight
			# rule and a block styled here carries no class to inherit it from.
			"borderBottom": "1px solid var(--outline-gray-1)",
		},
	)


def alerts_tree():
	"""What is waiting on the borrower and what has happened, over one list of rows.

	The two lists come back in the same {title, note, when, url} shape, so the tab
	switches which array the repeater reads rather than which blocks it draws.
	"""
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
	"""The Ctrl+K palette: one box, the rows it finds, and the keys that drive it.

	Laid out as the desk's command palette is, to the pixel -- see PALETTE_CSS for the
	numbers. The one thing added is the grey note at the end of a row: eight rows all
	reading "Personal Loan Application" need their reference to be told apart. There is
	no Search page behind it any more, so this is the whole of search. The state is the
	page script's; see useSearch in utils/portal.ts.
	"""
	# A style element, rather than styles on a block, because the overlay and the panel
	# frame are frappe-ui's and no block reaches them. Hidden, and still applied.
	frame_css = block("HTML", props={"html": f"<div><style>{PALETTE_CSS}</style></div>"}, styles={"display": "none"})

	# 8px round a 28px row, less 4 under it: the desk's input row and the gap to its rule.
	# `sm` is frappe-ui's 28px input at 14px with 6px 8px of padding, which is the desk's.
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

	# The desk's `<b>Loan Lead</b> List`: the name bold, the kind in the same ink after a
	# space. The space is the kind's own, held open by `pre`, so it is Inter's space and
	# not a gap guessed at in pixels.
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
		# `minWidth: 0` or the row grows to its note -- a flex item's floor is its content
		# -- and the note runs off the card instead of truncating.
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
	# 12px under the rule, 13 either side and below: the desk's list padding plus the
	# wrapper's, and the last row's 5px margin that the desk leaves in.
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

	# The note gives way before the keys do: it truncates, they never wrap.
	note = text(
		"{{ searchNote }}",
		styles=dict(FOOT_TEXT, minWidth="0px", overflow="hidden", textOverflow="ellipsis"),
	)
	# 40px: a 1px rule, 10px either side of an 18px line of keys.
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
			# A padding of its own replaces `top`'s 20vh; PALETTE_CSS sets the 28px.
			"paddingTop": "0px",
		},
		children=[column([frame_css, box, rule, results, foot], gap="0px")],
	)


def footer_tree():
	"""Whose portal this is, and the policies. Both are Lending Settings, read per request."""
	# The rows keep the Builder portal's names -- core.footer_links is shared -- so the
	# keys are footer_label and footer_href, not label and href.
	link = button(
		"{{ dataItem.footer_label }}",
		script="window.location.href = dataItem.footer_href",
		variant="ghost",
		props={"size": "sm"},
		# The copyright line's grey, so the band reads as one quiet line.
		styles={"color": "var(--ink-gray-6)"},
	)

	return row(
		[
			muted("{{ inputs.note }}"),
			spacer(),
			# Hidden when Lending Settings lists no links: an empty Repeater prints
			# "No data" whatever it is told, and a footer has nothing to apologise for.
			repeater(
				"{{ inputs.links }}",
				link,
				data_key="footer_label",
				visible=any_row("{{ inputs.links }}"),
				styles={"display": "flex", "gap": "4px"},
			),
		],
		gap="10px",
		# What lending.portal.brand washes in the lender's primary colour, as the header.
		classes=["portal-footer"],
		styles={
			# A fixed 49px band, matching the 48.8px header at the other end of the page.
			# The vertical padding goes with it: the links are `sm` buttons, 28px tall, and
			# 12px either side of them would ask for 52px in a box that is only allowed 49.
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
	"""Create or replace the four shared components. Safe to re-run.

	The sidebar is not one of them; see `sidebar` for why it is built into each page.
	"""
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
	"""One page: the frame, wrapped around this page's own blocks.

	`source` is the name of the page's data source, because every endpoint answers with
	the same frame payload -- the crumb, the holder, the footer -- alongside whatever
	the page itself asked for.
	"""
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
	# Last, so adding it moved no block the merge already knows by its position.
	return root([sidebar(data), main, brand_style("{{ %s.brand_style }}" % data)])
