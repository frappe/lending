# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	PANEL,
	alert,
	block,
	button,
	click,
	column,
	container,
	divider,
	icon,
	icon_tile,
	muted,
	pair_rows,
	reader,
	repeater,
	row,
	slot,
	spacer,
	text,
	tile_styles,
)
from lending.portal.studio_build.public import page

APPLY_SOURCE = "apply"

# panel 1, the landing screen, is not counted by the progress bar
STEPS = (
	"Who is borrowing",
	"What you need",
	"Your mobile number",
	"Your details",
	"Your offer",
	"Your account",
)

APPLICANT_TYPES = (
	("Individual", "Person", "I am borrowing in my own name", "user"),
	("Business", "Company", "The business borrows, not me", "building-2"),
)

# must match Loan Lead.employment_type's options
EMPLOYMENT_TYPES = ("Salaried", "Self-employed")

# (label, ref, Loan Lead field, type, applicant type or "" for both, required)
DETAIL_FIELDS = (
	("Company name", "companyName", "company_name", "text", "Business", True),
	("Your full name", "applicantName", "applicant_name", "text", "", True),
	("Date of birth", "dateOfBirth", "date_of_birth", "date", "Individual", False),
	("PAN", "pan", "pan", "text", "", False),
	("Country", "applicantCountry", "applicant_country", "text", "", False),
	("Email", "email", "email", "email", "", True),
	("Amount needed", "loanAmount", "loan_amount", "number", "", True),
	("Over how many months", "proposedTenure", "proposed_tenure", "number", "", False),
	("Monthly income", "income", "income", "number", "", False),
)


read_apply = reader(APPLY_SOURCE)

PAGE_WIDTH = "1128px"

MOCKUP_HEIGHT = 719
BAR_HEIGHT = 54
TILE = 50
GLYPH = 26

# Fixed mockup colours, cooler than frappe-ui's greys; safe since the portal has no dark theme.
INK = "#0a0a0a"
INTRO = "#4f5d6e"
NOTE = "#5a616d"
TAG = "#51575d"
RULE = "#e7eaec"
DIVIDER = "#e2e3e6"
FORM = {"width": "100%", "maxWidth": "720px", "margin": "0 auto"}

APPLY_SCRIPT = '''\tconst busy = ref(false)
\tconst codeSent = ref(false)
\tconst token = ref("")
\tconst accountToken = ref("")
\tconst offer = ref<Record<string, any>>({})

\tconst fail = (error: any) =>
\t\ttoast.error(String(error?.messages?.[0] || error?.message || error))

\t// Once the number is confirmed, step over the mobile screen in either direction.
\tconst go = (to: number) => {
\t\tif (to === 4 && token.value) to = step.value > 4 ? 3 : 5
\t\tstep.value = to
\t}

\tconst choose = (type: string) => {
\t\tif (type !== applicantType.value) loanProduct.value = ""
\t\tapplicantType.value = type
\t}

\tconst chooseProduct = (product: string) => { loanProduct.value = product }

\tconst resendIn = ref(0)
\tconst countDown = () => {
\t\tresendIn.value = 30
\t\tconst timer = setInterval(() => {
\t\t\tif (--resendIn.value <= 0) clearInterval(timer)
\t\t}, 1000)
\t}

\tconst sendCode = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.send_mobile_code", { mobile_number: mobileNumber.value })
\t\t\t.then((result: any) => {
\t\t\t\tcodeSent.value = true
\t\t\t\tcountDown()
\t\t\t\ttoast.success(result.message)
\t\t\t})
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}

\tconst resendCode = () => {
\t\tif (resendIn.value > 0 || busy.value) return
\t\tsendCode()
\t}

\tconst confirmCode = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.confirm_mobile_code", {
\t\t\tmobile_number: mobileNumber.value,
\t\t\totp: otp.value,
\t\t})
\t\t\t.then((result: any) => {
\t\t\t\tif (!result.verified) { toast.error(result.message); return }
\t\t\t\ttoken.value = result.token
\t\t\t\tstep.value = 5
\t\t\t})
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}

\tconst submit = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.submit_lead", {
\t\t\ttoken: token.value,
\t\t\tapplicant_type: applicantType.value,
\t\t\tloan_product: loanProduct.value,
%(fields)s
\t\t\temployment_type: employmentType.value,
\t\t})
\t\t\t.then((result: any) => {
\t\t\t\toffer.value = result
\t\t\t\taccountToken.value = result.account_token
\t\t\t\tstep.value = 6
\t\t\t})
\t\t\t.catch((error: any) => {
\t\t\t\tfail(error)
\t\t\t\tif (error?.exc_type !== "VerificationExpiredError") return
\t\t\t\ttoken.value = ""
\t\t\t\tcodeSent.value = false
\t\t\t\totp.value = ""
\t\t\t\tstep.value = 4
\t\t\t})
\t\t\t.finally(() => { busy.value = false })
\t}

\tconst createAccount = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.create_account", {
\t\t\ttoken: accountToken.value,
\t\t\tpassword: password.value,
\t\t\tconfirm_password: confirmPassword.value,
\t\t})
\t\t\t.then(() => { window.location.href = "/borrower-portal/overview" })
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}''' % {
	"fields": "\n".join(
		f"\t\t\t{field}: {ref_name}.value," for _label, ref_name, field, *_rest in DETAIL_FIELDS
	)
}

