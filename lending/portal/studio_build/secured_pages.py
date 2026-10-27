# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.apply_page import choice
from lending.portal.studio_build.blocks import (
	PANEL,
	alert,
	badge,
	block,
	button,
	card,
	click,
	column,
	container,
	fallback,
	heading,
	icon,
	icon_tile,
	muted,
	reader,
	repeater,
	row,
	spacer,
	text,
)
from lending.portal.studio_build.public import page as public_page
from lending.portal.studio_build.shell import frame

SOURCE = "securedLoan"
read = reader(SOURCE)

ROUTE = "/secured-loan"
CONSENT_ROUTE = "/kyc-consent"
REGISTER_ROUTE = "/register"

TENURES = (6, 12, 18, 24, 36)
CIRCLE = 28
ACCENT = "var(--portal-primary, var(--surface-gray-9))"
ACCENT_INK = "var(--portal-primary-ink, var(--ink-base))"

SCRIPT = '''\tconst page = computed<any>(() => context.%(source)s.data || {})
\tconst busy = ref(false)
\tconst viewing = ref("")
\tconst shown = computed(() => viewing.value || page.value.current || "")

\tconst fail = (error: any) => toast.error(String(error?.messages?.[0] || error?.message || error))
\t// Endpoints answer a provider's refusal with ok: false, so the logged attempt is kept.
\tconst run = (method: string, args: Record<string, any>, then?: (result: any) => void) => {
\t\tbusy.value = true
\t\treturn call(`lending.portal.secured.${method}`, args)
\t\t\t.then((result: any) => {
\t\t\t\tif (result?.ok === false) { toast.error(result.message); return }
\t\t\t\tif (result?.message) toast.success(result.message)
\t\t\t\tthen?.(result)
\t\t\t})
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}
\tconst advance = () => {
\t\tviewing.value = ""
\t\tcontext.%(source)s.reload()
\t}
\tconst viewStep = (row: any) => {
\t\tif (row.state !== "todo") viewing.value = row.key === page.value.current ? "" : row.key
\t}

\tconst money = (amount: number) =>
\t\tnew Intl.NumberFormat("en-IN", { style: "currency", currency: page.value.currency || "INR", maximumFractionDigits: 0 }).format(amount || 0)

\tconst verifyPan = () => run("verify_pan", { pan: pan.value }, advance)

\tconst sendHoldingsOtp = () =>
\t\trun("send_holdings_otp", { collateral: collateral.value }, (result) => { holdingsRequest.value = result.request_id })
\tconst fetchHoldings = () =>
\t\trun("fetch_holdings", { collateral: collateral.value, request_id: holdingsRequest.value, otp: holdingsOtp.value }, (result) => {
\t\t\tnotApproved.value = result.not_approved || []
\t\t\tholdingsRequest.value = ""
\t\t\tholdingsOtp.value = ""
\t\t\tadvance()
\t\t})
\tconst refetch = () => { viewing.value = "eligibility" }

\tconst holdings = computed<any[]>(() => page.value.holdings || [])
\t// One line per purchase lot, so a fund's units are the sum of its lines.
\twatch(() => page.value.application?.lines, (lines) => {
\t\tif (!lines?.length) return
\t\tconst saved: Record<string, number> = {}
\t\tlines.forEach((line: any) => { saved[line.holding] = (saved[line.holding] || 0) + line.units })
\t\tchosen.value = Object.keys(saved)
\t\tunits.value = Object.fromEntries(Object.entries(saved).map(([holding, count]) => [holding, String(count)]))
\t}, { immediate: true })
\tconst toggle = (holding: any) => {
\t\tif (sent.value || !holding.pledgeable_units) return
\t\tif (chosen.value.includes(holding.holding)) {
\t\t\tchosen.value = chosen.value.filter((name) => name !== holding.holding)
\t\t\treturn
\t\t}
\t\tchosen.value = [...chosen.value, holding.holding]
\t\tunits.value = { ...units.value, [holding.holding]: String(holding.pledgeable_units) }
\t}
\tconst setUnits = (holding: string, value: any) => { units.value = { ...units.value, [holding]: String(value ?? "") } }
\tconst unitsOf = (row: any) => Number(units.value[row.holding] || 0)
\tconst unitsValid = (row: any) => unitsOf(row) > 0 && unitsOf(row) <= row.pledgeable_units
\t// The same sum the server makes: units × NAV, less the fund's haircut.
\tconst lends = (row: any) => (unitsValid(row) ? unitsOf(row) * row.nav * (1 - row.haircut / 100) : 0)
\tconst sent = computed(() => Boolean(page.value.application?.sent))
\tconst chosenRows = computed(() => holdings.value.filter((row) => chosen.value.includes(row.holding)))
\tconst chosenEligible = computed(() => chosenRows.value.reduce((sum, row) => sum + lends(row), 0))
\tconst limit = computed(() => {
\t\tconst ceiling = page.value.product?.maximum || 0
\t\treturn Math.floor(ceiling ? Math.min(chosenEligible.value, ceiling) : chosenEligible.value)
\t})
\tconst useLimit = () => { loanAmount.value = String(limit.value) }
\twatch(() => page.value.application?.amount, (amount) => { if (amount) loanAmount.value = String(amount) }, { immediate: true })
\twatch(() => page.value.application?.tenure, (months) => { if (months) tenure.value = String(months) }, { immediate: true })
\tconst canApply = computed(() =>
\t\tchosenRows.value.length > 0 && chosenRows.value.every(unitsValid)
\t\t&& Number(loanAmount.value) > 0 && Number(loanAmount.value) <= limit.value)
\tconst startApplication = () =>
\t\trun("start_application", {
\t\t\tcollateral: collateral.value,
\t\t\tlines: JSON.stringify(chosenRows.value.map((row) => ({ holding: row.holding, units: unitsOf(row) }))),
\t\t\tloan_amount: loanAmount.value,
\t\t\ttenure: tenure.value,
\t\t}, advance)

\t// A provider's page is another site, so this is a full load, not a router push.
\tconst startKyc = () => run("start_kyc", {}, (result) => { window.location.href = result.redirect_url })
\tconst completeKyc = () => run("complete_kyc", {}, advance)
\tlet askedKyc = false
\twatch(() => page.value.kyc?.status, (status) => {
\t\tif (status !== "Pending" || askedKyc || context.route.query.step !== "kyc") return
\t\taskedKyc = true
\t\tcompleteKyc()
\t}, { immediate: true })

\tconst sendPledgeOtp = () => run("send_pledge_otp", {}, () => { pledgeSent.value = true })
\tconst confirmPledge = () => run("confirm_pledge", { otp: pledgeOtp.value }, () => { pledgeSent.value = false; advance() })

\tconst saveBank = () => run("save_bank_account", { account_number: accountNumber.value, ifsc: ifsc.value }, advance)

\tconst sendEsignOtp = () => run("send_esign_otp", {}, () => {
\t\tesignSent.value = true
\t\tcontext.%(source)s.reload()
\t})
\tconst confirmEsign = () => run("confirm_esign", { otp: esignOtp.value }, () => { esignSent.value = false; advance() })

\twatch(() => page.value.loan?.available, (available) => { if (available) withdrawAmount.value = String(Math.floor(available)) }, { immediate: true })
\tconst withdraw = () => run("withdraw", { amount: withdrawAmount.value }, advance)''' % {
	"source": SOURCE
}

