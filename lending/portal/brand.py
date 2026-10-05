# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from typing import NamedTuple

from lending.portal.colour import (
	DARK_INK,
	WHITE,
	channels,
	contrast,
	deep,
	ink_for,
	lift,
	mix,
	shade,
	to_hex,
	under,
)

# frappe-ui's dark --surface-base.
DARK_GROUND = (23, 23, 23)

HOVER_SHADE = 0.1
ACTIVE_SHADE = 0.2

# WCAG 1.4.11 non-text contrast.
UI_CONTRAST = 3.0

# Where the presets' hand-picked dark primaries sit (4.94 to 6.29); lifting a custom primary only
# to 3:1 left it dull beside them, navy turning a flat mid-blue.
DARK_PRIMARY_CONTRAST = 5.0

# Header buttons that only just cleared 3:1 on the dark band read as faint.
DARK_HEADER_CONTRAST = 3.5

SOFT_WEIGHT = 0.12
# 12% on near-black reads as grey; theme.SURFACES lifts the quiet inks to read on this.
DARK_BAND_WEIGHT = 0.22
LINE_WEIGHT = 0.35

SOFT_HOVER_WEIGHT = 0.18
SOFT_ACTIVE_WEIGHT = 0.24

# WCAG 1.4.3 body text contrast.
TEXT_CONTRAST = 4.5

# Scoped to the portal root so the Studio canvas does not repaint the editor's own buttons.
SOLID_BUTTON = ".borrower-portal button.bg-surface-gray-10"

# Selects render a grey button trigger too, but are fields, so they stay grey.
SUBTLE_BUTTON_ONLY = 'button.bg-surface-gray-2:not(.portal-plain):not([role="combobox"])'
SUBTLE_BUTTON = f".borrower-portal {SUBTLE_BUTTON_ONLY}"

HEADER = ".borrower-portal .portal-header"
HEADER_BUTTON = f"{HEADER} button.bg-surface-gray-10"

SIDEBAR = ".borrower-portal .bg-surface-sidebar"

FOOTER = ".borrower-portal .portal-footer"


def thinned(percent: int) -> str:
	return f"color-mix(in srgb, var(--portal-primary) {percent}%, transparent)"


WASH_VARIABLES = {
	"--surface-gray-2": thinned(8),
	"--surface-gray-3": thinned(12),
	"--surface-gray-4": thinned(18),
}

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

AVATAR = ".borrower-portal .portal-avatar"
AVATAR_VARIABLES = {
	# Not --surface-white: the Studio renderer CSS does not define it.
	"--surface-gray-2": "var(--surface-elevation-1)",
	"--ink-gray-5": "var(--portal-primary-deep)",
}
PROFILE_AVATAR = ".borrower-portal .portal-profile-avatar"
PROFILE_AVATAR_VARIABLES = {
	**AVATAR_VARIABLES,
	"--surface-gray-2": "var(--portal-primary-soft)",
}


class Mode(NamedTuple):
	ground: tuple
	dark: bool = False
	band_weight: float = SOFT_WEIGHT

	def wash(self, rgb, weight: float) -> str:
		return mix(rgb, self.ground, weight)

	def band(self, primary) -> str:
		"""The header, rail and footer wash."""
		return self.wash(primary, self.band_weight)

	def apart(self, rgb, against, bar=UI_CONTRAST) -> str:
		return (lift if self.dark else deep)(rgb, against, bar)

	def press(self, rgb, ink: str, amount: float) -> str:
		# Away from the label, so a pressed button never reads worse than a resting one.
		if self.dark and ink == to_hex(DARK_INK):
			return mix(rgb, WHITE, 1 - amount)

		return shade(rgb, amount)


LIGHT = Mode(WHITE)
DARK = Mode(DARK_GROUND, dark=True, band_weight=DARK_BAND_WEIGHT)


def brand_style(primary_color, secondary_color, dark_primary=None, dark_secondary=None, dark_ink=None) -> str:
	"""Wrapped in a div since DOMPurify drops a leading <style>; :root so teleported dialogs see it."""
	tokens = brand_tokens(primary_color, secondary_color)
	if not tokens:
		return ""

	dark = dark_tokens(primary_color, secondary_color, dark_primary, dark_secondary, dark_ink)
	# Same specificity as :root, so it must come after it.
	rules = [f":root {{ {declarations(tokens)} }}", f'[data-theme="dark"] {{ {declarations(dark)} }}']

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
		rules += [
			f"{HEADER} {SUBTLE_BUTTON_ONLY} {{ background-color: var(--surface-gray-2); color: var(--ink-gray-8); }}",
			f"{HEADER} {SUBTLE_BUTTON_ONLY}:hover {{ background-color: var(--surface-gray-3); }}",
			f"{HEADER} {SUBTLE_BUTTON_ONLY}:active {{ background-color: var(--surface-gray-4); }}",
		]
		rules.append(f"{AVATAR} {{ {declarations(AVATAR_VARIABLES)} }}")
		rules.append(f"{PROFILE_AVATAR} {{ {declarations(PROFILE_AVATAR_VARIABLES)} }}")
		rules += button_rules(HEADER_BUTTON, "--portal-header-action")

	return "<div><style>%s</style></div>" % " ".join(rules)


