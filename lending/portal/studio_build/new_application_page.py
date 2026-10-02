# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.apply_page import choice
from lending.portal.studio_build.blocks import (
	alert,
	block,
	button,
	card,
	column,
	container,
	fallback,
	heading,
	input_props,
	muted,
	pair_rows,
	reader,
	repeater,
	row,
	spacer,
	text,
)
from lending.portal.studio_build.profile_page import section
from lending.portal.studio_build.shell import frame

SOURCE = "newApplication"
read = reader(SOURCE)

ROUTE = "/new-application"

# (label, ref, input type, applicant type asked or "" for both, required)
NEEDS = (
	("Amount needed", "loanAmount", "number", "", True),
	("Over how many months", "proposedTenure", "number", "", False),
)
# PAN first, so it fills the row of locked details and Work starts the next one.
ABOUT = (
	("PAN", "pan", "text", "", False),
	("Monthly income", "income", "number", "", False),
	("Date of birth", "dateOfBirth", "date", "Individual", False),
)

COLUMNS = 4

# ref -> Loan Lead field
SUBMIT = {
	"loanProduct": "loan_product",
	"loanAmount": "loan_amount",
	"proposedTenure": "proposed_tenure",
	"income": "income",
	"employmentType": "employment_type",
	"dateOfBirth": "date_of_birth",
	"pan": "pan",
}

# ref -> `last_answers` key
PREFILL = {
	"income": "income",
	"employmentType": "employment_type",
	"dateOfBirth": "date_of_birth",
	"pan": "pan",
	"proposedTenure": "proposed_tenure",
}

FORM = '''\tconst page = computed(() => context.%(source)s.data || {})
\tconst applicants = computed<any[]>(() => page.value.applicants || [])
\tconst chosen = computed<any>(() => applicants.value.find((row) => row.value === applicant.value) || {})
\tconst products = computed<any[]>(() => page.value.products?.[chosen.value.applicant_type] || [])
\tconst isPerson = computed(() => chosen.value.applicant_type === "Individual")
\tconst busy = ref(false)
\tconst offer = ref<Record<string, any>>({})
\t// A ref rather than chosen.identity, so the locked boxes bind to something they own.
\tconst identity = ref<Record<string, string>>({})

\twatch(applicants, (all) => {
\t\tif (!all.some((row) => row.value === applicant.value)) applicant.value = all[0]?.value || ""
\t}, { immediate: true })

\twatch(chosen, (row) => {
\t\tconst answers = row.answers || {}
\t\tidentity.value = { ...(row.identity || {}) }
%(prefill)s
\t\tif (!products.value.some((product) => product.value === loanProduct.value)) loanProduct.value = ""
\t}, { immediate: true })

\tconst chooseProduct = (product: string) => { loanProduct.value = product }
\tconst needsMobile = computed(() => Boolean(chosen.value.value && !chosen.value.has_mobile))
\tconst ready = computed(() => Boolean(loanProduct.value && Number(loanAmount.value) > 0 && chosen.value.has_mobile))

\tconst submit = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.create_customer_lead", {
\t\t\tcustomer: applicant.value,
%(fields)s
\t\t})
\t\t\t.then((result: any) => { offer.value = result })
\t\t\t.catch((error: any) => toast.error(String(error?.messages?.[0] || error?.message || error)))
\t\t\t.finally(() => { busy.value = false })
\t}

\tconst another = () => {
\t\toffer.value = {}
\t\tloanProduct.value = ""
\t\tloanAmount.value = ""
\t}''' % {
	"source": SOURCE,
	"prefill": "\n".join(
		f'\t\t{ref_name}.value = answers.{key} || ""' for ref_name, key in PREFILL.items()
	),
	"fields": "\n".join(f"\t\t\t{field}: {ref_name}.value," for ref_name, field in SUBMIT.items()),
}

STATE = [("applicant", '""'), *((ref_name, '""') for ref_name in SUBMIT)]
RETURNS = [
	"applicants",
	"chosen",
	"identity",
	"products",
	"isPerson",
	"busy",
	"offer",
	"chooseProduct",
	"needsMobile",
	"ready",
	"submit",
	"another",
]

# `typeof`, because page-script refs are undefined on the canvas and a bare read throws.
SENT = "typeof offer !== 'undefined' && offer.reference"
# Shown on the canvas too, where `isPerson` is undefined.
PERSON_ONLY = "{{ typeof isPerson === 'undefined' || isPerson }}"