STATE = [
	("pan", '""'),
	("collateral", '"Mutual Funds"'),
	("holdingsRequest", '""'),
	("holdingsOtp", '""'),
	("notApproved", "[]"),
	("chosen", "[] as string[]"),
	("units", "{} as Record<string, string>"),
	("loanAmount", '""'),
	("tenure", '"12"'),
	("pledgeOtp", '""'),
	("pledgeSent", "false"),
	("accountNumber", '""'),
	("confirmAccount", '""'),
	("ifsc", '""'),
	("esignOtp", '""'),
	("esignSent", "false"),
	("withdrawAmount", '""'),
]

RETURNS = [
	"busy",
	"shown",
	"viewStep",
	"money",
	"verifyPan",
	"sendHoldingsOtp",
	"fetchHoldings",
	"refetch",
	"toggle",
	"setUnits",
	"unitsValid",
	"lends",
	"sent",
	"chosenEligible",
	"limit",
	"useLimit",
	"canApply",
	"startApplication",
	"startKyc",
	"completeKyc",
	"sendPledgeOtp",
	"confirmPledge",
	"saveBank",
	"sendEsignOtp",
	"confirmEsign",
	"withdraw",
]


def build():
	return [build_journey(), build_consent(), build_register()]


def build_journey():
	return upsert_page(
		"Loan against securities",
		ROUTE,
		frame(
			SOURCE,
			[
				stepper(),
				registration_panel(),
				pan_panel(),
				eligibility_panel(),
				vault_panel(),
				kyc_panel(),
				pledge_panel(),
				bank_panel(),
				esign_panel(),
				loan_panel(),
			],
		),
		[
			api_resource(SOURCE, "lending.portal.secured.get_secured_loan"),
			api_resource("alerts", "lending.portal.notifications.get_notifications", auto=0),
		],
		script=page_script(state=STATE, body=SCRIPT, returns=RETURNS),
	)


# Stepper