def brand_tokens(primary_color, secondary_color, mode=LIGHT, ink=None) -> dict:
	"""`ink` overrides the button label colour, for a preset whose APCA pick falls short."""
	primary = channels(primary_color)
	action = channels(secondary_color) or primary
	tokens = {}

	if primary:
		tokens["--portal-primary"] = to_hex(primary)
		tokens["--portal-primary-ink"] = ink_for(primary)
		tokens.update(progress_tokens(primary, mode))

	if action:
		tokens.update(button_tokens("--portal-action", action, mode, ink))
		tokens.update(wash_tokens(action, mode))

	if primary and action:
		header, header_ink = header_action(primary, action, mode)
		if header == action:
			header_ink = ink
		tokens.update(button_tokens("--portal-header-action", header, mode, header_ink))

	return tokens


def dark_tokens(primary_color, secondary_color, dark_primary, dark_secondary, dark_ink) -> dict:
	"""A preset brings its own dark pair; custom colours are lifted until they stand out on the dark ground."""
	primary = dark_primary or lifted(primary_color, DARK_PRIMARY_CONTRAST)
	secondary = dark_secondary or lifted(secondary_color, UI_CONTRAST)

	return brand_tokens(primary, secondary, DARK, dark_ink)


def swatch(primary_color, secondary_color, dark_primary=None, dark_secondary=None, dark_ink=None):
	"""The band and button as the portal paints them, so Desk previews the final button, not the input."""
	light = brand_tokens(primary_color, secondary_color)
	if not light:
		return None

	dark = dark_tokens(primary_color, secondary_color, dark_primary, dark_secondary, dark_ink)

	return {"light": swatch_mode(light, WHITE), "dark": swatch_mode(dark, DARK_GROUND)}


def swatch_mode(tokens, ground) -> dict:
	page = to_hex(ground)

	return {
		"page": page,
		"band": tokens.get("--portal-primary-soft", page),
		"primary": tokens.get("--portal-primary", page),
		"button": tokens["--portal-action"],
		"ink": tokens["--portal-action-ink"],
	}


def lifted(colour, bar):
	rgb = channels(colour)
	return lift(rgb, DARK_GROUND, bar) if rgb else None


def progress_tokens(primary, mode) -> dict:
	soft = mode.band(primary)

	return {
		"--portal-primary-soft": soft,
		"--portal-primary-line": mode.wash(primary, LINE_WEIGHT),
		# Text: the avatar's initials and the tracker's step labels.
		"--portal-primary-deep": mode.apart(primary, channels(soft), TEXT_CONTRAST),
	}


def wash_tokens(action, mode) -> dict:
	pressed = mode.wash(action, SOFT_ACTIVE_WEIGHT)

	return {
		"--portal-action-soft": mode.wash(action, SOFT_WEIGHT),
		"--portal-action-soft-hover": mode.wash(action, SOFT_HOVER_WEIGHT),
		"--portal-action-soft-active": pressed,
		"--portal-action-deep": mode.apart(action, channels(pressed), TEXT_CONTRAST),
	}


def header_action(primary, action, mode) -> tuple:
	"""The header button's fill, and its label when the default pick cannot fit."""
	# A secondary that can't clear 3:1 on the band (HDFC red on navy) takes the band's ink.
	band = channels(mode.band(primary))
	bar = DARK_HEADER_CONTRAST if mode.dark else UI_CONTRAST
	if contrast(action, band) >= bar:
		return action, None

	if not mode.dark:
		return channels(ink_for(band)), None

	# On a dark band the ink is white, and a white button glares; lightening keeps the brand.
	lighter = channels(lift(action, band, bar))
	if contrast(lighter, WHITE) >= TEXT_CONTRAST:
		return lighter, to_hex(WHITE)

	# Too light for a white label: darkening it back would sink it into the band, so the label goes dark.
	return lighter, to_hex(DARK_INK)


def button_tokens(prefix, rgb, mode, ink=None) -> dict:
	# APCA picks white on mid-tones like #ef6f21 at 3:1; the fill gives way so the label reaches 4.5:1.
	ink = ink or ink_for(rgb)
	rgb = channels(under(ink, rgb, TEXT_CONTRAST))

	return {
		prefix: to_hex(rgb),
		f"{prefix}-hover": mode.press(rgb, ink, HOVER_SHADE),
		f"{prefix}-active": mode.press(rgb, ink, ACTIVE_SHADE),
		f"{prefix}-ink": ink,
	}


def declarations(values: dict) -> str:
	return " ".join(f"{name}: {value};" for name, value in values.items())


def button_rules(selector, prefix) -> list:
	return [
		f"{selector} {{ background-color: var({prefix}); color: var({prefix}-ink); }}",
		f"{selector}:hover {{ background-color: var({prefix}-hover); }}",
		f"{selector}:active {{ background-color: var({prefix}-active); }}",
	]
