# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The lender's two colours, as a stylesheet every portal page carries.

The Studio pages are built once and Lending Settings is read per request, so a colour
cannot be written into a block. Instead each page renders `brand_style()` through a
hidden HTML block, and the few places that wear the lender's colour read it back as
`var(--portal-primary, <frappe-ui's own colour>)`. A lender who sets nothing gets no
stylesheet, every fallback stands, and the portal looks as it always has.

Most banks carry two colours -- HDFC and Kotak a navy and a red, Canara a blue and a
yellow, ICICI a crimson and an orange -- and use them the same way: the first is who
the bank is, the second is what to press. So:

	primary     a wash of it for the header, the sidebar and the footer, the letter tile, the
	            thin marks of where you are -- the open tab, the current step -- and a
	            wash of it for the steps already done, on the trackers and the timeline,
	            and for the borrower's own initial at the foot of the sidebar
	secondary   solid buttons, and a wash of it for the grey buttons and the band over
	            a table; left blank, all three take the primary

The thin marks stay on the primary because a second colour is often a bright one, and
a bright one is lost on white: Canara's yellow is 1.8:1 against the page, well under
the 3:1 a 2px underline needs to be seen. A button carries its own ink, so it can be.

The values go into a <style> element, so they are parsed rather than trusted: anything
that is not a hex colour is dropped, which is also what keeps a stray `}` or `</style>`
in the field from reaching the page.
"""

import re

HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)

# The two inks a colour can carry: frappe-ui's white, and its darkest grey.
LIGHT_INK = (255, 255, 255)
DARK_INK = (23, 23, 23)

# How much darker a solid button goes under the pointer, and while pressed. frappe-ui
# steps its own gray-10 button down one shade for each.
HOVER_SHADE = 0.1
ACTIVE_SHADE = 0.2

# WCAG's floor for a control against what is behind it (1.4.11). A secondary colour
# that cannot clear it against the header band would put a button there that reads as
# a smudge -- HDFC's red on its navy is 2.0:1 -- so that button takes the band's ink.
UI_CONTRAST = 3.0

# APCA 0.0.98G's constants, which the Builder portal's ink choice used too.
APCA_BLACK_THRESHOLD = 0.022
APCA_BLACK_CLAMP = 1.414
APCA_SCALE = 1.14
APCA_LOW_CLIP = 0.1
APCA_OFFSET = 0.027

# How much of the primary a finished step's disc and its connector carry over white --
# the disc about as pale as frappe-ui's green-2, the line about as strong as green-3.
SOFT_WEIGHT = 0.12
LINE_WEIGHT = 0.35

# A subtle button steps one wash deeper under the pointer and another while pressed, as
# frappe-ui's own steps gray-2 to gray-3 to gray-4.
SOFT_HOVER_WEIGHT = 0.18
SOFT_ACTIVE_WEIGHT = 0.24

# WCAG's floor for body text (1.4.3), which a label on a wash has to clear.
TEXT_CONTRAST = 4.5

# frappe-ui's solid Button, as it paints itself. Scoped to the portal's own root so that
# the Studio canvas, if it ever resolves the binding, does not repaint the editor's own.
SOLID_BUTTON = ".borrower-portal button.bg-surface-gray-10"

# frappe-ui's grey subtle Button -- the variant a button takes when none is named, so
# Back and Cancel -- which wears a wash of the action colour. A block marked
# `portal-plain` keeps frappe-ui's grey: the statement's period shortcuts do. So does
# every select: its trigger is a grey button too, but it is a field and not an action,
# and it sits among the date and text fields, which stay grey.
SUBTLE_BUTTON_ONLY = 'button.bg-surface-gray-2:not(.portal-plain):not([role="combobox"])'
SUBTLE_BUTTON = f".borrower-portal {SUBTLE_BUTTON_ONLY}"

# The page's three bands -- the header, the rail and the footer -- are one pale wash of
# the primary colour, the same wash a done step's disc wears, so the text on them keeps
# frappe-ui's own greys. Everything on them reads a frappe-ui variable, so redefining
# those recolours a band whole: a grey badge and a row or link under the pointer become
# the primary thinned over the wash.
HEADER = ".borrower-portal .portal-header"
HEADER_BUTTON = f"{HEADER} button.bg-surface-gray-10"

# frappe-ui's Sidebar. Its greys are custom properties, so redefining them on this one
# element washes the rail -- its ground, a row under the pointer, the rule down its edge,
# the disc that shuts it -- and leaves every grey on the page beside it alone.
SIDEBAR = ".borrower-portal .bg-surface-sidebar"

FOOTER = ".borrower-portal .portal-footer"


def thinned(percent: int) -> str:
	"""The primary at `percent` strength over whatever is behind it."""
	return f"color-mix(in srgb, var(--portal-primary) {percent}%, transparent)"


WASH_VARIABLES = {
	"--surface-gray-2": thinned(8),
	"--surface-gray-3": thinned(12),
	"--surface-gray-4": thinned(18),
}

# The rule under the header takes the band's own colour, so the band has no hairline
# along its foot. The rail's edge and the footer's rule stay, a shade of the primary.
HEADER_VARIABLES = {
	"background-color": "var(--portal-primary-soft)",
	"--outline-gray-1": "var(--portal-primary-soft)",
	**WASH_VARIABLES,
}
SIDEBAR_VARIABLES = {
	"--surface-sidebar": "var(--portal-primary-soft)",
	"--outline-gray-1": thinned(18),
	**WASH_VARIABLES,
}
FOOTER_VARIABLES = {
	"background-color": "var(--portal-primary-soft)",
	"--outline-gray-2": thinned(18),
	**WASH_VARIABLES,
}

# The signed-in borrower's initial at the foot of the rail. frappe-ui's grey Avatar
# draws it in these two variables, so on this one avatar they become a white disc on
# the rail's wash, with the deep shade of the primary on it.
AVATAR = ".borrower-portal .portal-avatar"
AVATAR_VARIABLES = {
	"--surface-gray-2": "var(--surface-white)",
	"--ink-gray-5": "var(--portal-primary-deep)",
}


def channels(colour):
	"""(r, g, b) for a hex colour, or None for anything else."""
	match = HEX.match((colour or "").strip())
	if not match:
		return None

	digits = match.group(1)
	if len(digits) == 3:
		digits = "".join(digit * 2 for digit in digits)

	return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb) -> str:
	return "#" + "".join(f"{round(part):02x}" for part in rgb)


def luminance(rgb) -> float:
	"""WCAG relative luminance."""

	def linear(part):
		part /= 255
		return part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4

	red, green, blue = (linear(part) for part in rgb)

	return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first, second) -> float:
	high, low = sorted((luminance(first), luminance(second)), reverse=True)

	return (high + 0.05) / (low + 0.05)


def apca_y(rgb) -> float:
	"""Screen luminance as APCA measures it: the plain 2.4 exponent, with a soft clamp
	near black so that two very dark colours do not report a contrast nobody can see."""
	red, green, blue = ((part / 255) ** 2.4 for part in rgb)
	brightness = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue

	if brightness >= APCA_BLACK_THRESHOLD:
		return brightness

	return brightness + (APCA_BLACK_THRESHOLD - brightness) ** APCA_BLACK_CLAMP


def apca(text, background) -> float:
	"""How readable `text` is on `background`, from 0 to about 106, without its sign.

	About 60 is body text and about 45 a large label. Only ever used to choose between
	two inks, so which way round the polarity runs does not matter here.
	"""
	text_y, back_y = apca_y(text), apca_y(background)

	if back_y > text_y:
		raw = (back_y**0.56 - text_y**0.57) * APCA_SCALE
		return 0.0 if raw < APCA_LOW_CLIP else (raw - APCA_OFFSET) * 100

	raw = (back_y**0.65 - text_y**0.62) * APCA_SCALE

	return 0.0 if -raw < APCA_LOW_CLIP else -(raw + APCA_OFFSET) * 100


def ink_for(rgb) -> str:
	"""Whichever of white and the dark ink reads better on this colour.

	APCA rather than the WCAG ratio. WCAG puts the crossover at one luminance for every
	hue, and it overrates dark text on saturated mid-tones: it hands black to an orange
	like #ef6f21, a mid green, a teal and a pink, where white is what reads -- APCA
	scores white 61 and black 47 on that orange. It still hands dark ink to the colours
	that are truly light, a yellow, an amber, a cyan.
	"""
	return to_hex(max((LIGHT_INK, DARK_INK), key=lambda ink: apca(ink, rgb)))


def shade(rgb, amount: float) -> str:
	"""The colour mixed toward black by `amount`."""
	return to_hex(part * (1 - amount) for part in rgb)


def relight(rgb, target: float):
	"""The same colour at a given luminance, scaled on the linear channels so the hue holds."""

	def linear(part):
		part /= 255
		return part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4

	def encode(part):
		part = max(0.0, min(1.0, part))
		return 255 * (part * 12.92 if part <= 0.0031308 else 1.055 * part ** (1 / 2.4) - 0.055)

	current = luminance(rgb)
	scale = target / current if current else 0

	return tuple(encode(linear(part) * scale) for part in rgb)


def tint(rgb, weight: float) -> str:
	"""The colour laid thinly over white, `weight` of it to the rest white."""
	return to_hex(part * weight + 255 * (1 - weight) for part in rgb)


def deep(rgb, ground, bar=UI_CONTRAST) -> str:
	"""The colour, darkened only as far as it must be to stand at `bar` on `ground`.

	A tick on a pale disc is a glyph, not text, so 3:1 is the bar; a button's label or a
	column name is text, and asks TEXT_CONTRAST. A navy clears either as it is; Canara's
	lighter blue does not, and is relit on its linear channels -- which keeps its hue --
	to the luminance that does.
	"""
	if contrast(rgb, ground) >= bar:
		return to_hex(rgb)

	target = (luminance(ground) + 0.05) / bar - 0.05
	darker = channels(to_hex(relight(rgb, target)))

	# Rounding to whole channels can leave the result a hair short of the bar, so it
	# steps down a shade at a time until the colour as written clears it.
	while contrast(darker, ground) < bar:
		darker = channels(shade(darker, 0.02))

	return to_hex(darker)


def progress_tokens(primary) -> dict:
	"""What a finished step is drawn in: a pale disc, a stronger connector, a deep tick.

	Green was the colour of done until a lender set a primary; a tracker in the bank's own
	colour reads as the bank's, and the page already says "done" with the tick.
	"""
	soft = tint(primary, SOFT_WEIGHT)

	return {
		"--portal-primary-soft": soft,
		"--portal-primary-line": tint(primary, LINE_WEIGHT),
		"--portal-primary-deep": deep(primary, channels(soft)),
	}


def wash_tokens(action) -> dict:
	"""The action colour thinned onto white, for what is grey until a lender picks one:
	a subtle button at rest, under the pointer and pressed, and the band over a table.
	The label on it is the action colour taken as deep as body text needs on the deepest
	of the three washes, so it still reads while the button is held down."""
	pressed = tint(action, SOFT_ACTIVE_WEIGHT)

	return {
		"--portal-action-soft": tint(action, SOFT_WEIGHT),
		"--portal-action-soft-hover": tint(action, SOFT_HOVER_WEIGHT),
		"--portal-action-soft-active": pressed,
		"--portal-action-deep": deep(action, channels(pressed), TEXT_CONTRAST),
	}


def header_action(primary, action):
	"""What a solid button on the header band is filled with: the action colour if it
	stands out from the band, and the band's own ink if it does not."""
	band = channels(tint(primary, SOFT_WEIGHT))
	if contrast(action, band) >= UI_CONTRAST:
		return action

	return channels(ink_for(band))