def stepper():
	connector = {
		"position": "absolute",
		"top": f"{CIRCLE / 2 - 1}px",
		"left": "50%",
		"width": "100%",
		"height": "2px",
	}
	circle = {
		"width": f"{CIRCLE}px",
		"height": f"{CIRCLE}px",
		"borderRadius": "9999px",
		"display": "flex",
		"alignItems": "center",
		"justifyContent": "center",
		"position": "relative",
		"zIndex": "1",
		"flexShrink": "0",
	}
	not_last = "dataItem.key !== 'loan'"
	viewed = "dataItem.key === shown"
	halo = 10
	step = column(
		[
			# The step whose panel is open; a past step otherwise looks like every other done step.
			container(
				styles={
					"position": "absolute",
					"top": f"-{halo // 2}px",
					"left": f"calc(50% - {(CIRCLE + halo) // 2}px)",
					"width": f"{CIRCLE + halo}px",
					"height": f"{CIRCLE + halo}px",
					"borderRadius": "9999px",
					"border": f"2px solid {ACCENT}",
					"backgroundColor": "var(--surface-base)",
					"zIndex": "1",
					"pointerEvents": "none",
				},
				visible="{{ %s && dataItem.state === 'done' }}" % viewed,
			),
			container(
				styles=dict(connector, backgroundColor=ACCENT),
				visible="{{ %s && dataItem.state === 'done' }}" % not_last,
			),
			container(
				styles=dict(connector, backgroundColor="var(--outline-gray-2)"),
				visible="{{ %s && dataItem.state !== 'done' }}" % not_last,
			),
			row(
				[icon("check", size=14, stroke=3)],
				styles=dict(circle, backgroundColor=ACCENT, color=ACCENT_INK),
				visible="{{ dataItem.state === 'done' }}",
			),
			row(
				[container(styles={"width": "10px", "height": "10px", "borderRadius": "9999px", "backgroundColor": ACCENT})],
				styles=dict(circle, backgroundColor="var(--surface-base)", border=f"2px solid {ACCENT}"),
				visible="{{ dataItem.state === 'now' }}",
			),
			container(
				styles=dict(circle, backgroundColor="var(--surface-base)", border="2px solid var(--outline-gray-3)"),
				visible="{{ dataItem.state === 'todo' }}",
			),
			text(
				"{{ dataItem.label }}",
				size="text-xs",
				styles={"textAlign": "center", "color": "var(--ink-gray-9)", "fontWeight": "600"},
				visible="{{ %s }}" % viewed,
			),
			text(
				"{{ dataItem.label }}",
				size="text-xs",
				styles={"textAlign": "center", "color": "var(--ink-gray-7)", "fontWeight": "500"},
				visible="{{ !(%s) && dataItem.state !== 'todo' }}" % viewed,
			),
			text(
				"{{ dataItem.label }}",
				size="text-xs",
				styles={"textAlign": "center", "color": "var(--ink-gray-5)"},
				visible="{{ !(%s) && dataItem.state === 'todo' }}" % viewed,
			),
		],
		gap="8px",
		styles={
			"position": "relative",
			"alignItems": "center",
			"flex": "1 1 0%",
			"minWidth": "76px",
			"cursor": "pointer",
		},
		events=click("viewStep(dataItem)"),
	)
	steps = repeater(
		fallback(read("steps"), "[]"),
		step,
		data_key="key",
		# The top padding keeps the viewed step's ring inside the scroll box, which clips both axes.
		styles={
			"display": "flex",
			"flexDirection": "row",
			"width": "100%",
			"overflowX": "auto",
			"paddingTop": f"{halo // 2}px",
			"paddingBottom": "4px",
		},
	)

	return container([steps], styles=dict(PANEL, padding="20px 12px 16px"))


# Panels


def panel(key, title, subtitle, body, **kwargs):
	return card(
		title,
		subtitle,
		column(body, gap="14px"),
		styles={"padding": "20px 24px"},
		visible="{{ shown === '%s' }}" % key,
		**kwargs,
	)


def done_line(message, visible):
	return row(
		[icon_tile("check", theme="green", tile=28, glyph=14), text(message, size="text-base")],
		gap="10px",
		visible=visible,
	)


def field(label, ref_name, kind="text", placeholder="", **kwargs):
	return block(
		"FormControl",
		props={
			"type": kind,
			"label": label,
			"size": "md",
			"variant": "subtle",
			"placeholder": placeholder,
			"modelValue": {"$type": "variable", "name": ref_name},
		},
		**kwargs,
	)


def action(label, script, enabled=None, variant="solid", **kwargs):
	props = {"size": "md", "loading": "{{ busy }}"}
	if enabled:
		props["disabled"] = "{{ !(%s) }}" % enabled

	return button(label, script=script, variant=variant, props=props, **kwargs)


def actions(*parts, **kwargs):
	return row([spacer(), *parts], gap="8px", **kwargs)


def form_grid(fields, columns=2, **kwargs):
	return container(
		fields,
		styles={
			"display": "grid",
			"gridTemplateColumns": f"repeat({columns}, minmax(0, 1fr))",
			"gap": "12px",
			"maxWidth": "560px",
		},
		mobile={"gridTemplateColumns": "minmax(0, 1fr)"},
		**kwargs,
	)


def registration_panel():
	return panel(
		"registration",
		"Registration",
		"",
		[done_line("You are signed in as {{ %s.data.customer_name }}." % SOURCE, None)],
	)


