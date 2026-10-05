# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

TONE = "tone({0})"

DATE_FORMAT = "DD-MM-YYYY"


def input_props(kind):
	# FormControl renders "date" as a DatePicker, which needs a format to show DD-MM-YYYY
	if kind != "date":
		return {"type": kind}
	return {"type": kind, "format": DATE_FORMAT, "placeholder": DATE_FORMAT.lower()}


def reader(source):
	"""`reader("overview")("crumb")` is `{{ overview.data.crumb }}`; no key reads the whole payload."""

	def read(key=""):
		return "{{ %s.data%s }}" % (source, f".{key}" if key else "")

	return read


def fallback(expression, default):
	"""Unresolved resources are undefined (always, on the canvas), which crashes frappe-ui components."""
	if not isinstance(expression, str):
		return expression
	if not (expression.startswith("{{") and expression.endswith("}}")):
		return expression

	return "{{ %s || %s }}" % (expression[2:-2].strip(), default)


def any_row(expression):
	inner = expression[2:-2].strip() if expression.startswith("{{") else expression

	return "{{ (%s || []).length > 0 }}" % inner


def no_rows(expression):
	inner = expression[2:-2].strip() if expression.startswith("{{") else expression

	return "{{ !(%s || []).length }}" % inner


def block(name, props=None, styles=None, children=None, **kwargs):
	node = {
		"componentName": name,
		"componentProps": props or {},
		"componentSlots": kwargs.pop("slots", None) or {},
		"componentEvents": kwargs.pop("events", None) or {},
		"baseStyles": styles or {},
		"mobileStyles": kwargs.pop("mobile", None) or {},
		"tabletStyles": kwargs.pop("tablet", None) or {},
		"children": children or [],
	}
	if visible := kwargs.pop("visible", None):
		node["visibilityCondition"] = visible

	node.update(kwargs)

	return node


def slot(name, content):
	return {name: {"slotName": name, "slotContent": content}}


def click(script):
	return {"click": {"event": "click", "action": "Run Script", "script": script}}


def root(children, direction="row"):
	"""Only a page's blocks[0] renders, so everything goes inside this one root."""
	return [
		block(
			"div",
			styles={
				"display": "flex",
				"flexDirection": direction,
				"width": "100%",
				"height": "100%",
				# Nothing above the root paints, so without this a dark page shows the browser's white.
				"backgroundColor": "var(--surface-base)",
				"color": "var(--ink-gray-8)",
				"overflowX": "hidden",
				"scrollbarWidth": "thin",
				"scrollbarColor": "var(--outline-gray-3) transparent",
			},
			children=children,
			# Scope for lending.portal.brand's button rule.
			classes=["borrower-portal"],
			originalElement="body",
			blockName="body",
		)
	]


def brand_style(expression):
	"""Hidden HTML block carrying the per-request stylesheet from lending.portal.brand."""
	return block("HTML", props={"html": fallback(expression, "''")}, styles={"display": "none"})


def container(children=None, styles=None, **kwargs):
	"""A div. `originalElement` is required, or the block and its children do not render."""
	return block("container", styles=styles, children=children, originalElement="div", **kwargs)


def column(children, gap="16px", **kwargs):
	styles = {"display": "flex", "flexDirection": "column", "gap": gap}
	styles.update(kwargs.pop("styles", None) or {})

	return container(children, styles=styles, **kwargs)


def row(children, gap="8px", align="center", **kwargs):
	styles = {"display": "flex", "flexDirection": "row", "alignItems": align, "gap": gap}
	styles.update(kwargs.pop("styles", None) or {})

	return container(children, styles=styles, **kwargs)


def text(value, tag="p", size="text-p-sm", **kwargs):
	return block("TextBlock", props={"text": value, "tag": tag, "fontSize": size}, **kwargs)


def heading(value, tag="h2", size="text-lg", **kwargs):
	styles = {"fontWeight": "600", "color": "var(--ink-gray-9)"}
	styles.update(kwargs.pop("styles", None) or {})

	return text(value, tag=tag, size=size, styles=styles, **kwargs)


def muted(value, **kwargs):
	styles = {"color": "var(--ink-gray-6)"}
	styles.update(kwargs.pop("styles", None) or {})

	return text(value, size="text-p-sm", styles=styles, **kwargs)