APPLY_STATE = [
	("step", "1"),
	("applicantType", '"Individual"'),
	("loanProduct", '""'),
	("mobileNumber", '""'),
	("otp", '""'),
	("employmentType", '"Salaried"'),
	("password", '""'),
	("confirmPassword", '""'),
] + [(ref_name, '""') for _label, ref_name, *_rest in DETAIL_FIELDS]

APPLY_RETURNS = [
	"busy",
	"codeSent",
	"offer",
	"go",
	"choose",
	"chooseProduct",
	"sendCode",
	"resendIn",
	"resendCode",
	"confirmCode",
	"submit",
	"createAccount",
]


def action(label, script, **kwargs):
	return button(label, script=script, variant="solid", props={"loading": "{{ busy }}"}, **kwargs)


def panel(index, title, note, body, back=None, forward=()):
	head = column([text(title, tag="h2", size="text-2xl", styles={"fontWeight": "600"}), muted(note)], gap="4px")
	buttons = [*([button("Back", script=f"go({back})")] if back else []), spacer(), *forward]
	nav = row([sized(part) for part in buttons], gap="8px")

	return column(
		[head, *body, nav],
		gap="16px",
		styles=dict(PANEL, **FORM),
		visible="{{ step === %d }}" % index,
	)


def sized(part):
	if part["componentName"] != "Button":
		return part

	return dict(part, componentProps=dict(part["componentProps"], size="md"))


def progress():
	where = "{{ 'Step ' + (step - 1) + ' of %d · ' + (%s[step - 2] || '') }}" % (len(STEPS), list(STEPS))

	return column(
		[
			block("Progress", props={"value": "{{ (step - 1) / %d * 100 }}" % len(STEPS), "size": "sm"}),
			text(where, size="text-sm", styles={"color": "var(--ink-gray-7)"}),
		],
		gap="6px",
		styles=FORM,
		visible="{{ step > 1 }}",
	)


RADIO = {
	"width": "20px",
	"height": "20px",
	"flexShrink": "0",
	"borderRadius": "9999px",
	"justifyContent": "center",
}


def radio(chosen):
	return [
		container(
			[],
			styles=dict(RADIO, border="1.5px solid var(--outline-gray-3)"),
			visible="{{ !(%s) }}" % chosen,
		),
		row(
			[icon("check", size=12, stroke=3)],
			styles=dict(RADIO, backgroundColor="var(--ink-gray-9)", color="var(--surface-base)"),
			visible="{{ %s }}" % chosen,
		),
	]


def choice(content, script, chosen, **kwargs):
	# Block styles can't follow state, so "selected" is an overlay; `!` beats PANEL's inline border.
	selected = container(
		[],
		styles={
			"position": "absolute",
			"inset": "-1px",
			"borderRadius": "calc(var(--radius-4) + 1px)",
			"border": "2px solid var(--ink-gray-9)",
			"backgroundColor": "var(--surface-gray-1)",
			"pointerEvents": "none",
		},
		visible="{{ %s }}" % chosen,
	)
	body = row(
		[*content, spacer(), *radio(chosen)],
		gap="12px",
		align="start",
		styles={"position": "relative", "width": "100%"},
	)

	return container(
		[selected, body],
		styles=dict(PANEL, position="relative", cursor="pointer", userSelect="none", flex="1"),
		events=click(script),
		classes=[
			"transition",
			"duration-150",
			"hover:!border-outline-gray-4",
			"hover:shadow-sm",
			"active:scale-[0.98]",
		],
		**kwargs,
	)