def pan_panel():
	verified = "%s.data?.pan?.verified" % SOURCE
	form = column(
		[
			form_grid([field("PAN", "pan", placeholder="ABCDE1234F")]),
			actions(action("Verify PAN", "verifyPan()", enabled="pan.length === 10")),
		],
		gap="14px",
		visible="{{ !%s }}" % verified,
	)

	return panel(
		"pan",
		"Verify your PAN",
		"Enter the PAN in your own name. We check it against the Income Tax records.",
		[
			done_line(
				"PAN {{ %s.data.pan.pan }} is verified, in the name of {{ %s.data.pan.name }}." % (SOURCE, SOURCE),
				"{{ %s }}" % verified,
			),
			form,
		],
	)


def eligibility_panel():
	picker = block(
		"FormControl",
		props={
			"type": "select",
			"label": "What would you like to borrow against?",
			"size": "md",
			"variant": "subtle",
			"options": fallback(read("collaterals"), "[]"),
			"modelValue": {"$type": "variable", "name": "collateral"},
		},
	)
	otp = column(
		[
			field("OTP", "holdingsOtp", kind="password", placeholder="6 digits"),
			muted("Sent to the mobile number registered with your mutual funds."),
		],
		gap="6px",
		visible="{{ holdingsRequest }}",
	)

	return panel(
		"eligibility",
		"Check your eligibility",
		"Choose what to borrow against. We fetch your mutual funds from CAMS and KFintech with an OTP, so you need not upload a statement.",
		[
			form_grid([picker, otp]),
			actions(
				action("Send OTP", "sendHoldingsOtp()", visible="{{ !holdingsRequest }}"),
				button("Resend OTP", script="sendHoldingsOtp()", props={"size": "md"}, visible="{{ holdingsRequest }}"),
				action("Fetch my funds", "fetchHoldings()", enabled="holdingsOtp.length >= 4", visible="{{ holdingsRequest }}"),
			),
		],
	)


def figure(label, value, note=None):
	return column(
		[
			muted(label),
			text(value, tag="div", size="text-2xl", styles={"fontWeight": "600", "color": "var(--ink-gray-9)"}),
			*([muted(note)] if note else []),
		],
		gap="2px",
		styles=dict(PANEL, flex="1 1 200px"),
	)


def holding_choice():
	left = column(
		[
			text("{{ dataItem.scheme }}", size="text-base", styles={"fontWeight": "600", "color": "var(--ink-gray-9)"}),
			muted("Folio {{ dataItem.folio }} · {{ dataItem.units }} units at {{ dataItem.nav_label }}"),
			muted("{{ dataItem.note }}", styles={"color": "var(--ink-amber-7, var(--ink-gray-6))"}, visible="{{ dataItem.note }}"),
		],
		gap="2px",
		styles={"flex": "1 1 auto", "minWidth": "0px"},
	)
	right = column(
		[
			text("{{ dataItem.eligible_label }}", size="text-base", styles={"fontWeight": "600", "textAlign": "right"}),
			muted("of {{ dataItem.value_label }} · {{ dataItem.haircut_label }}", styles={"textAlign": "right"}),
		],
		gap="2px",
		styles={"alignItems": "flex-end"},
	)

	chosen = "chosen.includes(dataItem.holding)"

	return column(
		[choice([left, right], "toggle(dataItem)", chosen), units_box(chosen)],
		gap="0px",
	)


def units_box(chosen):
	units = block(
		"FormControl",
		props={
			"type": "number",
			"size": "sm",
			"variant": "outline",
			"modelValue": "{{ units[dataItem.holding] }}",
			"disabled": "{{ sent }}",
		},
		events={
			"update:modelValue": {
				"event": "update:modelValue",
				"action": "Run Script",
				"script": "setUnits(dataItem.holding, eventArgs[0])",
			}
		},
		styles={"width": "140px"},
	)
	invalid = "!unitsValid(dataItem)"

	return row(
		[
			text("Units to pledge", size="text-sm", styles={"color": "var(--ink-gray-7)", "whiteSpace": "nowrap"}),
			units,
			muted("{{ 'of ' + dataItem.pledgeable_units + ' you can pledge' }}"),
			spacer(),
			text(
				"{{ 'Lends ' + money(lends(dataItem)) }}",
				size="text-sm",
				styles={"fontWeight": "600", "color": "var(--ink-gray-9)", "whiteSpace": "nowrap"},
				visible="{{ !(%s) }}" % invalid,
			),
			text(
				"{{ 'Enter 1 to ' + dataItem.pledgeable_units + ' units' }}",
				size="text-sm",
				styles={"color": "var(--ink-red-4, var(--ink-gray-7))", "whiteSpace": "nowrap"},
				visible="{{ %s }}" % invalid,
			),
		],
		gap="10px",
		styles={
			"padding": "10px 16px",
			"marginTop": "-6px",
			"borderWidth": "0px 1px 1px 1px",
			"borderStyle": "solid",
			"borderColor": "var(--outline-gray-2)",
			"borderRadius": "0 0 var(--radius-4) var(--radius-4)",
			"backgroundColor": "var(--surface-gray-1)",
		},
		mobile={"flexWrap": "wrap"},
		visible="{{ %s }}" % chosen,
	)


