# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from lending.portal.studio_build.app import api_resource, page_script, upsert_page
from lending.portal.studio_build.blocks import (
	PANEL,
	block,
	button,
	column,
	container,
	heading,
	icon,
	icon_tile,
	muted,
	reader,
	repeater,
	row,
	slot,
	text,
)
from lending.portal.studio_build.public import page

TRACK_SOURCE = "track"


read_track = reader(TRACK_SOURCE)

TRACK_SCRIPT = '''\tconst busy = ref(false)
\tconst result = ref<Record<string, any>>({})

\tconst find = () => {
\t\tbusy.value = true
\t\tcall("lending.portal.apply.track_application", {
\t\t\treference: reference.value,
\t\t\tmobile_number: mobileNumber.value,
\t\t})
\t\t\t.then((payload: any) => { result.value = payload })
\t\t\t.catch((error: any) =>
\t\t\t\ttoast.error(String(error?.messages?.[0] || error?.message || error)),
\t\t\t)
\t\t\t.finally(() => { busy.value = false })
\t}

\tconst startOver = () => { result.value = {} }'''


PAGE_WIDTH = "840px"

SHEET = dict(PANEL, padding="28px", borderRadius="var(--radius-6)")
SHEET_MOBILE = {"padding": "20px"}


def intro():
	centred = {"textAlign": "center", "alignSelf": "center"}

	eyebrow = text(
		read_track("eyebrow"),
		tag="span",
		size="text-sm",
		styles=dict(
			centred,
			textTransform="uppercase",
			letterSpacing="0.06em",
			color="var(--ink-gray-6)",
		),
	)
	title = text(
		read_track("heading"),
		tag="h1",
		size="text-5xl",
		# Studio's type scale stops short of this size.
		styles=dict(
			centred,
			fontSize="clamp(28px, 4.4vh, 40px)",
			fontWeight="700",
			lineHeight="1.15",
			letterSpacing="-0.02em",
			color="var(--ink-gray-9)",
		),
		mobile={"fontSize": "1.75rem"},
	)
	note = text(
		read_track("intro"),
		size="text-lg",
		styles=dict(centred, maxWidth="680px", lineHeight="1.6", color="var(--ink-gray-6)", whiteSpace="pre-line"),
	)

	return column(
		[eyebrow, column([title, note], gap="10px")],
		gap="16px",
		styles={"alignItems": "center", "padding": "clamp(8px, 3vh, 32px) 0 clamp(8px, 2vh, 20px)"},
	)


def field(label, ref_name, kind, placeholder, glyph):
	return block(
		"FormControl",
		props={
			"type": kind,
			"label": label,
			"placeholder": placeholder,
			"required": True,
			"size": "lg",
			"variant": "outline",
			"modelValue": {"$type": "variable", "name": ref_name},
		},
		slots=slot("prefix", [icon(glyph, size=18, styles={"color": "var(--ink-gray-5)"})]),
		styles={"flex": "1", "minWidth": "0px"},
	)


def track_form():
	head = row(
		[
			icon_tile("file-search-corner", tile=48, glyph=22),
			heading(read_track("track_title"), size="text-xl"),
		],
		gap="16px",
	)
	boxes = row(
		[
			field("Reference number", "reference", "text", "e.g. LEAD-0001", "file-text"),
			field("Mobile number", "mobileNumber", "tel", "e.g. 98765 43210", "phone"),
		],
		gap="24px",
		align="end",
		mobile={"flexDirection": "column", "alignItems": "stretch", "gap": "16px"},
	)
	# Label repeated in the default slot: with any slot, Studio's empty default one hides `label`.
	show = button(
		"Show me where it is",
		script="find()",
		variant="solid",
		props={"size": "lg", "loading": "{{ busy }}"},
		slots={
			**slot("suffix", [icon("arrow-right", size=16)]),
			**slot("default", [text("Show me where it is", tag="span", size="text-lg", styles={"fontWeight": "500"})]),
		},
		styles={"alignSelf": "flex-end"},
		mobile={"alignSelf": "stretch"},
	)

	return column([head, boxes, show], gap="24px", styles=SHEET, mobile=SHEET_MOBILE)


DOT = 28

# state: (fill, ring, ink, glyph)
DOT_STATES = {
	"done": (
		"var(--portal-primary-soft, var(--surface-green-2))",
		"var(--portal-primary-soft, var(--surface-green-2))",
		"var(--portal-primary-deep, var(--ink-green-7))",
		"check",
	),
	"now": (
		"var(--portal-primary, var(--surface-gray-9))",
		"var(--portal-primary, var(--surface-gray-9))",
		"var(--portal-primary-ink, var(--ink-base))",
		None,
	),
	"todo": ("var(--surface-base)", "var(--outline-gray-3)", "var(--ink-gray-4)", None),
	"stopped": ("var(--surface-red-2)", "var(--surface-red-2)", "var(--ink-red-6)", "x"),
}