def subject(value, **kwargs):
	styles = {"fontWeight": "500"}
	styles.update(kwargs.pop("styles", None) or {})

	return text(value, size="text-base", styles=styles, **kwargs)


# Inline lucide SVG, not `lucide-*` classes: Tailwind emits those only for class names in scanned source.
ICON_PATHS = {
	"file-text": (
		'<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588'
		'A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/>'
		'<path d="M14 2v5a1 1 0 0 0 1 1h5"/>'
		'<path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>'
	),
	"calendar": (
		'<path d="M8 2v3"/><path d="M16 2v3"/>'
		'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/>'
	),
	"database": (
		'<ellipse cx="12" cy="5" rx="9" ry="3"/>'
		'<path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>'
	),
	"file": (
		'<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588'
		'A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/>'
		'<path d="M14 2v5a1 1 0 0 0 1 1h5"/>'
	),
	"file-search-corner": (
		'<path d="M11.1 22H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.706.706l3.589 3.588'
		'A2.4 2.4 0 0 1 20 8v3.25"/>'
		'<path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="m21 22-2.88-2.88"/>'
		'<circle cx="16" cy="17" r="3"/>'
	),
	"chevron-right": '<path d="m9 18 6-6-6-6"/>',
	"search": '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
	"arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
	"arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
	"corner-down-left": '<path d="M20 4v7a4 4 0 0 1-4 4H4"/><path d="m9 10-5 5 5 5"/>',
	"check": '<path d="M20 6 9 17l-5-5"/>',
	"x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
	"percent": (
		'<line x1="19" x2="5" y1="5" y2="19"/>'
		'<circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>'
	),
	"wallet": (
		'<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3'
		'a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/>'
		'<path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>'
	),
	"info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
	"square-pen": (
		'<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
		'<path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84'
		'a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/>'
	),
	"file-user": (
		'<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588'
		'A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/>'
		'<path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M16 22a4 4 0 0 0-8 0"/>'
		'<circle cx="12" cy="15" r="3"/>'
	),
	"phone": (
		'<path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3'
		'a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351'
		'a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384"/>'
	),
	"chart-no-axes": (
		'<path d="M6 20v-4"/><path d="M12 20V10"/><path d="M18 20V4"/>'
	),
	"shield": (
		'<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1'
		'c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
	),
	"receipt-text": (
		'<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/>'
		'<path d="M14 8H8"/><path d="M16 12H8"/><path d="M13 16H8"/>'
	),
	"arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
	"arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
	"map-pin": (
		'<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993'
		' 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>'
	),
	"user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
	"users": (
		'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
		'<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
	),
	"building-2": (
		'<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/>'
		'<path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>'
		'<path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/>'
		'<path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>'
	),
}

SVG = (
	'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24"'
	' fill="none" stroke="currentColor" stroke-width="{stroke}" stroke-linecap="round"'
	' stroke-linejoin="round">{paths}</svg>'
)

def icon(name, size=16, stroke=2, hint=None, **kwargs):
	"""`hint` becomes the SVG `<title>`; a Tooltip component would crash on the canvas."""
	styles = {"display": "flex", "alignItems": "center", "flex": "0 0 auto"}
	styles.update(kwargs.pop("styles", None) or {})

	paths = (f"<title>{hint}</title>" if hint else "") + ICON_PATHS[name]
	props = {"html": SVG.format(size=size, stroke=stroke, paths=paths)}

	return block("HTML", props=props, styles=styles, **kwargs)


def chevron(**kwargs):
	return icon("chevron-right", styles={"color": "var(--ink-gray-4)"}, **kwargs)


def icon_line(name, value, size=14, **kwargs):
	return row(
		[icon(name, size=size, styles={"color": "var(--ink-gray-5)"}), muted(value)],
		gap="6px",
		**kwargs,
	)


def icon_tile(name, theme="gray", tile=40, glyph=20, **kwargs):
	styles = dict(tile_styles(theme, tile), **(kwargs.pop("styles", None) or {}))

	return icon(name, size=glyph, styles=styles, **kwargs)


