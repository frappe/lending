# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The borrower's Personal details page, as a Studio page.

It reads `get_profile_page` and posts back to `save_profile` -- the same two
endpoints, and the same fixed list of fields, because section 6.3 of PORTAL_PLAN.md is
what decides which of them a borrower may correct.

One card: the borrower's name under an avatar, then a section per kind of detail, each
led by a glyph on a tile. Name, record type and tax id are drawn greyed and disabled:
they are the outcome of a KYC check rather than a preference. The rest are ordinary
boxes, read-only until Edit is pressed, so a borrower who came to check what is on
record cannot change it by a stray keystroke.

One login can hold several customer records, so a picker beside Edit says which one is
open. The payload carries every record's values, so switching refills the boxes without
asking the server again.
"""

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	block,
	button,
	card,
	column,
	container,
	divider,
	fallback,
	heading,
	icon,
	icon_tile,
	muted,
	reader,
	row,
	slot,
	text,
)
from lending.portal.studio_build.shell import frame

SOURCE = "profile"
read = reader(SOURCE)

# Shown, never posted: these live in the page's `identity` ref, not in `form`.
IDENTITY = (
	("Full name", "customer_name"),
	("Registered as", "customer_type"),
	("Tax id", "tax_id"),
)

# The boxes a borrower may correct: (label, field, input type). `save_profile` reads
# exactly these names off the request and nothing else, so a box added here without a
# matching field there changes nothing.
CONTACT = (
	("Email", "email", "email"),
	("Mobile", "mobile", "tel"),
	("Phone", "phone", "tel"),
)
ADDRESS = (
	("Address line 1", "address_line1", "text"),
	("Address line 2", "address_line2", "text"),
	("City", "city", "text"),
	("State", "state", "text"),
	("Pin code", "pincode", "text"),
	("Country", "country", "text"),
)

FIELDS = [name for _label, name, _kind in CONTACT + ADDRESS]

# The form's own state, filled from the payload once it arrives. `saved` is the form as
# it last came from the server, so `dirty` is simply "the boxes say something else".
FORM = '''\tconst forms = computed(() => context.profile.data?.forms || {})
\tconst customer = ref("")
\tconst form = ref<Record<string, string>>({})
\tconst identity = ref<Record<string, string>>({})
\tconst saved = ref("")
\tconst saving = ref(false)

\tconst pick = (values: Record<string, string>, fields: string[]) =>
\t\tObject.fromEntries(fields.map((field) => [field, values[field] || ""]))

\tconst fillForm = () => {
\t\tconst values = forms.value[customer.value] || {}
\t\tidentity.value = pick(values, %(identity)s)
\t\tform.value = pick(values, %(fields)s)
\t\tsaved.value = JSON.stringify(form.value)
\t}
\twatch(forms, (all) => {
\t\tif (!(customer.value in all)) customer.value = context.profile.data?.form_customer || ""
\t\tfillForm()
\t}, { immediate: true })
\twatch(customer, () => { fillForm(); editing.value = false })

\tconst dirty = computed(() => JSON.stringify(form.value) !== saved.value)
\tconst edit = () => { editing.value = true }
\tconst cancel = () => { fillForm(); editing.value = false }

\tconst save = () => {
\t\tsaving.value = true
\t\tcall("lending.portal.profile.save_profile", { customer: customer.value, ...form.value })
\t\t\t.then((result: any) => {
\t\t\t\ttoast.success(result?.message || "Your details have been updated.")
\t\t\t\tediting.value = false
\t\t\t\tcontext.profile.reload()
\t\t\t})
\t\t\t.catch((error: any) => toast.error(String(error.messages?.[0] || error)))
\t\t\t.finally(() => { saving.value = false })
\t}''' % {
	"identity": [name for _label, name in IDENTITY],
	"fields": FIELDS,
}


def build():
	sections = [
		section(
			"file-user",
			"Basic information",
			"This information is fetched from your verified records.",
			[locked_box(label, name) for label, name in IDENTITY],
		),
		section(
			"phone", "Contact information", "Update your contact details.", boxes(CONTACT)
		),
		section("map-pin", "Address", "Enter your current address.", boxes(ADDRESS), rule=False),
	]
	body = column([header(), *sections], gap="0px")

	return upsert_page(
		"Personal details",
		"/profile",
		frame(SOURCE, [card("", "", body, styles=CARD, mobile={"padding": "12px 14px"})]),
		[
			api_resource(SOURCE, "lending.portal.profile.get_profile_page"),
			api_resource("alerts", "lending.portal.notifications.get_notifications", auto=0),
		],
		script=page_script(
			state=[("editing", "false")],
			body=FORM,
			returns=["form", "identity", "customer", "dirty", "edit", "cancel", "save", "saving"],
		),
	)


# Sized to fit a laptop screen without scrolling: the whole record is meant to be read
# at a glance, so every gap here is the smallest that still separates what it separates.
CARD = {"padding": "16px 20px"}


def header():
	"""The borrower's avatar and name, and what the form offers to press."""
	avatar = block(
		"Avatar",
		props={"label": "{{ identity.customer_name }}", "size": "2xl", "shape": "circle"},
		styles={"flex": "0 0 auto"},
		# What lending.portal.brand washes in the lender's primary colour, as the rail's is.
		classes=["portal-profile-avatar"],
	)
	name = text(
		"{{ identity.customer_name }}",
		tag="h2",
		size="text-lg",
		styles={"fontWeight": "600", "color": "var(--ink-gray-9)"},
	)
	lead = column([name], gap="0px", styles={"flex": "1 1 280px", "minWidth": "0px"})
	switcher = block(
		"FormControl",
		props={
			"type": "select",
			"options": fallback(read("customer_options"), "[]"),
			"modelValue": {"$type": "variable", "name": "customer"},
		},
		styles={"width": "200px"},
		visible="{{ (%s.data?.customer_options || []).length > 1 }}" % SOURCE,
	)
	# The label goes in the default slot as well as the prop: once a block has any slot,
	# Studio hands Button an empty default one too, and Button renders that over `label`.
	edit = button(
		"Edit",
		script="edit()",
		variant="outline",
		slots={
			**slot("prefix", [icon("square-pen", size=16)]),
			**slot("default", [text("Edit", tag="span", size="text-base")]),
		},
		visible="{{ !editing }}",
	)
	cancel = button("Cancel", script="cancel()", visible="{{ editing }}")
	save = button(
		fallback(read("save_label"), "'Save'"),
		script="save()",
		variant="solid",
		props={"disabled": "{{ !dirty }}", "loading": "{{ saving }}"},
		visible="{{ editing }}",
	)

	return column(
		[
			row(
				[avatar, lead, row([switcher, edit, cancel, save], styles={"flexWrap": "wrap"})],
				gap="12px",
				styles={"flexWrap": "wrap", "paddingBottom": "14px"},
			),
			divider(),
		],
		gap="0px",
	)


