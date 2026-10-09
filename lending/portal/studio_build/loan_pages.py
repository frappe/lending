# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	PANEL,
	any_row,
	block,
	button,
	column,
	container,
	divider,
	heading,
	icon,
	icon_tile,
	muted,
	no_rows,
	reader,
	repeater,
	row,
	spacer,
	subject,
	text,
	tile_styles,
)
from lending.portal.studio_build.shell import frame

DETAIL_SOURCE = "loan"
ALERTS = ("alerts", "lending.portal.notifications.get_notifications")

# The loan comes from the payload, not the route, because /loans names none.
REQUEST = '''\tconst requesting = ref(false)

\tconst openRequest = () => {
\t\trequestAmount.value = ""
\t\trequestOpen.value = true
\t}

\tconst sendRequest = () => {
\t\trequesting.value = true
\t\tcall("lending.portal.loans.request_disbursement", {
\t\t\tname: context.loan.data?.drawdown?.loan,
\t\t\tamount: requestAmount.value,
\t\t})
\t\t\t.then((result: any) => {
\t\t\t\ttoast.success(result?.message || "We have your request.")
\t\t\t\trequestOpen.value = false
\t\t\t\tcontext.loan.reload()
\t\t\t})
\t\t\t.catch((error: any) =>
\t\t\t\ttoast.error(String(error?.messages?.[0] || error?.message || error)),
\t\t\t)
\t\t\t.finally(() => { requesting.value = false })
\t}'''

DETAIL_SCRIPT = page_script(
	state=[("requestOpen", "false"), ("requestAmount", '""')],
	body=REQUEST,
	returns=["requesting", "openRequest", "sendRequest"],
)


def terms_card(read):
	term = TermCell(read)
	head = row(
		[
			icon_tile("file-text"),
			column([heading("Loan details"), muted(read("summary_note"))], gap="2px"),
			spacer(),
			drawdown_action(read),
		],
		gap="12px",
		align="start",
		styles={"flexWrap": "wrap"},
	)
	figures = column(
		[
			term.row(
				term("Loan amount (sanctioned)", "sanctioned"),
				term("Amount received", "disbursed"),
				term("Interest rate (p.a.)", "rate"),
				term("Tenure", "tenure"),
			),
			divider(),
			term.row(
				term("EMI amount", "instalment", note="frequency"),
				term("Total repayable", "total", hint="Principal plus all interest over the tenure"),
				term("Paid so far", "paid", note="written_off"),
				term("Next due date", "next_due", glyph="calendar"),
			),
		],
		gap="16px",
		visible=read("terms"),
	)

	return column([head, figures], gap="20px", styles=dict(PANEL, padding="20px"))


def drawdown_action(read):
	request = button(
		"Request disbursement",
		script="openRequest()",
		variant="solid",
		props={"size": "md"},
		visible=read("drawdown.open"),
	)
	note = muted(read("drawdown.note"), visible=read("drawdown.note"))

	return column([request, note], gap="4px", styles={"alignItems": "flex-end"})


def request_dialog(read):
	amount = block(
		"FormControl",
		props={
			"type": "number",
			"label": "Amount",
			"placeholder": "0.00",
			"required": True,
			"variant": "outline",
			"modelValue": {"$type": "variable", "name": "requestAmount"},
		},
	)
	actions = row(
		[
			spacer(),
			button("Cancel", script="requestOpen.value = false"),
			button(
				"Send request",
				script="sendRequest()",
				variant="solid",
				props={"disabled": "{{ !requestAmount }}", "loading": "{{ requesting }}"},
			),
		],
	)
	body = column(
		[
			muted(read("drawdown.note")),
			amount,
			muted("We will check your request and be in touch before we pay it out."),
			actions,
		],
		gap="12px",
	)

	return block(
		"Dialog",
		props={
			"modelValue": {"$type": "variable", "name": "requestOpen"},
			"title": "Request a disbursement",
			"size": "sm",
		},
		children=[body],
	)


class TermCell:
	# Wraps by the card's width, not a breakpoint: tablet styles only fire below a 768px viewport.

	GUTTER = 20

	def __init__(self, read):
		self.read = read

	def __call__(self, label, key, note=None, hint=None, glyph=None):
		return column(
			[self.label(label, hint), self.value(key, glyph), *self.note(note)],
			gap="4px",
			styles={
				"flex": "1 1 190px",
				"minWidth": "0px",
				"paddingInline": f"{self.GUTTER}px",
				"borderInlineStartWidth": "1px",
				"borderInlineStartStyle": "solid",
				"borderInlineStartColor": "var(--outline-gray-2)",
			},
		)

	def row(self, first, second, third, fourth):
		line = {"display": "flex", "flexWrap": "wrap", "rowGap": "16px"}
		pairs = [
			container(cells, styles=dict(line, flex="1 1 380px"))
			for cells in ([first, second], [third, fourth])
		]
		# Pulled left by one rule and gutter and clipped, so no wrapped line starts with a rule.
		pulled = container(pairs, styles=dict(line, marginInlineStart=f"-{self.GUTTER + 1}px"))

		# `overflow: hidden` zeroes a flex item's min height, so the page column would squash it.
		return container([pulled], styles={"overflow": "hidden", "flexShrink": "0"})

	def label(self, label, hint):
		words = text(label, size="text-sm", styles={"color": "var(--ink-gray-6)"})
		if not hint:
			return words

		mark = icon("info", size=14, hint=hint, styles={"color": "var(--ink-gray-5)", "cursor": "help"})
		return row([words, mark], gap="4px")

	def value(self, key, glyph):
		figure = text(
			self.read(f"terms.{key}"),
			tag="div",
			size="text-xl",
			styles={"fontWeight": "600", "fontVariantNumeric": "tabular-nums", "color": "var(--ink-gray-9)"},
		)
		if not glyph:
			return figure

		return row([icon(glyph, size=18, styles={"color": "var(--ink-gray-5)"}), figure], gap="8px")

	def note(self, key):
		if not key:
			return []

		expression = self.read(f"terms.{key}")
		return [muted(expression, visible=expression)]


