# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	block,
	brand_style,
	button,
	click,
	column,
	container,
	heading,
	muted,
	reader,
	root,
	row,
	slot,
	text,
)
from lending.portal.studio_build.public import mark

LOGIN_SOURCE = "login"

read_login = reader(LOGIN_SOURCE)

LOGIN_SCRIPT = '''\tconst busy = ref(false)
\tconst codeSent = ref(false)
\tconst sentNote = ref("")
\tconst sentHint = ref("")
\tconst resendIn = ref(0)
\tlet timer: ReturnType<typeof setInterval> | undefined

\t// Same rule as login.portal_redirect: a link can't send a borrower off the portal.
\tconst redirectTo = () => {
\t\tconst to = new URLSearchParams(window.location.search).get("redirect-to") || ""
\t\treturn to.startsWith("/borrower-portal/") ? to : "/borrower-portal/overview"
\t}

\t// Studio's editor runs setup() on its canvas, where the editor is never a guest.
\tif (!window.is_guest && !window.location.pathname.startsWith("/studio")) {
\t\twindow.location.replace(redirectTo())
\t}

\tconst fail = (error: any) =>
\t\ttoast.error(String(error?.messages?.[0] || error?.message || error))

\tconst countDown = () => {
\t\tclearInterval(timer)
\t\tresendIn.value = 30
\t\ttimer = setInterval(() => {
\t\t\tif (--resendIn.value <= 0) clearInterval(timer)
\t\t}, 1000)
\t}

\tconst sendCode = () => {
\t\tif (busy.value) return
\t\tbusy.value = true
\t\tcall("lending.portal.login.send_login_code", { email: email.value })
\t\t\t.then((result: any) => {
\t\t\t\tif (!result.sent) {
\t\t\t\t\ttoast.error(result.message)
\t\t\t\t\topen(result.apply_url)
\t\t\t\t\treturn
\t\t\t\t}
\t\t\t\tcodeSent.value = true
\t\t\t\tsentNote.value = result.message
\t\t\t\tsentHint.value = result.hint
\t\t\t\totp.value = ""
\t\t\t\tcountDown()
\t\t\t})
\t\t\t.catch(fail)
\t\t\t.finally(() => { busy.value = false })
\t}

\tconst resendCode = () => {
\t\tif (resendIn.value > 0) return
\t\tsendCode()
\t}

\tconst verifyCode = () => {
\t\tif (busy.value) return
\t\tbusy.value = true
\t\tcall("lending.portal.login.verify_login_code", {
\t\t\temail: email.value,
\t\t\totp: otp.value,
\t\t\tredirect_to: redirectTo(),
\t\t})
\t\t\t.then((result: any) => {
\t\t\t\tif (!result.verified) {
\t\t\t\t\ttoast.error(result.message)
\t\t\t\t\tbusy.value = false
\t\t\t\t\treturn
\t\t\t\t}
\t\t\t\t// A full load: the app booted as a guest and holds no borrower pages yet.
\t\t\t\twindow.location.href = result.redirect_to
\t\t\t})
\t\t\t.catch((error: any) => {
\t\t\t\tfail(error)
\t\t\t\tbusy.value = false
\t\t\t})
\t}

\tconst changeEmail = () => {
\t\tclearInterval(timer)
\t\tcodeSent.value = false
\t\totp.value = ""
\t\tresendIn.value = 0
\t}

\tconst withGoogle = (url?: string) => {
\t\tif (url) window.location.href = url
\t}'''

CARD = {
	"width": "100%",
	"maxWidth": "460px",
	"padding": "48px 48px 40px",
	"backgroundColor": "var(--surface-base)",
	"border": "1px solid var(--outline-gray-1)",
	"borderRadius": "var(--radius-6, 12px)",
	"boxShadow": "0 1px 2px rgba(0, 0, 0, 0.04)",
}

MARK = {"width": "48px", "height": "48px", "flexShrink": "0", "borderRadius": "12px"}

FULL_BUTTON = {"width": "100%", "height": "34px", "borderRadius": "8px"}

LINK = {
	"color": "var(--ink-gray-9)",
	"fontWeight": "500",
	"textDecoration": "underline",
	"textUnderlineOffset": "3px",
	"cursor": "pointer",
}

QUIET_LINK = dict(LINK, color="var(--ink-gray-5)")

GOOGLE_LOGO = (
	'<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 48 48">'
	'<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0'
	' 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
	'<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26'
	' 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
	'<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19'
	'C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
	'<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16'
	' 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>'
)


def enter(script):
	return {"keydown.enter": {"event": "keydown.enter", "action": "Run Script", "script": script}}


