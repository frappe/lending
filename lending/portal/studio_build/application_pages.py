# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One application's tracker, and the applications table the overview draws.

There is no list page. The sidebar opens the borrower's newest application straight
away, as it opens their loan; the overview's table is the way to any other.

The tracker leads on the detail page, because "where has my application got to" is the
question that brings a borrower here. Under it, what they asked for: four sets of
label-and-value pairs, which the Builder page stacked behind a tab strip built out of
buttons and a stylesheet, and this one draws as frappe-ui's underlined Tabs, each set's
fields laid straight on the card under them.
"""

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	button,
	card,
	column,
	container,
	field_grid,
	icon,
	icon_tile,
	muted,
	reader,
	record_list,
	repeater,
	row,
	spacer,
	subject,
	tab_strip,
	text,
	toned_badge,
)
from lending.portal.studio_build.shell import frame

DETAIL_SOURCE = "application"
ALERTS = ("alerts", "lending.portal.notifications.get_notifications")

# What the preview holds, in the order a borrower checks it: the loan first, because
# that is what the application is, then who it is for, then what went with it.
SECTIONS = (
	("Loan details", "terms", False),
	("Your details", "applicant", False),
	("Co-applicants", "co_applicants", True),
	("Documents", "documents", True),
)

# The tracker's geometry: the circle, and the space between it and the name under it.
STEP_NODE = "32px"
STEP_NODE_MOBILE = "24px"
STEP_LABEL_GAP = "8px"
# The same three looks as the dots of /track, so a borrower who tracked the file before
# logging in reads its stage the same way after. See track_page.DOT_STATES.
# A done step is a wash of the lender's primary colour, and green where none is set.
STEP_DONE = ("var(--portal-primary-soft, var(--surface-green-2))", "var(--portal-primary-deep, var(--ink-green-7))")
STEP_NOW = ("var(--portal-primary, var(--surface-gray-9))", "var(--portal-primary-ink, var(--surface-base))")
STEP_LINE_DONE = "var(--portal-primary-line, var(--outline-green-3))"


# --- the list -----------------------------------------------------------------------


def applications(read):
	"""Each row links to its own tracker, so the whole line is the way in.

	The Account overview draws this same table under "Application status", by calling
	this -- the two are one function rather than two copies of one, so a row cannot come
	to mean one thing on the list and another on the overview.

	The tracks are proportional rather than the fixed 9rem they were: a stage and an
	amount are both short, and two fixed columns pinned to the right of a wide one left
	the three reading as a line of text and a pair of figures pushed away from it.
	"""
	return record_list(
		[("minmax(0, 1.5fr)", "Application"), ("minmax(0, 1fr)", "Stage"), ("minmax(0, 1fr)", "Amount sought")],
		read("applications"),
		[
			[
				subject("{{ item.product }}"),
				# The name and the day it was raised, one under the other. The payload
				# joins them into `reference` for a row that has one line to say both
				# in; this row has three, so it takes them apart again.
				muted("{{ item.name }}"),
				muted("{{ item.initiated }}"),
				muted("{{ item.note }}", visible="{{ item.note }}"),
			],
			[toned_badge("{{ item.stage }}", "item.stage_tone", size="lg")],
			[text("{{ item.amount }}", size="text-base")],
		],
		script="open(item.url)",
	)


# --- one application ------------------------------------------------------------------


def step_node():
	"""The circle for one step, with its short name hung under it.

	A done step is a pale disc with a tick -- the lender's primary, or green -- the step in progress a dark disc round a
	dot, and one still ahead an empty grey ring. All three are in the tree and the step's
	`code` shows one, because a fill is a style and only props are evaluated.

	The name is placed absolutely, centred on the circle, so a name wider than the circle
	does not push the connectors away from it.
	"""
	ring = {
		"width": STEP_NODE,
		"height": STEP_NODE,
		"borderRadius": "9999px",
		"display": "flex",
		"alignItems": "center",
		"justifyContent": "center",
		"boxSizing": "border-box",
	}
	# Five circles at full size leave a phone's short connectors no room between names.
	small = {"width": STEP_NODE_MOBILE, "height": STEP_NODE_MOBILE}
	done = icon(
		"check",
		size=16,
		stroke=3,
		styles=dict(ring, backgroundColor=STEP_DONE[0], color=STEP_DONE[1]),
		mobile=small,
		visible="{{ dataItem.code === 'done' }}",
	)
	current = container(
		[container(styles={"width": "10px", "height": "10px", "borderRadius": "9999px", "backgroundColor": STEP_NOW[1]})],
		styles=dict(ring, backgroundColor=STEP_NOW[0]),
		mobile=small,
		visible="{{ dataItem.code === 'current' }}",
	)
	pending = container(
		styles=dict(ring, border="1.5px solid var(--outline-gray-3)", backgroundColor="var(--surface-base)"),
		mobile=small,
		visible="{{ dataItem.code === 'pending' }}",
	)

	label = {
		"position": "absolute",
		"top": f"calc(100% + {STEP_LABEL_GAP})",
		"left": "50%",
		"transform": "translateX(-50%)",
		"whiteSpace": "nowrap",
	}
	reached = text(
		"{{ dataItem.short }}",
		size="text-base",
		styles=dict(label, color="var(--ink-gray-7)"),
		mobile={"fontSize": "12px"},
		visible="{{ dataItem.code !== 'pending' }}",
	)
	ahead = text(
		"{{ dataItem.short }}",
		size="text-base",
		styles=dict(label, color="var(--ink-gray-5)"),
		mobile={"fontSize": "12px"},
		visible="{{ dataItem.code === 'pending' }}",
	)

	return container(
		[done, current, pending, reached, ahead],
		styles={"position": "relative", "flex": "0 0 auto"},
	)


def step_line(tone, colour):
	return container(
		styles={"flex": "1 1 auto", "height": "3px", "borderRadius": "9999px", "backgroundColor": colour},
		visible="{{ dataItem.line === '%s' }}" % tone,
	)


def tracker(read):
	"""How far the file has got: a circle per stage, joined by a line across the card.

	Each copy of the template is `display: contents`, so its circle and the line after
	it are laid out as the repeater's own children -- circle, line, circle, line, circle
	-- and the lines share out the width between the circles. The payload's `line` says
	which colour the line after a step is, and that there is none after the last.

	The inline padding is room for the first and last names, which overhang their
	circles; the bottom padding is room for all of them.
	"""
	step = container(
		[step_node(), step_line("ok", STEP_LINE_DONE), step_line("plain", "var(--outline-gray-2)")],
		styles={"display": "contents"},
	)

	return repeater(
		read("steps"),
		step,
		data_key="title",
		styles={
			"display": "flex",
			"flexDirection": "row",
			"flexWrap": "nowrap",
			"alignItems": "center",
			"gap": "0px",
			"width": "100%",
			"boxSizing": "border-box",
			"padding": "4px 28px 32px",
		},
		mobile={"padding": "4px 20px 28px"},
	)


def lead_card(read, **kwargs):
	"""The product, the reference and where the file stands, above everything else."""
	head = column(
		[
			row(
				[
					text(read("product"), tag="h2", size="text-2xl", styles={"fontWeight": "600"}),
					spacer(),
					muted(read("as_on")),
				],
				gap="10px",
			),
			muted(read("reference")),
		],
		gap="2px",
	)

	return card(
		"",
		"",
		column([head, tracker(read), muted(read("headline")), muted(read("headline_note"))], gap="12px"),
		**kwargs,
	)


def section_panel(read, key, detail):
	"""One section's fields, straight on the card. The open tab already names it, and a
	border round them would draw a second box inside the card's own."""
	return container(
		[field_grid(read(key), with_detail=detail)],
		visible="{{ previewTab === '%s' }}" % key,
	)