def step_dot(state, fill, ring, ink, glyph):
	# One block per state, picked by `visible`: only props are evaluated, not styles.
	inside = [icon(glyph, size=14, stroke=3)] if glyph else []
	if state == "now":
		inside = [container(styles={"width": "10px", "height": "10px", "borderRadius": "9999px", "backgroundColor": ink})]

	return row(
		inside,
		gap="0px",
		styles={
			"width": f"{DOT}px",
			"height": f"{DOT}px",
			"flex": "0 0 auto",
			"justifyContent": "center",
			"borderRadius": "9999px",
			"border": f"1.5px solid {ring}",
			"backgroundColor": fill,
			"color": ink,
			# Stacks the dot over the absolutely placed rail.
			"position": "relative",
		},
		visible="{{ dataItem.state === '%s' }}" % state,
	)


def timeline():
	step = row(
		[
			*[step_dot(state, *look) for state, look in DOT_STATES.items()],
			column(
				[
					text("{{ dataItem.title }}", size="text-base", styles={"fontWeight": "500", "color": "var(--ink-gray-9)"}),
					text("{{ dataItem.note }}", size="text-p-sm", styles={"color": "var(--ink-gray-6)"}),
				],
				gap="2px",
				styles={"flex": "1 1 auto", "minWidth": "0px", "paddingTop": "4px"},
			),
		],
		gap="14px",
		align="start",
	)
	rail = container(
		styles={
			"position": "absolute",
			"top": f"{DOT // 2}px",
			"bottom": f"{DOT // 2}px",
			"left": f"{DOT // 2}px",
			"width": "1.5px",
			"transform": "translateX(-50%)",
			"backgroundColor": "var(--outline-gray-2)",
		}
	)
	steps = repeater(
		"{{ result.steps || [] }}",
		step,
		data_key="title",
		styles={"display": "flex", "flexDirection": "column", "gap": "20px"},
	)

	return container([rail, steps], styles={"position": "relative"})


def figures():
	figure = column(
		[
			muted("{{ dataItem.label }}"),
			text("{{ dataItem.value }}", size="text-lg", styles={"fontWeight": "600", "color": "var(--ink-gray-9)"}),
		],
		gap="4px",
	)

	return repeater(
		"{{ result.offer || [] }}",
		figure,
		data_key="label",
		styles={
			"display": "grid",
			"gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
			"gap": "16px",
			"padding": "16px 20px",
			"borderRadius": "var(--radius-5)",
			"backgroundColor": "var(--surface-gray-1)",
		},
		mobile={"gridTemplateColumns": "minmax(0, 1fr)"},
	)


def track_result():
	head = row(
		[
			icon_tile("file-text", tile=48, glyph=22),
			column(
				[heading("{{ result.headline }}", size="text-xl"), muted("{{ result.message }}")],
				gap="2px",
				styles={"flex": "1 1 auto", "minWidth": "0px"},
			),
		],
		gap="16px",
	)
	after = row(
		[
			icon("info", size=16, styles={"color": "var(--ink-gray-5)"}),
			muted("{{ result.reference_note }}", styles={"flex": "1 1 auto"}),
			button("Log in", script="open('/login')", variant="outline", props={"size": "md"}),
		],
		gap="10px",
		styles={"paddingTop": "20px", "borderTop": "1px solid var(--outline-gray-1)"},
	)

	return column(
		[head, figures(), timeline(), after],
		gap="24px",
		styles=SHEET,
		mobile=SHEET_MOBILE,
	)


def back():
	# Label repeated in the default slot, as in track_form.
	return button(
		"Track another application",
		script="startOver()",
		variant="ghost",
		slots={
			**slot("prefix", [icon("arrow-left", size=16)]),
			**slot("default", [text("Track another application", tag="span", size="text-base")]),
		},
		styles={"alignSelf": "flex-start"},
	)


def build_track():
	asking = "{{ !result.reference }}"
	found = "{{ result.reference }}"
	body = [
		column([intro(), track_form()], visible=asking),
		column([back(), track_result()], visible=found),
	]

	return upsert_page(
		"Track your application",
		"/track",
		page(read_track, [("Apply for a loan", "/apply"), ("Log in", "/login", "user")], body, width=PAGE_WIDTH),
		[api_resource(TRACK_SOURCE, "lending.portal.apply.get_track_page")],
		script=page_script(
			state=[("reference", '""'), ("mobileNumber", '""')],
			body=TRACK_SCRIPT,
			# Never return `track`: it would shadow the data source of that name.
			returns=["busy", "result", "find", "startOver"],
			framed=False,
		),
		allow_guest=True,
	)


def build():
	return build_track()
