# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

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

SECTIONS = (
	("Loan details", "terms", False),
	("Your details", "applicant", False),
	("Co-applicants", "co_applicants", True),
	("Documents", "documents", True),
)

STEP_NODE = "32px"
STEP_NODE_MOBILE = "24px"
STEP_LABEL_GAP = "8px"
# Keep in step with track_page.DOT_STATES so a stage looks the same before and after login.
STEP_DONE = ("var(--portal-primary-soft, var(--surface-green-2))", "var(--portal-primary-deep, var(--ink-green-7))")
STEP_NOW = ("var(--portal-primary, var(--surface-gray-9))", "var(--portal-primary-ink, var(--surface-base))")
STEP_LINE_DONE = "var(--portal-primary-line, var(--outline-green-3))"


def applications(read):
	return record_list(
		[("minmax(0, 1.5fr)", "Application"), ("minmax(0, 1fr)", "Stage"), ("minmax(0, 1fr)", "Amount sought")],
		read("applications"),
		[
			[
				subject("{{ item.product }}"),
				muted("{{ item.name }}"),
				muted("{{ item.initiated }}"),
				muted("{{ item.note }}", visible="{{ item.note }}"),
			],
			[toned_badge("{{ item.stage }}", "item.stage_tone", size="lg")],
			[text("{{ item.amount }}", size="text-base")],
		],
		script="open(item.url)",
	)


def step_node():
	# All three are rendered and `visible` picks one, because only props are evaluated, not styles.
	ring = {
		"width": STEP_NODE,
		"height": STEP_NODE,
		"borderRadius": "9999px",
		"display": "flex",
		"alignItems": "center",
		"justifyContent": "center",
		"boxSizing": "border-box",
	}
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

	# Absolute, so a name wider than the circle does not push the connectors away.
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
	# `display: contents` lays circles and lines out as the repeater's own flex children.
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
			# Room for the absolutely placed step names that overhang the circles.
			"padding": "4px 28px 32px",
		},
		mobile={"padding": "4px 20px 28px"},
	)


def lead_card(read, **kwargs):
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
	return container(
		[field_grid(read(key), with_detail=detail)],
		visible="{{ previewTab === '%s' }}" % key,
	)


def preview(read):
	tabs = tab_strip([(label, key) for label, key, _detail in SECTIONS], "previewTab")
	panels = [section_panel(read, key, detail) for _label, key, detail in SECTIONS]

	return column([tabs, *panels], gap="16px")


def has_application(read, value):
	return "{{ %s === %s }}" % (read("has_application")[2:-2].strip(), value)


def no_application(read):
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
	return (
		build_detail("Loan application", "/applications"),
		build_detail("Application", "/application/:name", params={"name": "{{ route.params.name }}"}),
	)