def tile_styles(theme="gray", tile=40):
	return {
		"display": "flex",
		"alignItems": "center",
		"flex": "0 0 auto",
		"width": f"{tile}px",
		"height": f"{tile}px",
		"justifyContent": "center",
		"borderRadius": "var(--radius-5)",
		"backgroundColor": f"var(--surface-{theme}-2)",
		"color": f"var(--ink-{theme}-8)",
	}


def badge(label, theme="gray", size="sm", **kwargs):
	props = {"label": label, "theme": theme, "variant": "subtle", "size": size}

	return block("Badge", props=props, **kwargs)


def toned_badge(label, tone_expression, **kwargs):
	return badge(label, theme="{{ %s }}" % TONE.format(tone_expression), **kwargs)


def button(label, script=None, variant="subtle", **kwargs):
	props = {"label": label, "variant": variant, "size": "sm"}
	props.update(kwargs.pop("props", None) or {})

	return block("Button", props=props, events=click(script) if script else None, **kwargs)


def alert(message, theme="blue", **kwargs):
	return block("Alert", props={"title": message, "theme": theme}, **kwargs)


def divider(**kwargs):
	return block("Divider", **kwargs)


def instance(component_id, props=None, **kwargs):
	"""A Studio Component; it reads props as `{{ inputs.<name> }}` and cannot wrap children."""
	return block(component_id, props=props, isStudioComponent=True, **kwargs)


def repeater(data, template, data_key="name", empty="", **kwargs):
	"""Inside `template`, the current row is `dataItem`."""
	props = {"data": data, "dataKey": data_key, "emptyStateMessage": empty}

	return block("Repeater", props=props, children=[template], **kwargs)


# Inline 12px matches LIST_INSET: the family insets only rows with a hover surface.
ROW_PADDING = {
	"paddingTop": "10px",
	"paddingBottom": "10px",
	"paddingInlineStart": "12px",
	"paddingInlineEnd": "12px",
}

# Transparent --outline-gray-1 hides the header's unreachable rule; margin, since row padding-top is lost.
HEADER_BAND = {
	"height": "36px",
	"borderRadius": "var(--radius-4)",
	"backgroundColor": "var(--surface-gray-2)",
	"--outline-gray-1": "transparent",
	"marginBottom": "10px",
}

# Not `list-row-px-3`: Studio's Tailwind has no rule for it.
LIST_INSET = {"--list-row-padding-x": "12px"}

# Turns the cell itself: a nested column would shift the block ids the rebuild merge matches on.
CELL_STACK = {"flexDirection": "column", "alignItems": "stretch", "gap": "2px"}


def record_list(columns, items, cells, row_key="name", script=None):
	"""`columns` are (grid track, heading[, "end"]) tuples; `cells` are lists of blocks per column."""
	ends = [len(column) > 2 and column[2] == "end" for column in columns]

	def aligned(styles, end):
		return dict(styles or {}, justifyContent="flex-end", textAlign="right") if end else styles

	def cell(content, end):
		return block(
			"ListCell",
			children=content,
			styles=aligned(CELL_STACK if len(content) > 1 else None, end),
		)

	header = block(
		"ListHeader",
		children=[
			block(
				"ListHeaderCell",
				children=[
					text(column[1], size="text-sm", styles={"color": "var(--ink-gray-6)"})
				],
				styles=aligned(None, end),
			)
			for column, end in zip(columns, ends)
		],
		styles=HEADER_BAND,
	)
	record = block(
		"ListRow",
		props={"value": "{{ value }}"},
		children=[cell(content, end) for content, end in zip(cells, ends)],
		events=click(script) if script else None,
		styles=ROW_PADDING,
	)
	rows = block(
		"ListRows",
		props={"items": fallback(items, "[]"), "rowKey": row_key},
		slots=slot("default", [record]),
	)

	return block(
		"List",
		props={"columns": [column[0] for column in columns]},
		children=[header, rows],
		visible=any_row(items),
		# A copy: callers update a List's styles in place.
		styles=dict(LIST_INSET),
	)


