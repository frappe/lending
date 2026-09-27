# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A logged-in borrower's application form, as a Studio page.

It reads `get_new_application_page` and posts to `create_customer_lead`, which makes the
same draft Loan Lead the public /apply page makes. The difference is only in what is
asked. /apply is a wizard because it has to find out who a stranger is and prove their
number first. Here we already know both, so the page is one form: what the borrower
needs, a few details that sharpen the offer, and the details we hold, shown and not asked.

One login can hold several customer records -- a person and their company -- so the form
asks which one the loan is for, and only when there is a choice to make. Each record in
the payload carries its own details and last answers, so switching refills the form
without asking the server again.

The offer replaces the form in the same card once it is sent.
"""

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

# Every box the borrower fills: (label, ref, input type, who is asked, required). An
# empty "who" means both. create_customer_lead reads Loan Lead's own names off the
# request, and SUBMIT below maps each ref to one.
NEEDS = (
	("Amount needed", "loanAmount", "number", "", True),
	("Over how many months", "proposedTenure", "number", "", False),
)
# PAN first, so it sits in the row of details we hold and Work starts the next one.
ABOUT = (
	("PAN", "pan", "text", "", False),
	("Monthly income", "income", "number", "", False),
	("Date of birth", "dateOfBirth", "date", "Individual", False),
)

# Boxes to a row in both sections, so their columns line up. Four keeps the whole form
# on one laptop screen: the details we hold and PAN take one row, the rest another.
COLUMNS = 4

# The ref each answer lives in, and the Loan Lead field it arrives as.
SUBMIT = {
	"loanProduct": "loan_product",
	"loanAmount": "loan_amount",
	"proposedTenure": "proposed_tenure",
	"income": "income",
	"employmentType": "employment_type",
	"dateOfBirth": "date_of_birth",
	"pan": "pan",
}

# What `last_answers` sends back, by the ref it fills.
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

\t// A person and their company are offered different products and told us different
\t// things last time, so switching refills the form from the record now chosen.
\twatch(chosen, (row) => {
\t\tconst answers = row.answers || {}
\t\tidentity.value = { ...(row.identity || {}) }
%(prefill)s
\t\tif (!products.value.some((product) => product.value === loanProduct.value)) loanProduct.value = ""
\t}, { immediate: true })

\tconst chooseProduct = (product: string) => { loanProduct.value = product }
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

\t// Back to an empty request, keeping who it is for and what they told us about themselves.
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
	"ready",
	"submit",
	"another",
]

# `offer` is a page-script ref, which the canvas has no context for. `typeof` answers
# there instead of throwing, so the canvas draws the form and not the result.
SENT = "typeof offer !== 'undefined' && offer.reference"


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
	"""Who the loan is for. Drawn only for a login with more than one customer record."""
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
	"""The product, as tiles with their rates on, and then how much and for how long."""
	product = choice(
		[
			column(
				[
					text("{{ dataItem.label }}", size="text-base", styles={"fontWeight": "600"}),
					# One expression: Studio renders only the first of several bindings in a string.
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
		"{{ typeof products !== 'undefined' ? products : [] }}",
		product,
		data_key="value",
		empty="Nothing is open to this kind of applicant yet",
		# auto-fit, so four products share one row on a laptop instead of leaving a
		# fifth empty track and wrapping sooner.
		styles={
			"display": "grid",
			"gridTemplateColumns": "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
			"gap": "12px",
			"gridColumn": "1 / -1",
		},
	)

	return section("wallet", "What do you need?", "", [products, *boxes(NEEDS)], columns=COLUMNS)


def about_section():
	"""What we hold, in locked boxes, and the few answers that sharpen the offer."""
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
		visible="{{ typeof chosen !== 'undefined' && chosen.value && !chosen.has_mobile }}",
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
		visible="{{ typeof isPerson === 'undefined' || isPerson }}",
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
	"""A detail we hold, drawn as a box so it lines up with the ones the borrower fills."""
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
			"type": kind,
			"label": label,
			"size": "md",
			"variant": "subtle",
			"required": required,
			"modelValue": {"$type": "variable", "name": ref_name},
		},
		# Only a person is asked for a date of birth; Loan Lead zeroes a company's age.
		visible="{{ typeof chosen === 'undefined' || chosen.applicant_type === '%s' }}" % who if who else None,
	)


def actions():
	"""The one way on. It waits for a product and an amount rather than refusing after."""
	send = button(
		"Send application",
		script="submit()",
		variant="solid",
		props={"size": "md", "loading": "{{ busy }}", "disabled": "{{ !ready }}"},
	)

	return row([spacer(), send], styles={"paddingTop": "12px"})


def result():
	"""What our rules made of it, in the card the form was in."""
	return card(
		"",
		"",
		column(
			[
				text("{{ offer.headline }}", tag="h3", size="text-xl", styles={"fontWeight": "600"}),
				muted("{{ offer.message }}"),
				# A holding message has no figures, and an empty list would say "Nothing to show".
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