def tile(label, note, glyph_name, script, chosen):
	return choice(
		[
			icon_tile(glyph_name, tile=40, glyph=20),
			column(
				[text(label, size="text-base", styles={"fontWeight": "600"}), muted(note)],
				gap="2px",
			),
		],
		script,
		chosen,
	)


def glyph(names, expression):
	# icons are baked at build time, so emit one per name and show the one the row picks
	return [glyph_tile(name, visible="{{ %s === '%s' }}" % (expression, name)) for name in names]


def glyph_tile(name, **kwargs):
	# sized by padding because an SVG's width attribute can't hold calc()
	styles = dict(tile_styles(), width=u(TILE), height=u(TILE), padding=u((TILE - GLYPH) / 2))

	return icon(name, size="100%", styles=styles, **kwargs)


# One mockup pixel, shrinking down to 0.6px so the opening screen fits the viewport height.
UNIT = f"max(0.6px, min(1px, calc((100vh - {BAR_HEIGHT}px) / {MOCKUP_HEIGHT - BAR_HEIGHT})))"


def u(length):
	return f"calc({length:g} * var(--u, 1px))"


def copy(value, size, weight="400", color=INK, line=None, tag="p", **kwargs):
	# every property set explicitly, overriding the tracking and weight Studio's size class carries
	styles = {
		"fontSize": u(size),
		"lineHeight": u(line or round(size * 1.4)),
		"fontWeight": weight,
		"letterSpacing": "0em",
		"color": color,
	}
	styles.update(kwargs.pop("styles", None) or {})

	return text(value, tag=tag, size="text-base", styles=styles, **kwargs)


OPENING_CARD = dict(PANEL, borderColor=RULE, borderRadius="10px")


def hero():
	tagline = copy(
		read_apply("tagline"),
		14,
		color=TAG,
		line=26,
		tag="span",
		styles={
			"padding": f"0 {u(12)}",
			"marginBottom": u(3),
			"borderRadius": "9999px",
			"backgroundColor": "var(--surface-gray-2)",
		},
	)
	title = copy(
		read_apply("heading"),
		40,
		weight="700",
		line=45,
		tag="h1",
		styles={"whiteSpace": "pre-line"},
		mobile={"fontSize": "32px", "lineHeight": "38px"},
	)
	intro = copy(read_apply("intro"), 17, color=INTRO, line=22, styles={"maxWidth": u(560)})

	return column(
		[tagline, title, intro],
		gap=u(12),
		styles={"alignItems": "center", "textAlign": "center"},
	)


def card_text(title, note, size=15, line=20, gap="0px", tracking="-0.01em", note_tracking="0em"):
	return column(
		[
			copy(title, size, weight="600", line=line, styles={"letterSpacing": tracking}),
			copy(note, 14, color=NOTE, line=20, styles={"letterSpacing": note_tracking}),
		],
		gap=gap,
		styles={"flex": "1 1 160px", "minWidth": "0px"},
	)


def trust_points():
	point = row(
		[
			*glyph(("chart-no-axes", "shield", "receipt-text"), "dataItem.icon"),
			card_text("{{ dataItem.title }}", "{{ dataItem.note }}"),
		],
		gap=u(24),
		# wraps by width, since the tablet breakpoint fires only below 768px
		styles=dict(OPENING_CARD, padding=f"{u(18)} {u(20)}", flex="1 1 240px"),
	)

	return repeater(
		read_apply("trust_points"),
		point,
		data_key="title",
		styles={"display": "flex", "flexDirection": "row", "gap": u(16), "flexWrap": "wrap"},
	)