def build():
	body = column(
		[
			applicant_section(),
			needs_section(),
			about_section(),
			actions(),
		],
		gap="0px",
	)
	form = card(
		"Apply for a new loan",
		"",
		body,
		styles={"padding": "16px 20px"},
		visible="{{ !(%s) }}" % SENT,
	)

	return upsert_page(
		"New application",
		ROUTE,
		frame(SOURCE, [form, result()]),
		[
			api_resource(SOURCE, "lending.portal.apply.get_new_application_page"),
			api_resource("alerts", "lending.portal.notifications.get_notifications", auto=0),
		],
		script=page_script(state=STATE, body=FORM, returns=RETURNS),
	)


def applicant_section():
	picker = block(
		"FormControl",
		props={
			"type": "select",
			"label": "Applying as",
			"size": "md",
			"variant": "subtle",
			"options": fallback(read("applicants"), "[]"),
			"modelValue": {"$type": "variable", "name": "applicant"},
		},
	)

	return container(
		[section("building-2", "Who is this for?", "Pick the record the loan is in the name of.", [picker])],
		visible="{{ (%s.data?.applicants || []).length > 1 }}" % SOURCE,
	)


def needs_section():
	product = choice(
		[
			column(
				[
					text("{{ dataItem.label }}", size="text-base", styles={"fontWeight": "600", "color": "var(--ink-gray-9)"}),
					muted("{{ dataItem.summary }}"),
					muted("{{ dataItem.ceiling }}"),
				],
				gap="2px",
			)
		],
		"chooseProduct(dataItem.value)",
		"loanProduct === dataItem.value",
	)
	products = repeater(
		"{{ typeof products !== 'undefined' ? products : [] }}",
		product,
		data_key="value",
		empty="Nothing is open to this kind of applicant yet",
		styles={
			"display": "grid",
			"gridTemplateColumns": "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
			"gap": "12px",
			"gridColumn": "1 / -1",
		},
	)

	return section("wallet", "What do you need?", "", [products, *boxes(NEEDS)], columns=COLUMNS)


def about_section():
	on_record = [
		locked_box("Name", "applicant_name"),
		locked_box("Company", "company_name", visible="{{ identity?.company_name }}"),
		locked_box("Email", "email"),
		locked_box("Mobile", "mobile_number"),
	]
	change = row(
		[button("Change these in Personal details", script="open('/profile')", variant="ghost")],
		styles={"gridColumn": "1 / -1", "marginLeft": "-8px"},
	)
	no_mobile = alert(
		read("no_mobile_note"),
		theme="orange",
		styles={"gridColumn": "1 / -1"},
		visible="{{ needsMobile }}",
	)
	work = block(
		"FormControl",
		props={
			"type": "select",
			"label": "Work",
			"size": "md",
			"variant": "subtle",
			"placeholder": "Choose one",
			"options": fallback(read("employment_types"), "[]"),
			"modelValue": {"$type": "variable", "name": "employmentType"},
		},
		visible=PERSON_ONLY,
	)

	return section(
		"file-user",
		"About you",
		"Name, email and mobile are from your records. The rest is optional, and sharpens the offer.",
		[*on_record, *boxes(ABOUT[:1]), work, *boxes(ABOUT[1:]), change, no_mobile],
		rule=False,
		columns=COLUMNS,
	)


def locked_box(label, key, visible=None):
	return block(
		"FormControl",
		props={
			"type": "text",
			"label": label,
			"size": "md",
			"disabled": True,
			"placeholder": "Not on record",
			"modelValue": {"$type": "variable", "name": f"identity.{key}"},
		},
		visible=visible,
	)


def boxes(rows):
	return [box(*row_) for row_ in rows]


def box(label, ref_name, kind, who, required):
	return block(
		"FormControl",
		props={
			**input_props(kind),
			"label": label,
			"size": "md",
			"variant": "subtle",
			"required": required,
			"modelValue": {"$type": "variable", "name": ref_name},
		},
		# Only a person is asked for a date of birth; Loan Lead zeroes a company's age.
		visible=PERSON_ONLY if who == "Individual" else None,
	)


def actions():
	send = button(
		"Send application",
		script="submit()",
		variant="solid",
		props={"size": "md", "loading": "{{ busy }}", "disabled": "{{ !ready }}"},
	)

	return row([spacer(), send], styles={"paddingTop": "12px"})


def result():
	return card(
		"",
		"",
		column(
			[
				heading("{{ offer.headline }}", tag="h3", size="text-xl"),
				muted("{{ offer.message }}"),
				# Hidden when empty, or it would say "Nothing to show" under a holding message.
				pair_rows("{{ offer.offer }}", data_key="label", visible="{{ offer.offer?.length }}"),
				alert("{{ offer.reference_note }}", visible="{{ offer.reference_note }}"),
				row(
					[
						spacer(),
						button("Apply for another", script="another()"),
						button("See my applications", script="open('/applications')", variant="solid"),
					],
					gap="8px",
				),
			],
			gap="12px",
		),
		styles={"padding": "16px 20px"},
		visible="{{ %s }}" % SENT,
	)