def vault_panel():
	# Once sent, the units are pledged to this application, so the holdings no longer offer them.
	totals = row(
		[
			figure("Portfolio value", read("totals.value")),
			figure("You can borrow up to", read("totals.eligible"), "After the haircut on each fund"),
			figure("Rate of interest", read("product.rate"), read("product.label")),
		],
		gap="12px",
		align="stretch",
		styles={"flexWrap": "wrap"},
		visible="{{ !sent }}",
	)
	funds = repeater(
		fallback(read("holdings"), "[]"),
		holding_choice(),
		data_key="holding",
		empty="No funds yet. Check your eligibility first.",
		styles={"display": "flex", "flexDirection": "column", "gap": "10px"},
		visible="{{ !sent }}",
	)
	tenure = block(
		"FormControl",
		props={
			"type": "select",
			"label": "Repay over",
			"size": "md",
			"variant": "subtle",
			"options": [{"label": f"{months} months", "value": str(months)} for months in TENURES],
			"modelValue": {"$type": "variable", "name": "tenure"},
			"disabled": "{{ sent }}",
		},
		visible="{{ %s.data?.product?.asks_tenure }}" % SOURCE,
	)
	amount = column(
		[
			block(
				"FormControl",
				props={
					"type": "number",
					"label": "Loan amount",
					"size": "md",
					"variant": "subtle",
					"placeholder": "{{ 'Up to ' + money(limit) }}",
					"disabled": "{{ sent }}",
					"modelValue": {"$type": "variable", "name": "loanAmount"},
				},
			),
			row(
				[
					muted("{{ 'Selected funds let you borrow up to ' + money(limit) }}"),
					text(
						"Use this",
						styles={"color": "var(--ink-gray-9)", "fontWeight": "500", "cursor": "pointer", "whiteSpace": "nowrap"},
						events=click("useLimit()"),
						visible="{{ !sent && limit > 0 }}",
					),
				],
				gap="6px",
				visible="{{ !sent }}",
			),
		],
		gap="6px",
	)
	locked = alert(
		"Your application {{ %s.data.application.name }} is sent, so these units are fixed." % SOURCE,
		visible="{{ sent }}",
	)

	not_approved = alert(
		"{{ 'Not on our approved list, so not shown: ' + notApproved.map((row) => row.scheme).join(', ') }}",
		theme="amber",
		visible="{{ notApproved.length }}",
	)

	return panel(
		"vault",
		"Choose funds to pledge",
		"Pick the funds and the amount you need. The units stay yours and keep earning returns; we only mark a lien on them.",
		[
			totals,
			not_approved,
			funds,
			row(
				[button("Fetch my funds again", script="refetch()", variant="ghost", props={"size": "sm"})],
				visible="{{ !sent }}",
			),
			form_grid([amount, tenure], visible="{{ !sent }}"),
			locked,
			security_list(read("application.pledges"), visible="{{ sent }}"),
			summary_strip(
				[
					("Pledged value", read("application.value"), None),
					("Loan amount", read("application.loan_amount"), None),
					("Repay over", read("application.tenure_label"), "%s.data?.application?.tenure_label" % SOURCE),
				],
				visible="{{ sent }}",
			),
			actions(action("Continue", "startApplication()", enabled="canApply", visible="{{ !sent }}")),
		],
	)


def kyc_panel():
	verified = "%s.data?.kyc?.verified" % SOURCE
	pending = "%s.data?.kyc?.status === 'Pending'" % SOURCE

	return panel(
		"kyc",
		"Complete your KYC",
		"Share your Aadhaar and PAN from DigiLocker. It takes about a minute, and you need not upload any documents.",
		[
			done_line("KYC is complete, as {{ %s.data.kyc.name }}." % SOURCE, "{{ %s }}" % verified),
			row(
				[
					icon_tile("shield", tile=40, glyph=20),
					column(
						[
							text("DigiLocker", size="text-base", styles={"fontWeight": "600"}),
							muted("You will sign in to DigiLocker and allow us to read the two documents."),
						],
						gap="2px",
					),
				],
				gap="12px",
				visible="{{ !%s }}" % verified,
			),
			actions(
				button("I have finished", script="completeKyc()", props={"size": "md"}, visible="{{ %s }}" % pending),
				action("Verify with DigiLocker", "startKyc()", visible="{{ !%s }}" % verified),
			),
		],
	)


LIST_BOX = {
	"borderWidth": "1px",
	"borderStyle": "solid",
	"borderColor": "var(--outline-gray-2)",
	"borderRadius": "var(--radius-4)",
	"overflow": "hidden",
	"flexShrink": "0",
}