def start_card():
	# label repeated in the default slot: any slot gives Button an empty default that hides `label`
	apply = button(
		"Apply now",
		script="go(2)",
		variant="solid",
		props={"size": "lg"},
		slots={
			**slot("suffix", [icon("arrow-right", size=16)]),
			**slot("default", [copy("Apply now", 15, weight="500", line=20, tag="span", color="inherit")]),
		},
		styles={"height": u(45), "padding": f"0 {u(15)}", "borderRadius": u(8)},
		mobile={"width": "100%"},
	)

	return row(
		[
			glyph_tile("file-text"),
			column(
				[
					copy(read_apply("start_title"), 20, weight="600", line=26, styles={"letterSpacing": "-0.015em"}),
					copy(
						read_apply("start_note"), 14, color=NOTE, line=20, styles={"letterSpacing": "0.015em"}
					),
				],
				gap="0px",
				styles={"flex": "1 1 240px"},
			),
			apply,
		],
		gap=u(28),
		styles=dict(OPENING_CARD, padding=f"{u(21)} {u(22)}", flexWrap="wrap"),
		mobile={"padding": "16px", "gap": "16px"},
	)


def how_it_works():
	step = row(
		[
			*glyph(("file-text", "search", "percent"), "dataItem.icon"),
			card_text(
				"{{ dataItem.title }}", "{{ dataItem.note }}", size=14, line=18, gap=u(6), tracking="0em", note_tracking="0.02em"
			),
		],
		gap=u(24),
		align="start",
		styles=dict(OPENING_CARD, padding=f"{u(20)} {u(20)} {u(21)}", flex="1 1 0px", minWidth="0px"),
	)

	return column(
		[
			column(
				[
					copy(read_apply("how_title"), 22, weight="700", line=28, styles={"letterSpacing": "-0.025em"}),
					copy(read_apply("how_note"), 14, color=NOTE, line=20, styles={"letterSpacing": "0.02em"}),
				],
				gap=u(2),
			),
			repeater(
				read_apply("benefits"),
				step,
				data_key="icon",
				styles={"display": "flex", "flexDirection": "row", "gap": u(16)},
				tablet={"flexDirection": "column", "gap": "12px"},
			),
		],
		gap=u(8),
		styles={"marginTop": u(-2)},
	)


def opening():
	offer = column([hero(), trust_points(), start_card()], gap=u(16))

	return column(
		[offer, divider(styles={"borderColor": DIVIDER}), how_it_works()],
		gap=u(24),
		styles={"marginTop": "auto", "marginBottom": "auto", "--u": UNIT},
		mobile={"--u": "1px"},
		visible="{{ step === 1 }}",
	)


def type_panel():
	tiles = row(
		[
			tile(label, note, glyph_name, f"choose('{value}')", "applicantType === '%s'" % value)
			for value, label, note, glyph_name in APPLICANT_TYPES
		],
		gap="12px",
		align="stretch",
		mobile={"flexDirection": "column"},
	)

	return panel(
		2,
		"Are you applying as a person or a company?",
		read_apply("type_note"),
		[tiles],
		back=1,
		forward=[button("Continue", script="go(3)", variant="solid")],
	)


def product_panel():
	product = choice(
		[
			column(
				[
					text("{{ dataItem.label }}", size="text-base", styles={"fontWeight": "600"}),
					# one expression: Studio renders only the first binding in a string
					muted("{{ dataItem.rate + ' ' + dataItem.rate_note + ' · ' + dataItem.kind }}"),
					muted("Up to {{ dataItem.ceiling }}"),
				],
				gap="2px",
			)
		],
		"chooseProduct(dataItem.value)",
		"loanProduct === dataItem.value",
	)
	products = repeater(
		read_apply("products[applicantType]"),
		product,
		data_key="value",
		empty="Nothing is open to this kind of applicant yet",
		styles={
			"display": "grid",
			"gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
			"gap": "12px",
			"width": "100%",
		},
		mobile={"gridTemplateColumns": "minmax(0, 1fr)"},
	)

	return panel(
		3,
		"What are you looking for?",
		read_apply("product_note"),
		[products],
		back=2,
		forward=[
			button("Continue", script="go(4)", variant="solid", visible="{{ loanProduct }}"),
			muted("Pick a product to carry on", visible="{{ !loanProduct }}"),
		],
	)


def resend_line():
	link = text(
		"Resend OTP",
		styles={"color": "var(--ink-gray-9)", "fontWeight": "500", "cursor": "pointer"},
		events=click("resendCode()"),
	)

	return row(
		[
			row([muted("Didn't receive the OTP?"), link], gap="6px"),
			muted(
				"{{ 'Resend in 00:' + String(resendIn).padStart(2, '0') }}",
				styles={"color": "var(--ink-gray-5)"},
				visible="{{ resendIn > 0 }}",
			),
		],
		styles={"justifyContent": "space-between", "width": "100%"},
	)


