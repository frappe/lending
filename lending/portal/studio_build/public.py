# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The frame the two public pages share.

Neither /apply nor /track wears the borrower frame. Every row in that sidebar needs a
login, so a guest clicking one would be bounced; they carry this top bar instead, which
is why it is here rather than in `shell`.

Both pages are published with `allow_guest`, which is what lets the app renderer serve
them to somebody who has not signed in -- and, because one published guest page makes
the whole app guest-renderable, what lets the router reach them at all.
"""

from lending.portal.studio_build.blocks import (
	block,
	brand_style,
	button,
	container,
	icon,
	root,
	row,
	slot,
	spacer,
	text,
)

MARK = {"width": "26px", "height": "26px", "flexShrink": "0", "borderRadius": "6px"}

# The bar's links are set in pixels, as the opening screen of /apply is, and without the
# tracking Studio's size classes add.
LINK_TEXT = {"fontSize": "15px", "lineHeight": "20px", "letterSpacing": "0em"}

# Routes the site serves rather than the app. The rest are the app's own, and go through
# its router: a bare /track is the Builder page, which is not this portal.
SITE_ROUTES = {"/login"}


def page(read, links, body, width="720px", padding="clamp(16px, 3.6vh, 40px) 20px"):
	"""A public page: the bar, then one column of content, centred and capped at `width`."""
	well = container(
		body,
		styles={
			"display": "flex",
			"flexDirection": "column",
			"gap": "16px",
			# Shorter windows give up the padding first, before anything has to scroll.
			"padding": padding,
			"width": "100%",
			"maxWidth": width,
			"margin": "0 auto",
			# Fills the height under the bar, so a page can centre itself in what is left.
			"flex": "1 0 auto",
		},
		mobile={"padding": "24px 16px"},
	)

	return root(
		[
			container(
				[top_bar(read, links), well],
				styles={
					"display": "flex",
					"flexDirection": "column",
					"width": "100%",
					"height": "100%",
					"overflowY": "auto",
					# A step off white, so the panels on it read as panels.
					"backgroundColor": "var(--surface-gray-1)",
				},
			),
			brand_style(read("brand_style")),
		],
		direction="column",
	)


def mark(read):
	"""The lender's logo, or the first letter of its name on a tile when it has none.

	Both are written out and one renders, for the reason `shell.brand` gives: the page is
	built once and Lending Settings is read per request.
	"""
	logo = block(
		"ImageView",
		props={"image": read("brand_logo"), "alt": "", "shape": "square", "size": "lg"},
		styles=dict(MARK, overflow="hidden"),
		visible=read("brand_logo"),
	)
	letter = text(
		"{{ (%s || '').charAt(0) }}" % read("brand_name")[2:-2].strip(),
		size="text-base",
		styles=dict(
			MARK,
			display="flex",
			alignItems="center",
			justifyContent="center",
			fontSize="15px",
			fontWeight="700",
			textTransform="uppercase",
			# The primary on the bar's pale wash of it, as the signed-in rail's tile; on a
			# plain bar, a black tile.
			backgroundColor="var(--portal-primary, var(--ink-gray-9))",
			color="var(--portal-primary-ink, var(--surface-base))",
		),
		visible=read("show_wordmark"),
	)

	return [logo, letter]


def link_button(label, href, glyph=None, variant="ghost"):
	"""One place in the bar, led by `glyph` when it has one.

	The label goes in the default slot as well as the prop: once a block has any slot,
	Studio hands Button an empty default one too, and Button renders that over `label`.
	"""
	slots = slot("default", [text(label, tag="span", size="text-base", styles=LINK_TEXT)])
	if glyph:
		slots.update(slot("prefix", [icon(glyph, size=18)]))

	go = f"window.location.href = '{href}'" if href in SITE_ROUTES else f"open('{href}')"

	return button(
		label,
		script=go,
		variant=variant,
		props={"size": "md"},
		slots=slots,
		# A bare label needs less room round it than a button with a rule.
		styles={"height": "35px", "padding": "0 12px" if variant == "ghost" else "0 14px", "borderRadius": "8px"},
	)


def top_bar(read, links):
	"""The lender's name, and the two other places a visitor might want to be.

	A link is (label, href) or (label, href, glyph). The last one is the one a returning
	borrower wants, so it is the one drawn as a button rather than as a bare label. On a
	plain bar that is an outline. On a branded band it is solid, and wears the action
	colour the signed-in header's button does.
	"""
	branded = read("brand_style")[2:-2].strip()
	last = "{{ %s ? 'solid' : 'outline' }}" % branded

	return row(
		[
			*mark(read),
			text(
				read("brand_name"),
				tag="span",
				size="text-base",
				styles={
					"fontSize": "17px",
					"fontWeight": "600",
					"letterSpacing": "0em",
					"whiteSpace": "nowrap",
					"color": "var(--ink-gray-9)",
					"marginLeft": "2px",
				},
				mobile={"display": "none"},
			),
			spacer(),
			*[
				link_button(*link, variant=last if index == len(links) - 1 else "ghost")
				for index, link in enumerate(links)
			],
		],
		gap="12px",
		# A pale wash of the lender's primary colour, as the signed-in header is; the class
		# also turns the greys the bar's buttons hover in into washes of it.
		classes=["portal-header"],
		styles={
			# 54px tall with its rule, and the mockup's own margins either side.
			"height": "54px",
			"padding": "0 44px 0 56px",
			"flexShrink": "0",
			"width": "100%",
			"borderWidth": "0px 0px 1px 0px",
			"borderStyle": "solid",
			"borderColor": "var(--portal-primary-soft, var(--outline-gray-2))",
			"backgroundColor": "var(--portal-primary-soft, var(--surface-base))",
		},
		mobile={"padding": "12px 16px", "gap": "4px"},
	)