def payoff_card(read):
	head = half_head(
		container([text("₹", tag="div", size="text-xl", styles=RUPEE)], styles=tile_styles()),
		"Payoff amount",
		"Total amount required to close this loan.",
	)
	figure = column(
		[
			text("Outstanding amount", size="text-sm", styles={"color": "var(--ink-gray-6)"}),
			text(read("payoff_total"), tag="div", size="text-3xl", styles=PAYOFF_FIGURE),
			text(read("payoff_note"), size="text-sm", styles={"marginTop": "4px", "color": "var(--ink-gray-5)"}),
		],
		gap="0px",
	)
	request = button(
		"Request closure",
		script="toast.success('We will be in touch about closing this loan.')",
		props={"size": "md"},
		styles={"width": "100%"},
	)

	return column([head, figure, request], gap="20px", styles=HALF_PANEL)


def charges_card(read):
	charges = read("charges")
	head = half_head(
		icon_tile("file-text"),
		"Charges",
		"Additional charges applicable on this loan.",
	)
	entry = row(
		[
			column(
				[
					subject("{{ dataItem.label }}"),
					muted("{{ dataItem.detail }}", visible="{{ dataItem.detail }}"),
				],
				gap="2px",
				styles={"minWidth": "0px"},
			),
			spacer(),
			text(
				"{{ dataItem.value }}",
				size="text-base",
				styles={"fontWeight": "600", "fontVariantNumeric": "tabular-nums", "whiteSpace": "nowrap"},
			),
		],
		gap="12px",
		styles={"padding": "10px 0"},
	)
	listed = repeater(charges, entry, visible=any_row(charges))

	return column([head, listed, charges_empty(charges)], gap="20px", styles=HALF_PANEL)


def charges_empty(charges):
	return column(
		[
			icon_tile("file", styles={"marginBottom": "10px"}),
			text(
				"No charges on this loan",
				size="text-base",
				styles={"fontWeight": "600", "color": "var(--ink-gray-9)"},
			),
			muted("Any processing fees or other charges will appear here.", styles={"textAlign": "center"}),
		],
		gap="4px",
		visible=no_rows(charges),
		styles={"flex": "1 1 auto", "alignItems": "center", "justifyContent": "center", "padding": "12px 16px 16px"},
	)


def half_head(tile, title, subtitle):
	return row(
		[
			tile,
			column(
				[
					heading(title, size="text-lg", styles={"letterSpacing": "0"}),
					muted(subtitle, styles={"letterSpacing": "0"}),
				],
				gap="2px",
			),
		],
		gap="12px",
		align="start",
	)


HALF_PANEL = dict(PANEL, padding="20px", flex="1 1 auto")

RUPEE = {"fontWeight": "500", "lineHeight": "1", "letterSpacing": "0"}
# Inter's narrower display cut; the text cut runs a tenth wider than the design here.
PAYOFF_FIGURE = {
	"marginTop": "6px",
	"fontSize": "27px",
	"fontWeight": "600",
	"letterSpacing": "-0.02em",
	"fontVariationSettings": "'opsz' 32, 'cv11' 1",
	"color": "var(--ink-gray-9)",
}


def detail_content(read):
	return [
		terms_card(read),
		side_by_side((payoff_card(read), "1 1 320px"), (charges_card(read), "1 1 320px")),
		request_dialog(read),
	]


def side_by_side(*cells):
	# Not `two_columns`: wraps by card width, for the reason TermCell gives.
	cell = {"display": "flex", "flexDirection": "column", "minWidth": "0px"}

	return container(
		[container([card], styles=dict(cell, flex=flex)) for card, flex in cells],
		styles={"display": "flex", "flexWrap": "wrap", "gap": "16px", "width": "100%"},
	)


def build_detail(title, route, params=None):
	read = reader(DETAIL_SOURCE)

	return upsert_page(
		title,
		route,
		frame(
			DETAIL_SOURCE,
			detail_content(read),
		),
		[
			api_resource(DETAIL_SOURCE, "lending.portal.loans.get_loan_detail", params=params),
			api_resource(*ALERTS, auto=0),
		],
		script=DETAIL_SCRIPT,
	)


def build():
	return (
		build_detail("Loan account", "/loans"),
		build_detail("Loan", "/loan/:name", params={"name": "{{ route.params.name }}"}),
	)