def pair_rows(items, with_detail=False, **kwargs):
	body = [muted("{{ dataItem.label }}"), text("{{ dataItem.value }}", size="text-base")]
	if with_detail:
		body.append(muted("{{ dataItem.detail }}", visible="{{ dataItem.detail }}"))

	template = column(body, gap="2px", styles={"padding": "8px 0"})

	return repeater(items, template, empty="Nothing to show", **kwargs)


def pair_grid(items, with_detail=False, **kwargs):
	styles = {"display": "grid", "gridTemplateColumns": "repeat(3, minmax(0, 1fr))", "gap": "12px"}
	tablet = {"gridTemplateColumns": "repeat(2, minmax(0, 1fr))"}
	mobile = {"gridTemplateColumns": "minmax(0, 1fr)"}
	body = [muted("{{ dataItem.label }}"), text("{{ dataItem.value }}", size="text-base")]
	if with_detail:
		body.append(muted("{{ dataItem.detail }}", visible="{{ dataItem.detail }}"))

	return repeater(
		items,
		column(body, gap="2px"),
		styles=styles,
		tablet=tablet,
		mobile=mobile,
		**kwargs,
	)


# The grid is pulled left by both and clipped, hiding the first column's rule at any column count.
FIELD_INSET = 16
FIELD_RULE = 1


def field_grid(items, with_detail=False, **kwargs):
	pull = f"{FIELD_INSET + FIELD_RULE}px"
	body = [
		text("{{ dataItem.label }}", size="text-sm", styles={"color": "var(--ink-gray-6)"}),
		text("{{ dataItem.value }}", size="text-base", styles={"color": "var(--ink-gray-8)"}),
	]
	if with_detail:
		body.append(muted("{{ dataItem.detail }}", visible="{{ dataItem.detail }}"))

	reading = column(
		body,
		gap="6px",
		styles={
			"minWidth": "0px",
			"paddingInlineStart": f"{FIELD_INSET}px",
			"paddingInlineEnd": f"{FIELD_INSET}px",
			"borderInlineStart": f"{FIELD_RULE}px solid var(--outline-gray-1)",
		},
	)
	grid = repeater(
		items,
		reading,
		empty="Nothing to show",
		styles={
			"display": "grid",
			"gridTemplateColumns": "repeat(3, minmax(0, 1fr))",
			"columnGap": "0px",
			"rowGap": "20px",
			"marginInlineStart": f"-{pull}",
		},
		tablet={"gridTemplateColumns": "repeat(2, minmax(0, 1fr))"},
		mobile={"gridTemplateColumns": "minmax(0, 1fr)"},
		**kwargs,
	)

	return container([grid], styles={"overflow": "hidden"})


def tab_strip(tabs, state):
	"""Not frappe-ui Tabs, which would draw every panel; labels appear twice since styles are not evaluated."""

	def tab(label, value):
		is_open = "%s === '%s'" % (state, value)
		label_style = {"whiteSpace": "nowrap"}

		return container(
			[
				text(label, size="text-base", styles=dict(label_style, color="var(--ink-gray-8)"), visible="{{ %s }}" % is_open),
				text(label, size="text-base", styles=dict(label_style, color="var(--ink-gray-5)"), visible="{{ !(%s) }}" % is_open),
				container(
					styles={
						"position": "absolute",
						"left": "0px",
						"right": "0px",
						# Inside the tab: the strip clips at its padding edge.
						"bottom": "0px",
						"height": "2px",
						"borderRadius": "9999px",
						"backgroundColor": "var(--portal-primary, var(--surface-gray-10))",
					},
					visible="{{ %s }}" % is_open,
				),
			],
			styles={"position": "relative", "padding": "10px 0", "cursor": "pointer", "flex": "0 0 auto"},
			events=click(f"{state}.value = '{value}'"),
		)

	return row(
		[tab(label, value) for label, value in tabs],
		gap="20px",
		align="stretch",
		styles={
			"borderBottom": "1px solid var(--outline-gray-2)",
			"overflowX": "auto",
			"overflowY": "hidden",
			"scrollbarWidth": "none",
		},
	)


# The --portal-* variables come from lending.portal.theme.SURFACES; the fallbacks keep the Studio canvas painted.
PANEL = {
	"padding": "16px",
	"borderWidth": "1px",
	"borderStyle": "solid",
	"borderColor": "var(--portal-panel-line, var(--outline-gray-2))",
	"borderRadius": "var(--radius-4)",
	"backgroundColor": "var(--portal-panel, var(--surface-base))",
}


