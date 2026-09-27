# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The borrower's Account overview, as a Studio page.

It replaces the overview of the Builder portal this one was migrated from, and reads
the same payload: `lending.portal.core.get_dashboard`, unchanged. What differs is what
draws it -- a stage is a frappe-ui Badge rather than a styled span, and the record
tables are the List family rather than a grid of divs.

The scheduled repayments beside it are still a repeater, deliberately: a timeline is a
record of what happened, and those four rows are a diary of what has not.
"""

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
# Where every figure on this page is answered in full, and so where the two figure
# cards lead.
ACCOUNTS_ROUTE = "/loans"
read = reader(SOURCE)

# The timeline's geometry. The marker's box is the height of the title's line, so a
# marker of either size sits centred on it; the stem stops STEM_GAP short of the marker
# at each end.
MARKER = "18px"
DOT = "10px"
STEM_GAP = "4px"
# The row's own space below its lines, which the stem runs down through to the next.
ROW_GAP = "24px"
# Wide enough for "Nov" at the tile's size, and the same for every month.
DATE_TILE = "48px"

# A borrower with more than one loan chooses one before the overview reads as any of
# them. The overview is the app's home, so every sign-in passes through here.
SCRIPT = page_script(
	body='''\twatch(
\t\t() => context.overview?.data?.choose_account,
\t\t(choose) => { if (choose) router.replace("/accounts") },
\t\t{ immediate: true },
\t)'''
)


def application_card():
	"""The newest open application, as the record it is rather than as a figure.

	It sits in a strip of numbers and is not one. The product name is a headline at the
	weight of a heading, and the stage and the day it was raised share the line under it.
	What is waiting on the borrower follows, led by a dot in the stage's colour, and only
	when there is something to say.
	"""
	stage = f"{SOURCE}.data.application_stage"
	# The chevron waits for a destination: a borrower with nothing in progress reads the
	# same card saying so, and that one opens nothing.
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
	# The stage and the day on one line, so the card stays the height of the two figure
	# cards beside it.
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
	# The dot belongs to a card about something. The empty card's note is the whole
	# card, and stands without one.
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
	"""The stage, led by a team glyph while the application is with the lender.

	Two badges rather than one with a hidden glyph: Badge draws its prefix box whenever
	the slot exists, so a glyph hidden inside it still leaves the gap it would fill.
	"""
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
	"""A glyph, a quiet label and the value it names, set darker than the label."""
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
	"""A solid dot on a pale disc of its own colour, leading a line of status."""
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
	"""The three questions a borrower opens the portal with, in one strip.

	The application leads because it is the one with an answer from the first day: the
	two figures beside it read "Nothing due" and "No live accounts" until a loan is
	booked.

	Both figures are answered on the loan accounts page -- the instalment in its Next
	repayment column, the balance in its Outstanding one -- so both cards open it. The
	overview is a summary, and a summary that cannot be opened makes a borrower hunt
	down the rail for the page the figure came from.
	"""
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
	"""What is waiting on the borrower, directly under the figures.

	The strip hides itself when the payload has no tasks, so a borrower with nothing to
	do pays nothing for it.
	"""
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
	"""A check for a step of the loan itself, a grey dot for one that led up to it.

	The check is the application tracker's done step -- a wash of the lender's primary
	colour with a tick in its deep shade -- so "done" looks the same on every page. Green
	where no primary is set.

	Both are in the tree and the row's `tone` shows one, because a fill is a style and
	only props are evaluated. The dot sits in a box the check's size, so the two centre
	on the same line.
	"""
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
	"""The line down to the next marker: green between two steps that are both done.

	The payload decides which, and that there is none under the last row -- a repeated
	block cannot tell which copy of it is the last.
	"""

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
	"""The record of the account: a marker per event, and a stem joining it to the next.

	Drawn by hand rather than on @framework/ui's ActivityTimeline, whose gutter no block
	reaches -- its connector is one grey line, and this one turns green between two
	steps that are done.

	The stem runs through the space under a row's lines, so that space is the lines'
	padding rather than a gap between rows: a gap is outside every row, and nothing
	could be drawn across it.
	"""
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
	"""The day an instalment falls due, as a leaf off a desk calendar.

	The day leads because it is what a borrower checks against payday; the month and
	year under it are only there to say which one.
	"""
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
	"""The four instalments coming, as a diary rather than a record.

	Principal and interest take a line each: joined on one, the pair wrapped at the dot
	between them. The loan's name leads only when the rows are of several loans --
	`sub` is set only then, see core.name_once.
	"""
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
				# Only for several: one application is already the strip's first card, and
				# the table would say it a second time right under it.
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
					# The last row's own ROW_GAP is most of the space under it, so the
					# card's padding gives up the difference at the bottom.
					styles={"padding": "20px 20px 12px"},
					visible="{{ overview.data.activity && overview.data.activity.length > 0 }}",
				),
			],
			[
				card(
					"Scheduled repayments",
					read("schedule_note"),
					schedule(),
					# The rest of the schedule: the loan's own page when there is one loan,
					# the list of them when there are several.
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
		# No header action: the two figure cards and the rail already open the loan page.
		frame(SOURCE, content()),
		resources=[
			api_resource(SOURCE, "lending.portal.core.get_dashboard"),
			api_resource("alerts", "lending.portal.notifications.get_notifications", auto=0),
		],
		script=SCRIPT,
	)