def preview(read):
	"""Four sections behind four tabs, rather than four screens of scroll.

	Which section is showing is this page's own state, so the page script holds it,
	the tab strip sets it and each panel says when it is the one being read.
	"""
	tabs = tab_strip([(label, key) for label, key, _detail in SECTIONS], "previewTab")
	panels = [section_panel(read, key, detail) for _label, key, detail in SECTIONS]

	return column([tabs, *panels], gap="16px")


def has_application(read, value):
	"""The condition that the payload's `has_application` is `value`, and not undefined."""
	return "{{ %s === %s }}" % (read("has_application")[2:-2].strip(), value)


def no_application(read):
	"""A borrower who has not applied gets one thing to do, centred on a plain page.

	Shown only on an explicit `false`, so the canvas -- where the source never resolves --
	still draws the tracker and the preview for whoever is designing them.
	"""
	return column(
		[
			icon_tile("file", styles={"marginBottom": "10px"}),
			text(
				"No applications yet",
				size="text-base",
				styles={"fontWeight": "600", "color": "var(--ink-gray-8)"},
			),
			muted("Apply for a loan and you can follow it here.", styles={"textAlign": "center"}),
			button(
				"Create application",
				script="open('/new-application')",
				props={"iconLeft": "lucide-plus"},
				styles={"marginTop": "12px"},
			),
		],
		gap="4px",
		visible=has_application(read, "false"),
		styles={"flex": "1 1 auto", "alignItems": "center", "justifyContent": "center", "padding": "64px 16px"},
	)


def detail_content(read):
	# `!== false` rather than `=== true`, so the canvas draws these and not the empty state.
	applied = "{{ %s !== false }}" % read("has_application")[2:-2].strip()

	return [
		lead_card(read, visible=applied),
		card("Application preview", read("preview_note"), preview(read), visible=applied),
		no_application(read),
	]


def build_detail(title, route, params=None):
	read = reader(DETAIL_SOURCE)

	return upsert_page(
		title,
		route,
		frame(
			DETAIL_SOURCE,
			detail_content(read),
			action_label="New application",
			action_route="/new-application",
		),
		[
			api_resource(
				DETAIL_SOURCE,
				"lending.portal.applications.get_application_detail",
				params=params,
			),
			api_resource(*ALERTS, auto=0),
		],
		script=page_script(state=[("previewTab", '"terms"')]),
	)


def build():
	"""The sidebar's page, which opens the newest application, and one per application.

	The same pair the loan pages are: /applications names nothing and the data layer
	picks, /application/:name is where a row on the overview leads.
	"""
	return (
		build_detail("Loan application", "/applications"),
		build_detail("Application", "/application/:name", params={"name": "{{ route.params.name }}"}),
	)
