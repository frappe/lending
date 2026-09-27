# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The block vocabulary the Studio pages are written in.

Studio stores a page as a tree of blocks, each naming a Vue component: a frappe-ui one
(Button, Badge, FormControl, List), a Studio one (TextBlock, Repeater, HTML), or the
bare `container`, which renders as a div. This module is the Studio counterpart of
the Builder portal's own theme module, and the difference between the two says what
the migration was:
theme draws a badge as a styled span, and `badge()` below asks for the Badge component.

Almost nothing here sets a colour, a border or a font. The Builder portal carries its
own design system -- some thirty CSS custom properties driven by Lending Settings --
and the Studio pages deliberately do not: they take frappe-ui's own appearance first,
so what is on the canvas is a component to restyle rather than a div already painted.
Only layout (flex, gap, padding, width) is written here. The exception is the lender's
two colours, which a handful of blocks read as `var(--portal-primary, ...)` -- see
lending.portal.brand.

A value in a prop can be a `{{ }}` expression, evaluated against the page's data
sources, its script's return value, and `route`/`router`. That is how a block reads
live data, so most helpers take an expression rather than a string.
"""

# A payload tone -- "", "ok", "warn", "danger" -- read through the page script's own
# `tone()` helper. Written once here so no page spells the call out.
TONE = "tone({0})"


def reader(source):
	"""A page's own way of reading its data source.

	`read = reader("overview")` makes `read("crumb")` the expression
	`{{ overview.data.crumb }}`, and `read()` the whole payload. Every page binds
	dozens of keys, and spelling the source out at each of them is what makes a page
	hard to move to another endpoint.
	"""

	def read(key=""):
		return "{{ %s.data%s }}" % (source, f".{key}" if key else "")

	return read


def fallback(expression, default):
	"""The same expression, answering with `default` until its source arrives.

	A page's resources hold nothing until they resolve, and on the Studio canvas they
	never resolve at all. The evaluator rewrites `loan.data.schedule` as optional
	chaining, so the expression itself is safe and hands back `undefined` -- but a
	frappe-ui component that indexes what it is given, `items.map` or `title.charAt`,
	throws on that while rendering, and Vue tears the subtree down with it. Anything
	bound to a resource and read that way needs a value of the right shape instead.
	"""
	if not isinstance(expression, str):
		return expression
	if not (expression.startswith("{{") and expression.endswith("}}")):
		return expression

	return "{{ %s || %s }}" % (expression[2:-2].strip(), default)


def any_row(expression):
	"""The condition that `expression` holds at least one row.

	`|| []` for the same reason `fallback` has one: a resource holds nothing until it
	resolves, and `.length` of `undefined` throws while rendering rather than reading
	as zero.
	"""
	inner = expression[2:-2].strip() if expression.startswith("{{") else expression

	return "{{ (%s || []).length > 0 }}" % inner


def no_rows(expression):
	"""The condition that `expression` holds nothing: what an empty state shows on."""
	inner = expression[2:-2].strip() if expression.startswith("{{") else expression

	return "{{ !(%s || []).length }}" % inner


def block(name, props=None, styles=None, children=None, **kwargs):
	"""One block. `name` is the component, everything else is optional."""
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
	"""A named slot, in the shape Studio stores one."""
	return {name: {"slotName": name, "slotContent": content}}


def click(script):
	"""An onclick handler, in the shape Studio stores one."""
	return {"click": {"event": "click", "action": "Run Script", "script": script}}


# --- layout -------------------------------------------------------------------------


def root(children, direction="row"):
	"""The page's one outermost block.

	A page stores a list of blocks and renders the first of them -- AppContainer reads
	`blocks[0]`, and so does the exporter that collects which components a page uses. So
	a page is one root with everything inside it, never two blocks side by side.

	`originalElement: body` is what marks a block the root.

	The scrollbar is set here and nowhere else. `scrollbar-width` and `scrollbar-color`
	both inherit, so the root hands them to every scroller the page grows -- the sidebar,
	the main column, a panel added next month -- without any of them having to ask. The
	colour is frappe-ui's own thumb: its ScrollArea paints `bg-gray-400`, dark
	`bg-gray-700`, and `--outline-gray-3` is that pair under one name that tracks the
	theme. What a bare scrollbar cannot copy is the fade -- frappe-ui's is an overlay
	that hides when idle, which no CSS scrollbar property can express.
	"""
	return [
		block(
			"div",
			styles={
				"display": "flex",
				"flexDirection": direction,
				"width": "100%",
				"height": "100%",
				"overflowX": "hidden",
				"scrollbarWidth": "thin",
				"scrollbarColor": "var(--outline-gray-3) transparent",
			},
			children=children,
			# What lending.portal.brand scopes its button rule to.
			classes=["borrower-portal"],
			originalElement="body",
			blockName="body",
		)
	]


def brand_style(expression):
	"""The lender's colours, as a stylesheet: see lending.portal.brand.

	Hidden, and still applied. Read through `fallback` because the canvas never resolves
	the source, and a page is built once while the colours are read per request.
	"""
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


# --- text ---------------------------------------------------------------------------


def text(value, tag="p", size="text-p-sm", **kwargs):
	"""A line of copy. `size` follows Studio's own scale; text-p-* is the paragraph family."""
	return block("TextBlock", props={"text": value, "tag": tag, "fontSize": size}, **kwargs)