def security_list(items, with_lien=False, visible=None):
	detail = (
		badge("{{ 'Lien ' + dataItem.lien }}", theme="green", visible="{{ dataItem.lien }}")
		if with_lien
		else muted("{{ 'lends ' + dataItem.eligible }}", styles={"textAlign": "right"})
	)
	line = row(
		[
			icon_tile("chart-no-axes", tile=36, glyph=18),
			column(
				[
					text("{{ dataItem.scheme }}", size="text-base", styles={"fontWeight": "500", "color": "var(--ink-gray-9)"}),
					muted("{{ (dataItem.folio ? 'Folio ' + dataItem.folio + ' · ' : '') + dataItem.units + ' units' }}"),
				],
				gap="2px",
				styles={"flex": "1 1 auto", "minWidth": "0px"},
			),
			column(
				[text("{{ dataItem.value }}", size="text-base", styles={"fontWeight": "600", "textAlign": "right"}), detail],
				gap="4px",
				styles={"alignItems": "flex-end", "flexShrink": "0"},
			),
		],
		gap="12px",
		styles={
			"width": "100%",
			"padding": "14px 16px",
			"borderBottom": "1px solid var(--outline-gray-1)",
			"backgroundColor": "var(--surface-base)",
		},
		mobile={"flexWrap": "wrap"},
	)

	return repeater(
		fallback(items, "[]"),
		line,
		data_key="key",
		styles=dict(LIST_BOX, display="flex", flexDirection="column", width="100%", marginBottom="-1px"),
		visible=visible,
	)


def summary_strip(cells, visible=None):
	return container(
		[
			column(
				[muted(label), text(value, size="text-lg", styles={"fontWeight": "600", "color": "var(--ink-gray-9)"})],
				gap="2px",
				styles={"flex": "1 1 140px", "minWidth": "0px"},
				**({"visible": "{{ %s }}" % shown} if shown else {}),
			)
			for label, value, shown in cells
		],
		styles={
			"display": "flex",
			"flexWrap": "wrap",
			"gap": "16px",
			"padding": "14px 16px",
			"borderRadius": "var(--radius-4)",
			"backgroundColor": "var(--surface-gray-1)",
			"flexShrink": "0",
		},
		visible=visible,
	)


def pledge_panel():
	marked = "%s.data?.pledge?.marked" % SOURCE

	return panel(
		"pledge",
		"Pledge your mutual funds",
		"Review the funds and the loan. The registrar marks a lien on these units in our favour once you approve it with an OTP.",
		[
			done_line("The lien is marked on your units.", "{{ %s }}" % marked),
			security_list(read("pledge.lines"), with_lien=True, visible="{{ %s }}" % marked),
			security_list(read("application.pledges"), visible="{{ !%s }}" % marked),
			summary_strip(
				[
					("Pledged value", read("application.value"), None),
					("Loan amount", read("application.loan_amount"), None),
					("Repay over", read("application.tenure_label"), "%s.data?.application?.tenure_label" % SOURCE),
					("Monthly instalment", read("application.emi"), "%s.data?.application?.emi" % SOURCE),
				]
			),
			form_grid(
				[field("OTP", "pledgeOtp", kind="password", placeholder="6 digits")],
				visible="{{ pledgeSent && !%s }}" % marked,
			),
			actions(
				action("Send OTP", "sendPledgeOtp()", visible="{{ !pledgeSent && !%s }}" % marked),
				button("Resend OTP", script="sendPledgeOtp()", props={"size": "md"}, visible="{{ pledgeSent && !%s }}" % marked),
				action("Pledge units", "confirmPledge()", enabled="pledgeOtp.length >= 4", visible="{{ pledgeSent && !%s }}" % marked),
			),
		],
	)


def bank_panel():
	saved = "%s.data?.bank?.account" % SOURCE
	mismatch = "confirmAccount && confirmAccount !== accountNumber"
	holder = block(
		"FormControl",
		props={
			"type": "text",
			"label": "Account holder",
			"size": "md",
			"disabled": True,
			"modelValue": fallback(read("customer_name"), "''"),
		},
	)
	form = column(
		[
			form_grid(
				[
					holder,
					field("IFSC", "ifsc", kind="text", placeholder="HDFC0001234"),
					field("Account number", "accountNumber", kind="password", placeholder="Savings or current account"),
					field("Re-enter account number", "confirmAccount", kind="text", placeholder="Type it again"),
				]
			),
			text(
				"The account numbers do not match.",
				size="text-sm",
				styles={"color": "var(--ink-red-4, var(--ink-gray-7))"},
				visible="{{ %s }}" % mismatch,
			),
			row(
				[
					icon("info", size=16, styles={"color": "var(--ink-gray-5)"}),
					muted("We send ₹1 to this account to confirm it is yours. Your loan amount is paid into it."),
				],
				gap="8px",
				styles={"padding": "10px 12px", "borderRadius": "var(--radius-4)", "backgroundColor": "var(--surface-gray-1)"},
			),
			actions(
				action(
					"Verify bank account",
					"saveBank()",
					enabled="accountNumber.length >= 9 && accountNumber === confirmAccount && ifsc.length === 11",
				)
			),
		],
		gap="14px",
		visible="{{ !%s }}" % saved,
	)
	verified = row(
		[
			icon_tile("building-2", tile=40, glyph=20),
			column(
				[
					text(read("bank.bank"), size="text-base", styles={"fontWeight": "600", "color": "var(--ink-gray-9)"}),
					muted("{{ 'Account ' + %s.data.bank.account + ' · IFSC ' + %s.data.bank.ifsc }}" % (SOURCE, SOURCE)),
				],
				gap="2px",
				styles={"flex": "1 1 auto"},
			),
			badge("Verified", theme="green"),
		],
		gap="12px",
		styles=dict(LIST_BOX, padding="14px 16px"),
		visible="{{ %s }}" % saved,
	)

	return panel(
		"bank",
		"Add your bank details",
		"Add the account the loan should be paid into. It must be in your own name.",
		[
			verified,
			form,
		],
	)


