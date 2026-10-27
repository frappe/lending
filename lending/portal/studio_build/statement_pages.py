# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	DATE_FORMAT,
	PANEL,
	block,
	button,
	card,
	column,
	container,
	fallback,
	heading,
	icon_line,
	icon_tile,
	muted,
	no_rows,
	reader,
	record_list,
	row,
	spacer,
	subject,
	text,
)
from lending.portal.studio_build.shell import frame

STATEMENT = "statement"
CERTIFICATE = "certificate"
ALERTS = ("alerts", "lending.portal.notifications.get_notifications")


def download(source, read, label=None):
	# The URL comes from the payload, so it follows the period picked on screen.
	return button(
		label or read("download_label"),
		# The theme preview sends no URL: its PDF would be built from real loan records.
		script=f"{source}.data.download_url && window.open({source}.data.download_url, '_blank')",
		variant="solid",
	)


def date_field(label, state):
	return block(
		"FormControl",
		props={
			"type": "date",
			"label": label,
			# An empty date falls back to the endpoint's default, so the picker would show nothing.
			"clearable": False,
			"format": DATE_FORMAT,
			"modelValue": {"$type": "variable", "name": state},
		},
		styles={"width": "172px"},
	)


# FY is the Indian financial year (April to March), as in `lending.portal.statement`.
PERIODS = (("This FY", "this_year"), ("Last FY", "last_year"), ("Last 3 months", "last_quarter"))


def period_bar(read):
	ranges = row(
		[button(label, script=f"setPeriod('{period}')", classes=["portal-plain"]) for label, period in PERIODS],
		gap="6px",
	)
	fields = row(
		[date_field("From", "fromDate"), date_field("To", "toDate"), ranges],
		gap="12px",
		align="end",
		styles={"flexWrap": "wrap"},
	)

	return row(
		[fields, spacer(), download(STATEMENT, read)],
		gap="12px",
		align="end",
		styles=dict(PANEL, flexWrap="wrap"),
	)


FIGURE = {"fontWeight": "600", "fontVariantNumeric": "tabular-nums", "color": "var(--ink-gray-9)"}
AMOUNT = {"fontVariantNumeric": "tabular-nums", "whiteSpace": "nowrap"}

# frappe-ui sets this only on clickable rows, and the published bundle drops ListRow styles.
ROW_INSET = {"--_list-row-pad": "12px"}

# The published bundle drops ListRow padding, so the height comes from the List's own variable.
LEDGER_ROW = {"--list-row-height": "44px"}


def summary_strip(read):
	return ruled_panel(
		[
			figure_cell("Opening balance", read("summary.opening"), "Owed when the period began"),
			figure_cell("Charged", read("summary.charged"), "Loan amount, interest and charges"),
			figure_cell("Paid", read("summary.paid"), "Payments you made"),
			figure_cell("Closing balance", read("summary.balance"), read("summary.balance_note")),
		]
	)


def ledger(read):
	amount = {"size": "text-base", "styles": dict(AMOUNT, color="var(--ink-gray-8)")}
	table = record_list(
		[
			("minmax(104px, 0.8fr)", "Date"),
			("minmax(0, 2fr)", "Particulars"),
			("minmax(0, 1fr)", "Charged", "end"),
			("minmax(0, 1fr)", "Paid", "end"),
			("minmax(0, 1fr)", "Balance", "end"),
		],
		read("rows"),
		[
			[text("{{ item.date }}", size="text-base", styles={"color": "var(--ink-gray-6)", "whiteSpace": "nowrap"})],
			[subject("{{ item.label }}", styles={"color": "var(--ink-gray-8)"})],
			[text("{{ item.debit }}", **amount)],
			[text("{{ item.credit }}", **amount)],
			[text("{{ item.balance }}", size="text-base", styles=dict(AMOUNT, fontWeight="500", color="var(--ink-gray-9)"))],
		],
	)
	table["baseStyles"].update(ROW_INSET, **LEDGER_ROW, minWidth="640px")

	return container([table], styles={"overflowX": "auto"})


def ledger_empty(read):
	return column(
		[
			icon_tile("file", "gray", styles={"marginBottom": "8px"}),
			text(
				"No transactions in this period",
				size="text-base",
				styles={"fontWeight": "600", "color": "var(--ink-gray-9)"},
			),
			muted("Pick a wider range above to see earlier entries.", styles={"textAlign": "center"}),
		],
		gap="4px",
		visible=no_rows(read("rows")),
		styles={"alignItems": "center", "padding": "32px 16px"},
	)


def statement_content(read):
	return [
		period_bar(read),
		summary_strip(read),
		card("Transactions", read("rows_note"), column([ledger(read), ledger_empty(read)], gap="0px")),
	]


# Function declarations, not consts: the refs that call them are declared above this body.
STATEMENT_SCRIPT = """\
\tfunction isoDay(day: Date) {
\t\tconst pad = (n: number) => String(n).padStart(2, "0")
\t\treturn `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
\t}

\tfunction yearStart(yearsBack = 0) {
\t\tconst today = new Date()
\t\tconst start = today.getFullYear() - (today.getMonth() < 3 ? 1 : 0) - yearsBack
\t\treturn new Date(start, 3, 1)
\t}

\tconst setPeriod = (period: string) => {
\t\tconst today = new Date()
\t\tif (period === "last_year") {
\t\t\tconst start = yearStart(1)
\t\t\tfromDate.value = isoDay(start)
\t\t\ttoDate.value = isoDay(new Date(start.getFullYear() + 1, 2, 31))
\t\t} else if (period === "last_quarter") {
\t\t\tfromDate.value = isoDay(new Date(today.getFullYear(), today.getMonth() - 3, today.getDate()))
\t\t\ttoDate.value = isoDay(today)
\t\t} else {
\t\t\tfromDate.value = isoDay(yearStart())
\t\t\ttoDate.value = isoDay(today)
\t\t}
\t}"""