def verify_panel():
	number = block(
		"FormControl",
		props={
			"type": "tel",
			"label": "Mobile number",
			"placeholder": "98765 43210",
			"modelValue": {"$type": "variable", "name": "mobileNumber"},
		},
	)
	code = column(
		[
			muted(read_apply("code_note")),
			block(
				"FormControl",
				props={
					"type": "password",
					"label": "OTP",
					"modelValue": {"$type": "variable", "name": "otp"},
				},
			),
			resend_line(),
		],
		gap="8px",
		visible="{{ codeSent }}",
	)

	return panel(
		4,
		"What is your mobile number?",
		read_apply("verify_note"),
		[number, code],
		back=3,
		forward=[
			action("Send OTP", "sendCode()", visible="{{ !codeSent }}"),
			action("Confirm my number", "confirmCode()", visible="{{ codeSent }}"),
		],
	)


def details_panel():
	boxes = [
		block(
			"FormControl",
			props={
				"type": kind,
				"label": label,
				"required": required,
				"modelValue": {"$type": "variable", "name": ref_name},
			},
			visible="{{ applicantType === '%s' }}" % who if who else None,
		)
		for label, ref_name, _field, kind, who, required in DETAIL_FIELDS
	]
	work = block(
		"FormControl",
		props={
			"type": "select",
			"label": "Work",
			"options": [{"label": kind, "value": kind} for kind in EMPLOYMENT_TYPES],
			"modelValue": {"$type": "variable", "name": "employmentType"},
		},
		visible="{{ applicantType === 'Individual' }}",
	)
	grid = container(
		[*boxes, work],
		styles={
			"display": "grid",
			"gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
			"gap": "12px",
			"width": "100%",
		},
		mobile={"gridTemplateColumns": "minmax(0, 1fr)"},
	)
	chosen = row(
		[
			block("Badge", props={"label": "{{ applicantType }}", "theme": "gray", "size": "sm"}),
			block("Badge", props={"label": "{{ loanProduct }}", "theme": "gray", "size": "sm"}),
		],
		gap="6px",
	)

	return panel(
		5,
		"Applicant information",
		read_apply("details_note"),
		[chosen, grid],
		back=4,
		forward=[action("See my offer", "submit()")],
	)


def offer_panel():
	return panel(
		6,
		"Your indicative offer",
		"What our rules say about the details you gave us.",
		[
			text("{{ offer.headline }}", tag="h3", size="text-xl", styles={"fontWeight": "600"}),
			muted("{{ offer.message }}"),
			# hidden when empty, or the list would show "Nothing to show"
			pair_rows("{{ offer.offer }}", data_key="label", visible="{{ offer.offer?.length }}"),
			alert("{{ offer.reference_note }}", visible="{{ offer.reference_note }}"),
		],
		forward=[button("Open my account", script="go(7)", variant="solid")],
	)


def account_panel():
	return panel(
		7,
		"Keep track of this",
		read_apply("account_note"),
		[
			block(
				"FormControl",
				props={
					"type": "password",
					"label": "Choose a password",
					"modelValue": {"$type": "variable", "name": "password"},
				},
			),
			block(
				"FormControl",
				props={
					"type": "password",
					"label": "Confirm password",
					"modelValue": {"$type": "variable", "name": "confirmPassword"},
				},
			),
		],
		forward=[action("Create my account", "createAccount()")],
	)


def build_apply():
	body = [
		progress(),
		opening(),
		type_panel(),
		product_panel(),
		verify_panel(),
		details_panel(),
		offer_panel(),
		account_panel(),
	]

	return upsert_page(
		"Apply for a loan",
		"/apply",
		page(
			read_apply,
			[("Track an application", "/track"), ("Log in", "/login", "user")],
			body,
			width=PAGE_WIDTH,
			padding=f"calc(34 * {UNIT}) 20px calc(16 * {UNIT})",
		),
		[api_resource(APPLY_SOURCE, "lending.portal.apply.get_apply_page")],
		script=page_script(state=APPLY_STATE, body=APPLY_SCRIPT, returns=APPLY_RETURNS, search=False),
		allow_guest=True,
	)


def build():
	return build_apply()
