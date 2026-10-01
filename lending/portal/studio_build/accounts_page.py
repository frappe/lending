# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	PANEL,
	badge,
	card,
	column,
	fallback,
	icon,
	icon_tile,
	muted,
	pressable,
	reader,
	repeater,
	row,
	spacer,
	subject,
	text,
	toned_badge,
)
from lending.portal.studio_build.shell import frame

TITLE = "Choose an account"
ROUTE = "/accounts"
SOURCE = "accounts"
read = reader(SOURCE)

CHOOSE = '''\tconst choosing = ref("")

\tconst chooseAccount = (name: string) => {
\t\tif (choosing.value) return
\t\tchoosing.value = name
\t\tcall("lending.portal.switcher.choose_account", { name })
\t\t\t.then((result: any) => open(result?.url))
\t\t\t.catch((error: any) =>
\t\t\t\ttoast.error(String(error?.messages?.[0] || error?.message || error)),
\t\t\t)
\t\t\t.finally(() => { choosing.value = "" })
\t}'''

SCRIPT = page_script(body=CHOOSE, returns=["choosing", "chooseAccount"])


def account_card():
	about = column(
		[
			row(
				[
					subject("{{ dataItem.product }}"),
					badge("Viewing", theme="blue", visible="{{ dataItem.chosen }}"),
				],
				gap="8px",
				styles={"flexWrap": "wrap"},
			),
			muted("{{ dataItem.terms }}"),
			muted("{{ dataItem.customer }}", visible="{{ dataItem.customer }}"),
			row(
				[toned_badge("{{ dataItem.status_label }}", "dataItem.tone")],
				styles={"marginTop": "4px"},
			),
		],
		gap="2px",
		styles={"flex": "1 1 220px", "minWidth": "0px"},
	)
	figures = column(
		[
			muted("Outstanding"),
			text(
				"{{ dataItem.outstanding }}",
				tag="div",
				size="text-xl",
				styles={"fontWeight": "600", "color": "var(--ink-gray-9)"},
			),
			muted("{{ dataItem.against }}"),
			muted(
				"{{ 'Next due ' + dataItem.next_date + ' · ' + dataItem.next_amount }}",
				visible="{{ dataItem.next_amount }}",
			),
		],
		gap="2px",
		styles={"flex": "0 1 auto", "alignItems": "flex-end", "textAlign": "right"},
	)
	cursor, opens = pressable("chooseAccount(dataItem.name)")

	return row(
		[
			icon_tile("wallet"),
			about,
			spacer(),
			figures,
			icon("chevron-right", styles={"color": "var(--ink-gray-4)", "alignSelf": "center"}),
		],
		gap="12px",
		align="start",
		styles=dict(PANEL, flexWrap="wrap", **cursor),
		**opens,
	)


def content():
	return [
		card(
			"Your loan accounts",
			read("accounts_note"),
			repeater(
				fallback(read("accounts"), "[]"),
				account_card(),
				empty="No loan accounts yet",
				styles={"flexDirection": "column", "flexWrap": "nowrap", "gap": "10px"},
			),
		),
	]


def build():
	return upsert_page(
		TITLE,
		ROUTE,
		frame(SOURCE, content()),
		resources=[
			api_resource(SOURCE, "lending.portal.switcher.get_accounts_page"),
			api_resource("alerts", "lending.portal.notifications.get_notifications", auto=0),
		],
		script=SCRIPT,
	)