def esign_panel():
	signed = "%s.data?.esign?.signed_on" % SOURCE
	letter = "%s.data?.esign?.letter" % SOURCE

	return panel(
		"esign",
		"E-sign your sanction letter",
		"It sets out the loan's terms and the units pledged. Sign it with an OTP sent to your Aadhaar-linked mobile.",
		[
			done_line("You signed the sanction letter on {{ %s.data.esign.signed_on }}." % SOURCE, "{{ %s }}" % signed),
			row(
				[
					icon_tile("file-text", tile=40, glyph=20),
					column(
						[text("Sanction letter", size="text-base", styles={"fontWeight": "600"}), muted(read("application.name"))],
						gap="2px",
					),
					spacer(),
					button("Read the letter", script="window.open(%s, '_blank')" % letter, props={"size": "md"}),
				],
				gap="12px",
				visible="{{ %s }}" % letter,
			),
			form_grid(
				[field("Aadhaar OTP", "esignOtp", kind="password", placeholder="6 digits")],
				visible="{{ esignSent && !%s }}" % signed,
			),
			actions(
				action("Get the letter and OTP", "sendEsignOtp()", visible="{{ !esignSent && !%s }}" % signed),
				action("Sign", "confirmEsign()", enabled="esignOtp.length >= 4", visible="{{ esignSent && !%s }}" % signed),
			),
		],
	)


def withdraw_box():
	amount = block(
		"FormControl",
		props={
			"type": "number",
			"label": "Amount",
			"size": "md",
			"variant": "subtle",
			"modelValue": {"$type": "variable", "name": "withdrawAmount"},
		},
		styles={"width": "220px"},
	)
	destination = row(
		[
			icon_tile("building-2", tile=36, glyph=18),
			column(
				[
					text(read("bank.bank"), size="text-base", styles={"fontWeight": "500", "color": "var(--ink-gray-9)"}),
					muted("{{ 'Account ' + %s.data.bank.account }}" % SOURCE),
				],
				gap="2px",
			),
		],
		gap="10px",
	)

	return column(
		[
			column(
				[
					heading("Get your money", tag="h3", size="text-base"),
					muted("{{ 'You can withdraw up to ' + %s.data.loan.available_label + ' now.' }}" % SOURCE),
				],
				gap="2px",
			),
			row([amount, destination], gap="24px", align="end", styles={"flexWrap": "wrap"}),
			actions(
				action(
					"Withdraw to my bank",
					"withdraw()",
					enabled="Number(withdrawAmount) > 0 && Number(withdrawAmount) <= %s.data.loan.available" % SOURCE,
				)
			),
		],
		gap="14px",
		styles=dict(LIST_BOX, padding="16px", overflow="visible"),
		visible="{{ %s.data?.loan?.available > 0 }}" % SOURCE,
	)


def loan_panel():
	opened = "%s.data?.loan?.name" % SOURCE
	waiting = "!%s && %s.data?.esign?.signed_on" % (opened, SOURCE)
	paid = "%s.data?.loan?.has_disbursed" % SOURCE

	# No panel title: each state has its own heading.
	return panel(
		"loan",
		"",
		"",
		[
			column(
				[
					# Sanctioned is not open: nothing is paid until the first withdrawal.
					heading("Your loan is sanctioned", visible="{{ !%s }}" % paid),
					done_line(
						"Loan {{ %s.data.loan.name }} is sanctioned. Withdraw what you need into your bank account." % SOURCE,
						"{{ !%s }}" % paid,
					),
					heading("Your loan is open", visible="{{ %s }}" % paid),
					done_line("Loan {{ %s.data.loan.name }} is open." % SOURCE, "{{ %s }}" % paid),
					summary_strip(
						[
							("Sanctioned", read("loan.amount"), None),
							("Paid to you", read("loan.disbursed"), None),
							("Rate of interest", read("loan.rate"), None),
							("Status", read("loan.status"), None),
						]
					),
					withdraw_box(),
					alert(read("loan.pending_note"), theme="blue", visible=read("loan.pending_note")),
					actions(
						button(
							"Go to my loan",
							script="open(%s.data.loan.url)" % SOURCE,
							variant="subtle",
							props={"size": "md"},
						)
					),
				],
				gap="14px",
				visible="{{ %s }}" % opened,
			),
			column(
				[
					column(
						[
							heading("Your application is with our team"),
							muted("Everything is signed. We will approve the loan and let you know, usually within a working day."),
						],
						gap="2px",
					),
					actions(button("Track my application", script="open(%s.data.application.url)" % SOURCE, props={"size": "md"})),
				],
				gap="14px",
				visible="{{ %s }}" % waiting,
			),
		],
	)