def build_statement():
	read = reader(STATEMENT)

	return upsert_page(
		"Statement of account",
		"/statement",
		frame(STATEMENT, statement_content(read)),
		[
			api_resource(
				STATEMENT,
				"lending.portal.statement.get_statement_page",
				params={"from_date": "{{ fromDate }}", "to_date": "{{ toDate }}"},
			),
			api_resource(*ALERTS, auto=0),
		],
		script=page_script(
			state=[("fromDate", "isoDay(yearStart())"), ("toDate", "isoDay(new Date())")],
			body=STATEMENT_SCRIPT,
			returns=["setPeriod"],
		),
	)


def year_picker(read):
	return block(
		"FormControl",
		props={
			"type": "select",
			"options": fallback(read("years"), "[]"),
			"modelValue": {"$type": "variable", "name": "year"},
		},
		styles={"width": "140px"},
	)


def year_head(read):
	kind = block(
		"Badge",
		props={"label": read("kind"), "theme": read("kind_theme"), "variant": "subtle", "size": "md"},
	)
	title = column(
		[row([heading(read("year_label")), kind], gap="8px"), muted(read("rows_note"))],
		gap="4px",
		styles={"minWidth": "0px"},
	)
	controls = row(
		[year_picker(read), download(CERTIFICATE, read, "Download certificate")],
		gap="8px",
		styles={"flexWrap": "wrap"},
	)

	return row([title, spacer(), controls], gap="16px", styles={"flexWrap": "wrap"})


FIGURE_INSET = 20


def figure_cell(title, value, note, **kwargs):
	return column(
		[
			text(title, size="text-sm", styles={"color": "var(--ink-gray-6)"}),
			text(value, tag="div", size="text-2xl", styles=FIGURE),
			muted(note),
		],
		gap="4px",
		styles={
			"minWidth": "0px",
			"paddingInlineStart": f"{FIGURE_INSET}px",
			"paddingInlineEnd": f"{FIGURE_INSET}px",
			"borderInlineStart": "1px solid var(--outline-gray-1)",
		},
		**kwargs,
	)


def paid_summary(read):
	return ruled_panel(
		[
			figure_cell("Interest paid", read("summary.interest"), "On your loans this year"),
			figure_cell("Principal repaid", read("summary.principal"), "Towards the amount borrowed"),
			figure_cell(
				"Penalty and charges",
				read("summary.other"),
				"Late fees and other charges",
				visible=read("summary.other"),
			),
			figure_cell("Total paid", read("summary.total"), "Interest, principal and charges"),
		]
	)


def ruled_panel(cells):
	# Pulled left by one inset and rule and clipped, so no wrapped line starts with a rule.
	grid = container(
		cells,
		styles={
			"display": "grid",
			"gridTemplateColumns": "repeat(auto-fit, minmax(200px, 1fr))",
			"rowGap": "20px",
			"marginInlineStart": f"-{FIGURE_INSET + 1}px",
		},
	)

	return container([grid], styles=dict(PANEL, overflow="hidden", padding="20px"))


def disclaimer(read):
	return icon_line(
		"info",
		read("disclaimer"),
		visible=read("disclaimer"),
		styles={"paddingTop": "12px", "borderTop": "1px solid var(--outline-gray-1)"},
	)


def accounts_table(read):
	amount = {"size": "text-base", "styles": AMOUNT}
	table = record_list(
		[
			("minmax(0, 2fr)", "Loan"),
			("minmax(0, 1fr)", "Interest"),
			("minmax(0, 1fr)", "Principal"),
			("minmax(0, 1fr)", "Total"),
		],
		read("accounts"),
		[
			[subject("{{ item.label }}"), muted("{{ item.value }}")],
			[text("{{ item.interest }}", **amount)],
			[text("{{ item.principal }}", **amount)],
			[text("{{ item.total }}", size="text-base", styles=dict(AMOUNT, fontWeight="500"))],
		],
	)
	table["baseStyles"].update(ROW_INSET, minWidth="520px")

	return container([table], styles={"overflowX": "auto"})


def certificate_content(read):
	return [
		year_head(read),
		paid_summary(read),
		card(
			"Accounts covered",
			read("accounts_note"),
			column([accounts_table(read), disclaimer(read)], gap="12px"),
		),
	]


CERTIFICATE_SCRIPT = """\
\tfunction currentYear() {
\t\tconst today = new Date()
\t\tconst start = today.getFullYear() - (today.getMonth() < 3 ? 1 : 0)
\t\treturn `${start}-${start + 1}`
\t}"""


def build_certificate():
	read = reader(CERTIFICATE)

	return upsert_page(
		"Interest certificate",
		"/certificate",
		frame(CERTIFICATE, certificate_content(read)),
		[
			api_resource(
				CERTIFICATE,
				"lending.portal.statement.get_certificate_page",
				params={"year": "{{ year }}"},
			),
			api_resource(*ALERTS, auto=0),
		],
		script=page_script(state=[("year", "currentYear()")], body=CERTIFICATE_SCRIPT),
	)


def build():
	return build_statement(), build_certificate()
