# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Guest frame for /apply and /track; the borrower sidebar's rows all need a login."""

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

LINK_TEXT = {"fontSize": "15px", "lineHeight": "20px", "letterSpacing": "0em"}


def page(read, links, body, width="720px", padding="clamp(16px, 3.6vh, 40px) 20px"):
	well = container(
		body,
		styles={
			"display": "flex",
			"flexDirection": "column",
			"gap": "16px",
			"padding": padding,
			"width": "100%",
			"maxWidth": width,
			"margin": "0 auto",
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
					"backgroundColor": "var(--surface-gray-1)",
				},
			),
			brand_style(read("brand_style")),
		],
		direction="column",
	)


def mark(read, frame=MARK, letter_size="15px"):
	# Both rendered, one visible: the page is built once but Lending Settings is read per request.
	logo = block(
		"ImageView",
		props={"image": read("brand_logo"), "alt": "", "shape": "square", "size": "lg"},
		styles=dict(frame, overflow="hidden"),
		visible=read("brand_logo"),
	)
	letter = text(
		"{{ (%s || '').charAt(0) }}" % read("brand_name")[2:-2].strip(),
		size="text-base",
		styles=dict(
			frame,
			display="flex",
			alignItems="center",
			justifyContent="center",
			fontSize=letter_size,
			fontWeight="700",
			textTransform="uppercase",
			backgroundColor="var(--portal-primary, var(--ink-gray-9))",
			color="var(--portal-primary-ink, var(--surface-base))",
		),
		visible=read("show_wordmark"),
	)

	return [logo, letter]


def link_button(label, href, glyph=None, variant="ghost"):
	# Label repeated in the default slot: with any slot, Studio's empty default one hides `label`.
	slots = slot("default", [text(label, tag="span", size="text-base", styles=LINK_TEXT)])
	if glyph:
		slots.update(slot("prefix", [icon(glyph, size=18)]))

	return button(
		label,
		script=f"open('{href}')",
		variant=variant,
		props={"size": "md"},
		slots=slots,
		styles={"height": "35px", "padding": "0 12px" if variant == "ghost" else "0 14px", "borderRadius": "8px"},
	)


def top_bar(read, links):
	# `links` are (label, href[, glyph]); the last one renders as a button, the rest ghost.
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
		# Also recolours the buttons' grey hover states to the lender's primary.
		classes=["portal-header"],
		styles={
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