# The sample KYC provider's page


CONSENT_SOURCE = "kycConsent"
read_consent = reader(CONSENT_SOURCE)

CONSENT_SCRIPT = '''\tconst busy = ref(false)
\tconst allow = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.secured.give_kyc_consent")
\t\t\t.then((result: any) => {
\t\t\t\tif (result?.ok === false) { toast.error(result.message); return }
\t\t\t\trouter.push(result.redirect)
\t\t\t})
\t\t\t.catch((error: any) => toast.error(String(error?.messages?.[0] || error)))
\t\t\t.finally(() => { busy.value = false })
\t}
\tconst decline = () => router.push("/secured-loan")'''


def build_consent():
	documents = repeater(
		fallback(read_consent("documents"), "[]"),
		row([icon("check", size=14), text("{{ dataItem }}", size="text-base")], gap="8px"),
		data_key="",
		styles={"display": "flex", "flexDirection": "column", "gap": "8px"},
	)
	body = column(
		[
			alert("Demo only: this page stands in for DigiLocker, so no real documents are read.", theme="amber"),
			heading("Share your documents", size="text-2xl"),
			muted("{{ %s.data.customer_name }}, the lender is asking to read these documents from your account:" % CONSENT_SOURCE),
			documents,
			row(
				[
					spacer(),
					button("Deny", script="decline()", props={"size": "md"}),
					button("Allow", script="allow()", variant="solid", props={"size": "md", "loading": "{{ busy }}"}),
				],
				gap="8px",
			),
		],
		gap="16px",
		styles=dict(PANEL, padding="24px"),
	)

	return upsert_page(
		"Share your documents",
		CONSENT_ROUTE,
		public_page(read_consent, [], [body], width="560px"),
		[api_resource(CONSENT_SOURCE, "lending.portal.secured.get_kyc_consent")],
		script=page_script(body=CONSENT_SCRIPT, returns=["busy", "allow", "decline"], framed=False),
	)


# Sign-up for a visitor


REGISTER_SOURCE = "register"
read_register = reader(REGISTER_SOURCE)

REGISTER_SCRIPT = '''\tconst busy = ref(false)
\tconst token = ref("")
\tconst codeSent = ref(false)
\tconst fail = (error: any) => toast.error(String(error?.messages?.[0] || error?.message || error))
\tconst sendCode = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.send_mobile_code", { mobile_number: mobileNumber.value })
\t\t\t.then((result: any) => { codeSent.value = true; toast.success(result.message) })
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}
\tconst confirmCode = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.confirm_mobile_code", { mobile_number: mobileNumber.value, otp: otp.value })
\t\t\t.then((result: any) => {
\t\t\t\tif (!result.verified) { toast.error(result.message); return }
\t\t\t\ttoken.value = result.token
\t\t\t})
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}
\t// Not `register`: a setup() binding shadows the data source of the same name.
\tconst openAccount = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.secured.register", { token: token.value, full_name: fullName.value, email: email.value })
\t\t\t.then((result: any) => { window.location.href = router.resolve(result.redirect).href })
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}'''


def build_register():
	mobile = column(
		[
			field("Mobile number", "mobileNumber", kind="tel", placeholder="98765 43210"),
			field("OTP", "otp", kind="password", placeholder="6 digits", visible="{{ codeSent }}"),
		],
		gap="12px",
		visible="{{ !token }}",
	)
	details = column(
		[
			alert("Mobile number verified.", theme="green"),
			field("Full name, as on your PAN", "fullName", placeholder="Ananya Rao"),
			field("Email", "email", kind="email", placeholder="you@example.com"),
		],
		gap="12px",
		visible="{{ token }}",
	)
	body = column(
		[
			heading("Open your account", size="text-2xl"),
			muted("Borrow against your mutual funds, entirely online. Start with your mobile number."),
			mobile,
			details,
			row(
				[
					spacer(),
					action("Send OTP", "sendCode()", visible="{{ !codeSent && !token }}"),
					action("Verify", "confirmCode()", visible="{{ codeSent && !token }}"),
					action("Open my account", "openAccount()", enabled="fullName && email", visible="{{ token }}"),
				],
				gap="8px",
			),
		],
		gap="16px",
		styles=dict(PANEL, padding="24px"),
	)

	return upsert_page(
		"Open your account",
		REGISTER_ROUTE,
		public_page(read_register, [("Log in", "/login", "user")], [body], width="560px"),
		[api_resource(REGISTER_SOURCE, "lending.portal.apply.get_apply_page")],
		script=page_script(
			state=[("mobileNumber", '""'), ("otp", '""'), ("fullName", '""'), ("email", '""')],
			body=REGISTER_SCRIPT,
			returns=["busy", "token", "codeSent", "sendCode", "confirmCode", "openAccount"],
			framed=False,
		),
		allow_guest=True,
	)