def heading(value, tag="h2", size="text-lg", **kwargs):
	styles = {"fontWeight": "600"}
	styles.update(kwargs.pop("styles", None) or {})

	return text(value, tag=tag, size=size, styles=styles, **kwargs)


def muted(value, **kwargs):
	"""The quieter second line under a heading or a row.

	`text-p-sm`, not `-xs`: a borrower reads these lines -- a reference, a due date --
	and 12px grey is too small to take in at a glance.
	"""
	styles = {"color": "var(--ink-gray-6)"}
	styles.update(kwargs.pop("styles", None) or {})

	return text(value, size="text-p-sm", styles=styles, **kwargs)


def subject(value, **kwargs):
	"""What a record row is about, against the lines that only describe it.

	The List family paints no cell -- unlike the ListView it replaces, it sets no ink on
	the first column and none on the rest -- so every line of a row arrives at one
	weight. `muted` quiets the describing lines; this lifts the one a borrower scans for,
	what the row stands for, the way the desk's list view sets its first column.
	"""
	styles = {"fontWeight": "500"}
	styles.update(kwargs.pop("styles", None) or {})

	return text(value, size="text-base", styles=styles, **kwargs)


# --- icons ------------------------------------------------------------------------------

# lucide's own paths, copied from lucide-static. A `lucide-*` class is a Tailwind mask
# emitted only where that exact class name sits in scanned source, so a class name
# written here would arrive in the app with no CSS behind it. The markup is drawn by
# Studio's HTML block, which sanitises what it is given -- DOMPurify keeps SVG.
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
	"""One glyph, drawn at `size` and painted by whatever colour it inherits.

	`stroke` is in the glyph's own 24-unit box, so it thins as `size` shrinks: a 12px
	glyph at the default draws a 1px line. `hint` becomes the SVG's own `<title>`, which
	the browser shows on hover -- no Tooltip component, so nothing that can crash on the canvas.
	"""
	styles = {"display": "flex", "alignItems": "center", "flex": "0 0 auto"}
	styles.update(kwargs.pop("styles", None) or {})

	paths = (f"<title>{hint}</title>" if hint else "") + ICON_PATHS[name]
	props = {"html": SVG.format(size=size, stroke=stroke, paths=paths)}

	return block("HTML", props=props, styles=styles, **kwargs)


def chevron(**kwargs):
	"""The mark at the end of a card's label saying the card opens something.

	The affordance a row in the List family already has, at the size of a card. Not a
	button: a card with a button in it is two things to press, and the card is the
	larger target.
	"""
	return icon("chevron-right", styles={"color": "var(--ink-gray-4)"}, **kwargs)


def icon_line(name, value, size=14, **kwargs):
	"""A quiet line led by a glyph: a date, a place, whatever the glyph names.

	The glyph takes its colour from the row, not from the text beside it -- an SVG
	inherits `currentColor` from its parent, and the parent here is the row.
	"""
	return row(
		[icon(name, size=size, styles={"color": "var(--ink-gray-5)"}), muted(value)],
		gap="6px",
		**kwargs,
	)


def icon_tile(name, theme="gray", tile=40, glyph=20, **kwargs):
	"""A glyph on a tinted square: what a card about a record or a figure leads with.

	Grey unless `theme` names a status. A tile tinted for decoration competes with the
	badges and trackers, where colour means something.
	"""
	styles = dict(tile_styles(theme, tile), **(kwargs.pop("styles", None) or {}))

	return icon(name, size=glyph, styles=styles, **kwargs)


