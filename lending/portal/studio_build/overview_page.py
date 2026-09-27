# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.application_pages import applications
from lending.portal.studio_build.blocks import (
	button,
	card,
	chevron,
	click,
	column,
	container,
	fallback,
	icon,
	muted,
	reader,
	record_stat,
	repeater,
	row,
	slot,
	spacer,
	stat,
	stat_strip,
	text,
	tile_styles,
	toned_badge,
	two_columns,
)
from lending.portal.studio_build.shell import frame

TITLE = "Account overview"
ROUTE = "/overview"
SOURCE = "overview"
ACCOUNTS_ROUTE = "/loans"
read = reader(SOURCE)

# The marker box is the title's line height, so either marker size centres on it.
MARKER = "18px"
DOT = "10px"
STEM_GAP = "4px"
# Padding under a row's lines, not a gap between rows, so the stem can run through it.
ROW_GAP = "24px"
DATE_TILE = "48px"

# Every sign-in lands here, so multi-loan borrowers are sent to pick an account first.
SCRIPT = page_script(
	body='''\twatch(
\t\t() => context.overview?.data?.choose_account,
\t\t(choose) => { if (choose) router.replace("/accounts") },
\t\t{ immediate: true },
\t)'''
)


def application_card():
	stage = f"{SOURCE}.data.application_stage"
	label = row(
		[
			text(
				read("label_application"),
				size="text-xs",
				styles={
					"color": "var(--ink-gray-5)",
					"fontWeight": "500",
					"letterSpacing": "0.06em",
					"textTransform": "uppercase",
				},
			),
			spacer(),
			icon(
				"chevron-right",
				styles=dict(tile_styles(tile=28), color="var(--ink-gray-6)"),
				visible=read("application_url"),
			),
		],
		gap="8px",
	)
	meta = row(
		[
			stage_badge(with_us=True),
			stage_badge(with_us=False),
			labelled("calendar", "application_date_label", "application_date"),
		],
		gap="10px",
		styles={"flexWrap": "wrap"},
		visible=read("application_stage"),
	)
	warn = f"{SOURCE}.data.application_stage_tone === 'warn'"
	note = row(
		[
			status_dot("orange", visible="{{ %s && %s }}" % (stage, warn)),
			status_dot("green", visible="{{ %s && !(%s) }}" % (stage, warn)),
			muted(read("application_note")),
		],
		gap="10px",
		styles={"paddingTop": "6px"},
		visible=read("application_note"),
	)

	return record_stat(
		"file-text",
		[
			label,
			text(
				read("application_headline"),
				tag="div",
				size="text-2xl",
				styles={"fontWeight": "600", "padding": "2px 0 4px"},
				visible=read("application_headline"),
			),
			meta,
			note,
			muted(read("application_more"), visible=read("application_more")),
		],
		script=f"open({SOURCE}.data.application_url)",
	)


def stage_badge(with_us):
	# Two badges, not one with a hidden glyph: Badge keeps the prefix gap whenever the slot exists.
	stage = f"{SOURCE}.data.application_stage"
	flag = f"{SOURCE}.data.application_with_us"
	shown = "{{ %s && %s }}" % (stage, flag if with_us else f"!{flag}")
	glyph = slot("prefix", [icon("users", size=16)]) if with_us else None

	return toned_badge(
		read("application_stage"),
		f"{SOURCE}.data.application_stage_tone",
		size="md",
		visible=shown,
		slots=glyph,
	)


def labelled(glyph, label_key, value_key):
	return row(
		[
			icon(glyph, styles={"color": "var(--ink-gray-5)"}),
			muted(read(label_key)),
			text(read(value_key), styles={"color": "var(--ink-gray-8)", "fontWeight": "500"}),
		],
		gap="6px",
		visible=read(value_key),
	)