def full_button(label, script, variant="solid", logo=None, **kwargs):
	# Label repeated in the default slot: with any slot, Studio's empty default one hides `label`.
	slots = slot("default", [text(label, tag="span", size="text-base")])
	if logo:
		slots.update(slot("prefix", [block("HTML", props={"html": logo}, styles={"display": "flex"})]))

	return button(
		label,
		script=script,
		variant=variant,
		props={"size": "md", "loading": "{{ busy }}"},
		slots=slots,
		styles=FULL_BUTTON,
		**kwargs,
	)


def field(label, ref_name, kind, placeholder, on_enter):
	return block(
		"FormControl",
		props={
			"type": kind,
			"label": label,
			"placeholder": placeholder,
			"required": True,
			"size": "md",
			"variant": "outline",
			"modelValue": {"$type": "variable", "name": ref_name},
		},
		events=enter(on_enter),
		styles={"width": "100%"},
	)


def intro():
	title = heading(
		read_login("heading"),
		tag="h1",
		size="text-xl",
		styles={"marginTop": "8px", "letterSpacing": "-0.01em"},
		visible="{{ !codeSent }}",
	)
	code_title = heading(
		read_login("code_heading"),
		tag="h1",
		size="text-xl",
		styles={"marginTop": "8px", "letterSpacing": "-0.01em"},
		visible="{{ codeSent }}",
	)
	note = muted(read_login("intro"), styles={"fontSize": "15px"}, visible="{{ !codeSent }}")
	sent = muted("{{ sentNote }}", styles={"fontSize": "15px"}, visible="{{ codeSent }}")

	return column(
		[
			row(mark(read_login, frame=MARK, letter_size="20px")),
			column([title, code_title, note, sent], gap="6px"),
		],
		gap="12px",
	)


def email_step():
	google = full_button(
		"Continue with Google",
		"withGoogle(%s)" % read_login("google_url")[2:-2].strip(),
		variant="outline",
		logo=GOOGLE_LOGO,
		visible=read_login("google_url"),
	)

	return column(
		[
			field("Email", "email", "email", "name@example.com", "sendCode()"),
			column(
				[full_button("Send verification code", "sendCode()"), google],
				gap="12px",
			),
		],
		gap="20px",
		visible="{{ !codeSent }}",
	)


def code_step():
	resend = row(
		[
			text("Resend code", tag="span", size="text-p-sm", styles=QUIET_LINK, events=click("resendCode()"), visible="{{ resendIn <= 0 }}"),
			muted(
				"{{ 'Resend in 00:' + String(resendIn).padStart(2, '0') }}",
				styles={"color": "var(--ink-gray-5)"},
				visible="{{ resendIn > 0 }}",
			),
		],
	)
	links = row(
		[
			text("Use a different email", tag="span", size="text-p-sm", styles=QUIET_LINK, events=click("changeEmail()")),
			resend,
		],
		styles={"justifyContent": "space-between", "width": "100%"},
	)

	return column(
		[
			column(
				[
					field("Login code", "otp", "text", "Enter the code", "verifyCode()"),
					muted("{{ sentHint }}", styles={"color": "var(--ink-gray-5)"}),
				],
				gap="8px",
			),
			full_button("Verify and log in", "verifyCode()"),
			links,
		],
		gap="20px",
		visible="{{ codeSent }}",
	)


def signup_line():
	return row(
		[
			muted("New borrower?", styles={"fontSize": "15px"}),
			text("Apply for a loan.", tag="span", size="text-base", styles=LINK, events=click("open('/apply')")),
		],
		gap="6px",
		styles={"justifyContent": "center", "marginTop": "8px"},
		visible="{{ %s && !codeSent }}" % read_login("show_signup")[2:-2].strip(),
	)


def login_card():
	return column(
		[intro(), email_step(), code_step(), signup_line()],
		gap="28px",
		styles=CARD,
		mobile={"padding": "32px 24px"},
	)


def build_login():
	body = container(
		[login_card()],
		styles={
			"display": "flex",
			"alignItems": "center",
			"justifyContent": "center",
			"width": "100%",
			"height": "100%",
			"padding": "40px 16px",
			"overflowY": "auto",
			"backgroundColor": "var(--surface-gray-1)",
		},
	)

	return upsert_page(
		"Log in",
		"/login",
		root([body, brand_style(read_login("brand_style"))], direction="column"),
		[
			api_resource(
				LOGIN_SOURCE,
				"lending.portal.login.get_login_page",
				params={"redirect_to": "{{ route.query['redirect-to'] || '' }}"},
			)
		],
		script=page_script(
			state=[("email", '""'), ("otp", '""')],
			body=LOGIN_SCRIPT,
			# Never return `login`: it would shadow the data source of that name.
			returns=[
				"busy",
				"codeSent",
				"sentNote",
				"sentHint",
				"resendIn",
				"sendCode",
				"resendCode",
				"verifyCode",
				"changeEmail",
				"withGoogle",
			],
			search=False,
		),
		allow_guest=True,
	)


def build():
	return build_login()