def tile_styles(theme="gray", tile=40):
	"""A tile's square, for a tile that holds something other than a glyph.

	Rounded to `--radius-5` rather than to a circle. A disc reads as a person, which is
	what an Avatar is for; these stand for a document and an amount.
	"""
	return {
		"display": "flex",
		"alignItems": "center",
		"flex": "0 0 auto",
		"width": f"{tile}px",
		"height": f"{tile}px",
		"justifyContent": "center",
		"borderRadius": "var(--radius-5)",
		"backgroundColor": f"var(--surface-{theme}-2)",
		"color": f"var(--ink-{theme}-7)",
	}


# --- components -----------------------------------------------------------------------


def badge(label, theme="gray", size="sm", **kwargs):
	"""A status. `theme` is a frappe-ui theme, or an expression producing one.

	`sm` is the badge that rides along a line of something else -- the flag on a figure
	card. A badge that is a column of its own wants `lg`, which is the size the rest of
	a record row is set at rather than the size of a label stuck to it.
	"""
	props = {"label": label, "theme": theme, "variant": "subtle", "size": size}

	return block("Badge", props=props, **kwargs)


def toned_badge(label, tone_expression, **kwargs):
	"""A status whose colour comes from the payload rather than from the page."""
	return badge(label, theme="{{ %s }}" % TONE.format(tone_expression), **kwargs)


def button(label, script=None, variant="subtle", **kwargs):
	props = {"label": label, "variant": variant, "size": "sm"}
	props.update(kwargs.pop("props", None) or {})

	return block("Button", props=props, events=click(script) if script else None, **kwargs)


def alert(message, theme="blue", **kwargs):
	"""A quiet panel of guidance, shown only when the data supplies one."""
	return block("Alert", props={"title": message, "theme": theme}, **kwargs)



def divider(**kwargs):
	return block("Divider", **kwargs)


def instance(component_id, props=None, **kwargs):
	"""A Studio Component, rendered with these inputs.

	A component's own tree reads them as `{{ inputs.<name> }}`. Its children are its
	own: unlike a Builder component, a Studio one cannot be wrapped around page
	content, which is why the portal frame is three components beside the content
	rather than one around it. See shell.
	"""
	return block(component_id, props=props, isStudioComponent=True, **kwargs)


# --- lists ----------------------------------------------------------------------------


def repeater(data, template, data_key="name", empty="", **kwargs):
	"""`template` once per row of `data`. Inside it, a row is `dataItem`."""
	props = {"data": data, "dataKey": data_key, "emptyStateMessage": empty}

	return block("Repeater", props=props, children=[template], **kwargs)


# A row is as tall as what is in it, so the padding is what keeps two of them apart.
# Rows here are two lines or four -- a draft application carries a line saying what it
# is waiting for -- and the fixed `rowHeight` this replaces fitted only two. The inline
# 12px is the inset the column names take from LIST_INSET, said here so that a row
# without a hover surface to inset itself from still lines up with them; on a row that
# has one it lands on exactly the 12px the family was already giving it.
ROW_PADDING = {
	"paddingTop": "10px",
	"paddingBottom": "10px",
	"paddingInlineStart": "12px",
	"paddingInlineEnd": "12px",
}

# The band the column names sit on. frappe-ui's own header is a rule under the labels
# and nothing else, which the portal's rows are too tall and too quiet to be told from;
# this is the filled strip the desk's list view draws. `height` is a style because the
# component sets 32px as a class, and only a style outranks one.
#
# The rule itself is still drawn, as a child of the header that no block reaches, and
# under a filled band it reads as a grey line along the band's bottom edge. That child is
# the only thing in the header coloured `outline-gray-1`, so the header redefines the
# token as transparent for itself and its children and the line goes with it.
#
# The gap under the band is the header's margin, not the first row's padding-top: on
# the published bundle the row's padding-top never reached the page, and the first row
# sat flush against the band.
HEADER_BAND = {
	"height": "36px",
	"borderRadius": "var(--radius-4)",
	"backgroundColor": "var(--surface-gray-2)",
	"--outline-gray-1": "transparent",
	"marginBottom": "10px",
}