def status_dot(theme, **kwargs):
	disc = {
		"display": "flex",
		"alignItems": "center",
		"justifyContent": "center",
		"flex": "0 0 auto",
		"width": "20px",
		"height": "20px",
		"borderRadius": "9999px",
		"backgroundColor": f"var(--surface-{theme}-2)",
	}
	dot = {
		"width": "8px",
		"height": "8px",
		"borderRadius": "9999px",
		"backgroundColor": f"var(--surface-{theme}-6)",
	}

	return container([container(styles=dot)], styles=disc, **kwargs)


def summary():
	return stat_strip(
		[
			application_card(),
			stat(
				read("label_next"),
				read("next_amount"),
				read("next_note"),
				flag=read("next_flag"),
				icon_name="calendar",
				note_icon="calendar",
				script=f"open('{ACCOUNTS_ROUTE}')",
			),
			stat(
				read("label_outstanding"),
				read("outstanding"),
				read("outstanding_note"),
				sub=read("sanctioned_line"),
				icon_name="database",
				script=f"open('{ACCOUNTS_ROUTE}')",
			),
		]
	)


def tasks():
	task = row(
		[
			column(
				[text("{{ dataItem.product }}", size="text-base"), muted("{{ dataItem.note }}")],
				gap="2px",
			),
			spacer(),
			toned_badge("{{ dataItem.stage }}", "dataItem.stage_tone"),
		],
		gap="10px",
		styles={"padding": "10px 0", "cursor": "pointer"},
		events=click("open(dataItem.url)"),
	)

	return card(
		"Waiting on you",
		read("tasks_note"),
		repeater(read("tasks"), task),
		visible="{{ overview.data.tasks && overview.data.tasks.length > 0 }}",
	)


def marker():
	# Both are rendered and `visible` picks one, because only props are evaluated, not styles.
	box = {"width": MARKER, "height": MARKER, "justifyContent": "center", "flex": "0 0 auto"}
	done = icon(
		"check",
		size=12,
		stroke=3,
		styles=dict(
			box,
			borderRadius="9999px",
			backgroundColor="var(--portal-primary-soft, var(--surface-green-6))",
			color="var(--portal-primary-deep, #fff)",
		),
		visible="{{ dataItem.tone === 'ok' }}",
	)
	dot = container(
		[
			container(
				styles={
					"width": DOT,
					"height": DOT,
					"borderRadius": "9999px",
					"backgroundColor": "var(--outline-gray-3)",
				}
			)
		],
		styles=dict(box, display="flex", alignItems="center"),
		visible="{{ dataItem.tone !== 'ok' }}",
	)

	return [done, dot]


def stems():
	# The payload sets `stem`: a repeated block cannot tell which copy is the last.

	def stem(tone, colour):
		return container(
			styles={
				"flex": "1 1 auto",
				"width": "1px",
				"marginBottom": STEM_GAP,
				"backgroundColor": colour,
			},
			visible="{{ dataItem.stem === '%s' }}" % tone,
		)

	return [stem("ok", "var(--portal-primary-line, var(--outline-green-3))"), stem("plain", "var(--outline-gray-1)")]


def activity():
	# Hand-drawn: ActivityTimeline's connector is one grey line no block can restyle.
	gutter = column(
		[*marker(), *stems()],
		gap=STEM_GAP,
		styles={"alignItems": "center", "width": "20px", "flex": "0 0 auto"},
	)
	lines = column(
		[
			text(
				"{{ dataItem.title }}",
				size="text-base",
				styles={"fontWeight": "500", "color": "var(--ink-gray-9)", "paddingTop": "1px"},
			),
			text("{{ dataItem.note }}", size="text-sm", styles={"color": "var(--ink-gray-5)"}),
		],
		gap="6px",
		styles={"flex": "1 1 auto", "minWidth": "0px", "paddingBottom": ROW_GAP},
	)
	date = text(
		"{{ dataItem.date }}",
		size="text-sm",
		styles={"color": "var(--ink-gray-5)", "paddingTop": "2px", "whiteSpace": "nowrap"},
	)
	event = row(
		[gutter, lines, date],
		gap="28px",
		align="stretch",
		styles={"cursor": "pointer"},
		events=click("open(dataItem.url)"),
	)

	return repeater(
		fallback(read("activity"), "[]"),
		event,
		styles={"flexDirection": "column", "flexWrap": "nowrap", "gap": "0px", "paddingTop": "4px"},
	)