def section(glyph, title, subtitle, fields, rule=True, columns=3):
	"""A glyph on a tile, and beside it the section's heading over its boxes.

	`columns` boxes to a row, fewer when the card is narrow. The count comes from the
	card's own width, not a breakpoint: tablet styles fire only below a 768px viewport,
	and the sidebar squeezes the card long before that. A track is never under
	1/`columns` of the row, so there are never more than `columns`.
	"""
	track = f"calc((100% - {16 * columns}px) / {columns})"
	grid = container(
		fields,
		styles={
			"display": "grid",
			"gridTemplateColumns": f"repeat(auto-fill, minmax(min(100%, max(200px, {track})), 1fr))",
			"columnGap": "16px",
			"rowGap": "10px",
		},
	)
	titles = column(
		[heading(title, tag="h3", size="text-base"), *([muted(subtitle)] if subtitle else [])], gap="0px"
	)
	content = column([titles, grid], gap="10px", styles={"flex": "1 1 0%", "minWidth": "0px"})

	padding = "14px 0" if rule else "14px 0 0"
	parts = [
		row(
			[icon_tile(glyph, tile=32, glyph=16), content],
			gap="14px",
			align="start",
			styles={"padding": padding},
			mobile={"gap": "10px"},
		)
	]

	return column(parts + [divider()] if rule else parts, gap="0px")


def boxes(rows):
	return [box(label, name, kind) for label, name, kind in rows]


def box(label, name, kind):
	"""A box the borrower may correct, drawn as the desk draws a form field.

	frappe-ui's `subtle` variant is that field: a grey fill, no border, dark text.
	`readonly` rather than `disabled` outside edit mode, so the value keeps its dark text
	and reads as on record rather than as unavailable.
	"""
	return block(
		"FormControl",
		props={
			"type": kind,
			"label": label,
			"size": "md",
			"variant": "subtle",
			"placeholder": f"Enter {label.lower()}",
			"readonly": "{{ !editing }}",
			"modelValue": {"$type": "variable", "name": f"form.{name}"},
		},
	)


def locked_box(label, name):
	return block(
		"FormControl",
		props={
			"type": "text",
			"label": label,
			"size": "md",
			"disabled": True,
			"placeholder": "Not on record",
			"modelValue": {"$type": "variable", "name": f"identity.{name}"},
		},
	)