# The inset the column names take, through the family's own hook. `list-row-px-3` is
# the class the family documents for this, but Studio's Tailwind has no rule for it, so
# the header stood flush with the band's edge, 12px left of the text under it.
LIST_INSET = {"--list-row-padding-x": "12px"}

# What a cell of more than one line needs. A ListCell is a flex box with `items-center`,
# which is a row -- so its lines were laid side by side, and "Personal Loan" ran into the
# two lines that belong under it. Turning the cell itself is what turns them, rather than
# standing a column inside it: a block added under a cell renames every block below it,
# and an id is what tells the next rebuild the same block from a new one.
#
# `stretch` rather than `flex-start`, which the turned cell would otherwise inherit from
# `items-center`: a line sized to its own content has nothing to wrap against, so a long
# product name would run out of the column and into the stage beside it.
CELL_STACK = {"flexDirection": "column", "alignItems": "stretch", "gap": "2px"}


def record_list(columns, items, cells, row_key="name", script=None):
	"""The List family: a header of labels, then one row per record.

	`columns` are CSS grid tracks paired with their heading, and `cells` builds the
	blocks of one row from `item`, the slot's name for the current record. A cell is a
	list, and a cell of several blocks reads as lines stacked down the row. `script`
	makes the whole row the way into the record it stands for.

	An empty list is the whole block hidden rather than a header standing over nothing.
	Every card that holds one of these already says in its subtitle how many rows it
	has, so the column names are the only thing left to say it a second time and worse.

	A column may carry a third item, "end", to set its heading and its cells flush
	right -- the way the desk's report view sets a column of money, so the figures line
	up by their last digit.
	"""
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
					text(column[1], size="text-sm", styles={"color": "var(--ink-gray-5)"})
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
		# The header's own inset, which it takes from this hook and nowhere else. The
		# rows take the same 12px from ROW_PADDING rather than from the hook, because
		# the family hands it only to a row with a hover surface to inset it from -- so
		# a list of plain rows would otherwise sit 12px left of the names of its columns.
		styles=LIST_INSET,
	)


def pair_rows(items, with_detail=False, **kwargs):
	"""A repeater over {label, value, detail} rows -- the portal's workhorse shape."""
	body = [muted("{{ dataItem.label }}"), text("{{ dataItem.value }}", size="text-base")]
	if with_detail:
		body.append(muted("{{ dataItem.detail }}", visible="{{ dataItem.detail }}"))

	template = column(body, gap="2px", styles={"padding": "8px 0"})

	return repeater(items, template, empty="Nothing to show", **kwargs)


def pair_grid(items, with_detail=False, **kwargs):
	"""The same rows, three to a row -- eight readings of one record, within a glance."""
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


# Where a field grid's column rule sits: the inset each reading keeps from the rule on
# its left, plus the rule itself. The grid is pulled left by both, so the first
# column's rule falls outside its clipping box and the readings line up with the text above.
FIELD_INSET = 16
FIELD_RULE = 1