def date_tile():
	quiet = {"color": "var(--ink-gray-5)", "lineHeight": "1.2"}

	return column(
		[
			text(
				"{{ dataItem.day }}",
				tag="div",
				size="text-lg",
				styles={"fontWeight": "600", "color": "var(--ink-gray-9)", "lineHeight": "1.2"},
			),
			text("{{ dataItem.month }}", tag="div", size="text-xs", styles=quiet),
			text("{{ dataItem.year }}", tag="div", size="text-xs", styles=quiet),
		],
		gap="1px",
		styles={
			"alignItems": "center",
			"justifyContent": "center",
			"width": DATE_TILE,
			"flex": "0 0 auto",
			"padding": "6px 0",
			"borderRadius": "var(--radius-4)",
			"backgroundColor": "var(--surface-gray-1)",
			"borderWidth": "1px",
			"borderStyle": "solid",
			"borderColor": "var(--outline-gray-1)",
		},
	)


def schedule():
	# `sub` is set only when the rows span several loans, see core.name_once.
	quiet = {"color": "var(--ink-gray-7)", "fontVariantNumeric": "tabular-nums"}
	lines = column(
		[
			text(
				"{{ dataItem.product }}",
				size="text-sm",
				styles={"fontWeight": "500", "color": "var(--ink-gray-8)"},
				visible="{{ dataItem.sub }}",
			),
			text("{{ dataItem.principal }}", size="text-sm", styles=quiet),
			text("{{ dataItem.interest }}", size="text-sm", styles=quiet),
		],
		gap="2px",
		styles={"flex": "1 1 auto", "minWidth": "0px"},
	)
	amount = text(
		"{{ dataItem.amount }}",
		size="text-base",
		styles={"fontWeight": "500", "color": "var(--ink-gray-9)", "whiteSpace": "nowrap"},
	)
	instalment = row(
		[date_tile(), lines, amount, chevron()],
		gap="14px",
		styles={"padding": "6px 0", "cursor": "pointer"},
		events=click("open(dataItem.url)"),
	)

	return repeater(
		read("schedule"),
		instalment,
		empty="Nothing due",
		styles={"flexDirection": "column", "flexWrap": "nowrap", "gap": "6px"},
	)


def content():
	return [
		summary(),
		tasks(),
		two_columns(
			[
				# A single application is already the strip's first card.
				card(
					"Application status",
					read("applications_note"),
					applications(read),
					visible="{{ (overview.data.applications || []).length > 1 }}",
				),
				card(
					"Activity timeline",
					read("activity_note"),
					activity(),
					# Less bottom padding: the last row's ROW_GAP already fills it.
					styles={"padding": "20px 20px 12px"},
					visible="{{ overview.data.activity && overview.data.activity.length > 0 }}",
				),
			],
			[
				card(
					"Scheduled repayments",
					read("schedule_note"),
					schedule(),
					action=button(
						"View all",
						script=f"open({SOURCE}.data.schedule_url || '{ACCOUNTS_ROUTE}')",
						variant="outline",
					),
					visible="{{ overview.data.schedule && overview.data.schedule.length > 0 }}",
				)
			],
		),
	]


def build():
	return upsert_page(
		TITLE,
		ROUTE,
		frame(SOURCE, content()),
		resources=[
			api_resource(SOURCE, "lending.portal.core.get_dashboard"),
			api_resource("alerts", "lending.portal.notifications.get_notifications", auto=0),
		],
		script=SCRIPT,
	)