def button_tokens(prefix, rgb) -> dict:
	"""A solid button's fill, its two pressed shades and its ink, under `prefix`."""
	return {
		prefix: to_hex(rgb),
		f"{prefix}-hover": shade(rgb, HOVER_SHADE),
		f"{prefix}-active": shade(rgb, ACTIVE_SHADE),
		f"{prefix}-ink": ink_for(rgb),
	}


def brand_tokens(primary_color, secondary_color) -> dict:
	"""The custom properties a lender's colours set, keyed by name. Unset ones are left out."""
	primary = channels(primary_color)
	action = channels(secondary_color) or primary
	tokens = {}

	if primary:
		tokens["--portal-primary"] = to_hex(primary)
		tokens["--portal-primary-ink"] = ink_for(primary)
		tokens.update(progress_tokens(primary))

	if action:
		tokens.update(button_tokens("--portal-action", action))
		tokens.update(wash_tokens(action))

	if primary and action:
		tokens.update(button_tokens("--portal-header-action", header_action(primary, action)))

	return tokens


def declarations(values: dict) -> str:
	return " ".join(f"{name}: {value};" for name, value in values.items())


def button_rules(selector, prefix) -> list:
	return [
		f"{selector} {{ background-color: var({prefix}); color: var({prefix}-ink); }}",
		f"{selector}:hover {{ background-color: var({prefix}-hover); }}",
		f"{selector}:active {{ background-color: var({prefix}-active); }}",
	]