def field_grid(items, with_detail=False, **kwargs):
	"""{label, value, detail} rows as the desk reads a record: three columns with a rule between them.

	A label in grey over its value, the way a read-only field sits on a Frappe form. The
	rule is each reading's left border. A repeated block cannot tell which copy starts a
	row, so the grid is pulled left by one inset and one rule, and the wrapper clips what
	lands outside -- the first column's rule, at every column count the grid falls to.
	"""
	pull = f"{FIELD_INSET + FIELD_RULE}px"
	body = [
		text("{{ dataItem.label }}", size="text-sm", styles={"color": "var(--ink-gray-5)"}),
		text("{{ dataItem.value }}", size="text-base", styles={"color": "var(--ink-gray-9)"}),
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
	"""frappe-ui's Tabs, drawn from blocks: a row of labels on a rule, the open one underlined.

	Not the Tabs component, which renders its panel slot once for whichever tab is open --
	so every panel under it would draw at once. The look is copied from its source: 14px
	labels 20px apart, grey-5 until open and grey-9 once it is, and a 2px bar in
	surface-gray-10 standing on the rule under the open one -- or in the lender's brand
	colour, where one is set.

	`tabs` is (label, value) pairs and `state` the page ref that holds the open value.
	A label's colour is a style, and only props are evaluated, so each label is in the
	tree twice and the ref shows one.
	"""

	def tab(label, value):
		is_open = "%s === '%s'" % (state, value)
		label_style = {"whiteSpace": "nowrap"}

		return container(
			[
				text(label, size="text-base", styles=dict(label_style, color="var(--ink-gray-9)"), visible="{{ %s }}" % is_open),
				text(label, size="text-base", styles=dict(label_style, color="var(--ink-gray-5)"), visible="{{ !(%s) }}" % is_open),
				container(
					styles={
						"position": "absolute",
						"left": "0px",
						"right": "0px",
						# Inside the tab rather than over the rule: the strip clips at its
						# padding edge, and the rule is outside it.
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

	# The strip scrolls rather than wrapping, as frappe-ui's does, so four tabs on a phone
	# do not push the page wider than the screen. The bar is hidden: the cut-off label
	# already says there is more, and a bar under the rule reads as a second rule.
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


# --- panels ---------------------------------------------------------------------------

# What a card and a number card are both drawn on. The one place this file names a
# colour, because a panel that does not separate itself from the page is not a panel.
PANEL = {
	"padding": "16px",
	"borderWidth": "1px",
	"borderStyle": "solid",
	"borderColor": "var(--outline-gray-2)",
	"borderRadius": "var(--radius-4)",
	"backgroundColor": "var(--surface-base)",
}


def pressable(script):
	"""What makes a whole card the way into the record or the page it stands for.

	The styles and the block's own kwargs come back together because they are one
	decision said twice: the cursor is a style, and the hover it promises cannot be --
	an inline style has no hover. The border is what lights up, so the card answers
	without moving anything on the page, and the app's bundle carries the class the
	same way it carries the crumb's in shell.
	"""
	if not script:
		return {}, {}

	return {"cursor": "pointer"}, {
		"events": click(script),
		"classes": ["transition-colors", "hover:border-outline-gray-3"],
	}


def card(title, subtitle, body, action=None, **kwargs):
	"""A titled panel with a subtitle from the data. Every portal page is built of these.

	Studio Components take inputs, not children, so a card cannot be one: its body is
	whatever the page puts in it. It stays a function that builds blocks, the way
	`theme.card` is on the Builder side.
	"""
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
	"""One number card: a label, the figure, and a line saying what it is.

	Not a NumberChart. Every figure on the portal arrives already formatted and
	translated -- "₹3,17,450", "Nothing due" -- because the Builder pages could not
	format one, and a chart that wants a number would print the string as NaN.

	`icon_name` gives it the shape of the record card it stands beside: a tinted tile on
	the left, the lines to its right. A strip then reads as one row of cards rather than
	as a record card and two figures that happen to share a border.

	It also settles the figure's size, which is why the two are one argument. A card with
	a tile has a headline where the tile is, and 4xl beside a 40px tile over two lines of
	note fills the card and still disagrees with the record card's own 2xl headline. A
	card without one is all figure, and keeps the size it had.

	`note_icon` leads the note with a glyph, the way the record card beside it leads the
	day it was raised. For a note that says when, so the two cards date a line alike.

	`script` makes the whole card the way into the page the figure comes from, and says
	so with a chevron at the end of the label.
	"""
	head = [muted(title)]
	if flag:
		theme = "{{ %s }}" % TONE.format(flag_tone) if flag_tone else "orange"
		head.append(badge(flag, theme=theme, visible=flag))
	if script:
		head += [spacer(), chevron()]

	figure = "text-2xl" if icon_name else "text-4xl"
	note_line = icon_line(note_icon, note) if note_icon else muted(note)
	body = [text(value, tag="div", size=figure, styles={"fontWeight": "600"}, visible=value), note_line]
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
	"""A card the size of a stat, standing on a record instead of a figure.

	What a borrower reads off an application is its name, its stage and the day it was
	raised -- four short lines, none of which is a number. Drawn as a stat they are a
	4xl product name pretending to be an amount, so this leads with a tile and lets the
	lines stay the size they are. The tile is the plain grey one the figure cards beside
	it wear: the stage already says its colour on its own badge, and a green tile beside
	two grey ones read as the one card that was different in kind.

	`lines` is whatever the page stacks beside the tile, top to bottom. The tile sits at
	the top of them rather than in the middle, as it does on the figure cards beside it:
	centred against six lines it drifts down to where the third of them starts, and the
	strip's three tiles stop sharing a line.

	`script` opens the record, as it does on a stat. The chevron that says so goes in
	`lines`, because only the page knows which of them is the label row it belongs on.
	"""
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
	"""The record down the wide side, what is coming down the narrow one."""
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