def pressable(script):
	"""Returns (styles, block kwargs) that make a whole card clickable."""
	if not script:
		return {}, {}

	return {"cursor": "pointer"}, {
		"events": click(script),
		# Not a hover:border class: PANEL's inline border beats it. This one moves the variable PANEL reads.
		"classes": ["transition-colors", "portal-pressable"],
	}


def logos(read, frame):
	"""The logo once per mode; lending.portal.theme.SURFACES hides the one that does not apply."""
	plate = read("logo_plate")[2:-2].strip()

	def logo(key, mode, **styles):
		return block(
			"ImageView",
			props={"image": read(key), "alt": "", "shape": "square", "size": "lg"},
			# ImageView sizes start at 128px; the styles override them and `size` only picks the corner.
			styles=dict(frame, overflow="hidden", **styles),
			visible=read("brand_logo"),
			classes=[f"portal-logo-{mode}"],
		)

	return [
		logo("brand_logo", "light"),
		logo(
			"brand_logo_dark",
			"dark",
			backgroundColor="{{ %s ? '#ffffff' : 'transparent' }}" % plate,
			padding="{{ %s ? '3px' : '0px' }}" % plate,
		),
	]


def card(title, subtitle, body, action=None, **kwargs):
	parts = ([heading(title)] if title else []) + ([muted(subtitle)] if subtitle else [])
	titles = column(parts, gap="2px")
	head = titles if action is None else row([titles, spacer(), action], align="start")
	children = [body] if not parts and action is None else [head, body]
	styles = dict(PANEL, **(kwargs.pop("styles", None) or {}))

	return column(children, gap="12px", styles=styles, **kwargs)


def stat(
	title,
	value,
	note,
	flag=None,
	flag_tone=None,
	sub=None,
	icon_name=None,
	note_icon=None,
	script=None,
):
	"""Not NumberChart: figures arrive preformatted as strings; `icon_name` also shrinks the figure."""
	head = [muted(title)]
	if flag:
		theme = "{{ %s }}" % TONE.format(flag_tone) if flag_tone else "orange"
		head.append(badge(flag, theme=theme, visible=flag))
	if script:
		head += [spacer(), chevron()]

	figure = "text-2xl" if icon_name else "text-4xl"
	note_line = icon_line(note_icon, note) if note_icon else muted(note)
	body = [
		text(value, tag="div", size=figure, styles={"fontWeight": "600", "color": "var(--ink-gray-9)"}, visible=value),
		note_line,
	]
	if sub:
		body.append(muted(sub, visible=sub))

	lines = column(
		[row(head, gap="6px"), column(body, gap="2px")],
		gap="6px",
		styles={"flex": "1 1 auto", "minWidth": "0px"},
	)
	cursor, opens = pressable(script)
	children = ([icon_tile(icon_name)] if icon_name else []) + [lines]

	return row(children, gap="12px", align="start", styles=dict(PANEL, flex="1", **cursor), **opens)


def record_stat(icon_name, lines, script=None):
	"""The chevron for `script` goes in `lines`: only the page knows which is the label row."""
	cursor, opens = pressable(script)

	return row(
		[
			icon_tile(icon_name),
			column(lines, gap="2px", styles={"flex": "1 1 auto", "minWidth": "0px"}),
		],
		gap="12px",
		align="start",
		styles=dict(PANEL, flex="1", **cursor),
		**opens,
	)


def stat_strip(cards):
	styles = {"display": "flex", "flexDirection": "row", "gap": "12px", "width": "100%"}

	return container(cards, styles=styles, tablet={"flexWrap": "wrap"}, mobile={"flexDirection": "column"})


def two_columns(wide, narrow):
	styles = {
		"display": "grid",
		"gridTemplateColumns": "minmax(0, 2fr) minmax(0, 1fr)",
		"gap": "16px",
		"width": "100%",
	}

	return container(
		[column(wide), column(narrow)],
		styles=styles,
		tablet={"gridTemplateColumns": "minmax(0, 1fr)"},
	)


def spacer():
	return container(styles={"flex": "1 1 auto"})