def brand_style(primary_color, secondary_color) -> str:
	"""The stylesheet, wrapped as the HTML block needs it -- or "" when nothing is set.

	Wrapped in a div because DOMPurify, which the HTML block runs, drops a <style> that
	is the first thing in the fragment. The variables go on :root rather than the
	portal's root block, so the dialogs frappe-ui teleports to <body> see them too.
	"""
	tokens = brand_tokens(primary_color, secondary_color)
	if not tokens:
		return ""

	# The buttons, the band and the rail need rules of their own: everything else that
	# wears a colour already names its variable, with frappe-ui's colour as the fallback.
	rules = [f":root {{ {declarations(tokens)} }}"]

	if "--portal-action" in tokens:
		rules += button_rules(SOLID_BUTTON, "--portal-action")
		rules += [
			f"{SUBTLE_BUTTON} {{ background-color: var(--portal-action-soft); color: var(--portal-action-deep); }}",
			f"{SUBTLE_BUTTON}:hover {{ background-color: var(--portal-action-soft-hover); }}",
			f"{SUBTLE_BUTTON}:active {{ background-color: var(--portal-action-soft-active); }}",
		]

	if channels(primary_color):
		rules.append(f"{HEADER} {{ {declarations(HEADER_VARIABLES)} }}")
		rules.append(f"{SIDEBAR} {{ {declarations(SIDEBAR_VARIABLES)} }}")
		rules.append(f"{FOOTER} {{ {declarations(FOOTER_VARIABLES)} }}")
		# A grey button on the band keeps the band's own wash of its ink, as the bell does,
		# rather than a wash of the action colour laid over the primary.
		rules += [
			f"{HEADER} {SUBTLE_BUTTON_ONLY} {{ background-color: var(--surface-gray-2); color: var(--ink-gray-8); }}",
			f"{HEADER} {SUBTLE_BUTTON_ONLY}:hover {{ background-color: var(--surface-gray-3); }}",
			f"{HEADER} {SUBTLE_BUTTON_ONLY}:active {{ background-color: var(--surface-gray-4); }}",
		]
		rules.append(f"{AVATAR} {{ {declarations(AVATAR_VARIABLES)} }}")
		rules += button_rules(HEADER_BUTTON, "--portal-header-action")

	return "<div><style>%s</style></div>" % " ".join(rules)
