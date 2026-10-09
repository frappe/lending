# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

# Colours land inside a <style>, so anything that is not a hex colour must be dropped.
HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)

LIGHT_INK = (255, 255, 255)
DARK_INK = (23, 23, 23)

HOVER_SHADE = 0.1
ACTIVE_SHADE = 0.2

# WCAG 1.4.11 non-text contrast.
UI_CONTRAST = 3.0

# APCA 0.0.98G constants.
APCA_BLACK_THRESHOLD = 0.022
APCA_BLACK_CLAMP = 1.414
APCA_SCALE = 1.14
APCA_LOW_CLIP = 0.1
APCA_OFFSET = 0.027

SOFT_WEIGHT = 0.12
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
	"--surface-gray-2": "var(--surface-white)",
	"--ink-gray-5": "var(--portal-primary-deep)",
}
PROFILE_AVATAR = ".borrower-portal .portal-profile-avatar"
PROFILE_AVATAR_VARIABLES = {
	**AVATAR_VARIABLES,
	"--surface-gray-2": "var(--portal-primary-soft)",
}


def channels(colour):
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
	def linear(part):
		part /= 255
		return part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4

	red, green, blue = (linear(part) for part in rgb)

	return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first, second) -> float:
	high, low = sorted((luminance(first), luminance(second)), reverse=True)

	return (high + 0.05) / (low + 0.05)


def apca_y(rgb) -> float:
	red, green, blue = ((part / 255) ** 2.4 for part in rgb)
	brightness = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue

	if brightness >= APCA_BLACK_THRESHOLD:
		return brightness

	return brightness + (APCA_BLACK_THRESHOLD - brightness) ** APCA_BLACK_CLAMP


def apca(text, background) -> float:
	"""Unsigned APCA Lc, 0 to about 106."""
	text_y, back_y = apca_y(text), apca_y(background)

	if back_y > text_y:
		raw = (back_y**0.56 - text_y**0.57) * APCA_SCALE
		return 0.0 if raw < APCA_LOW_CLIP else (raw - APCA_OFFSET) * 100

	raw = (back_y**0.65 - text_y**0.62) * APCA_SCALE

	return 0.0 if -raw < APCA_LOW_CLIP else -(raw + APCA_OFFSET) * 100


def ink_for(rgb) -> str:
	# APCA, not WCAG: WCAG picks black on saturated mid-tones like #ef6f21 where white reads.
	return to_hex(max((LIGHT_INK, DARK_INK), key=lambda ink: apca(ink, rgb)))


def shade(rgb, amount: float) -> str:
	return to_hex(part * (1 - amount) for part in rgb)


def relight(rgb, target: float):
	"""Scaled on linear channels so the hue holds."""

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
	return to_hex(part * weight + 255 * (1 - weight) for part in rgb)


def deep(rgb, ground, bar=UI_CONTRAST) -> str:
	"""The colour, darkened only as far as needed to reach `bar` contrast on `ground`."""
	if contrast(rgb, ground) >= bar:
		return to_hex(rgb)

	target = (luminance(ground) + 0.05) / bar - 0.05
	darker = channels(to_hex(relight(rgb, target)))

	# Rounding to whole channels can leave it just short of the bar.
	while contrast(darker, ground) < bar:
		darker = channels(shade(darker, 0.02))

	return to_hex(darker)


def progress_tokens(primary) -> dict:
	soft = tint(primary, SOFT_WEIGHT)

	return {
		"--portal-primary-soft": soft,
		"--portal-primary-line": tint(primary, LINE_WEIGHT),
		"--portal-primary-deep": deep(primary, channels(soft)),
	}


def wash_tokens(action) -> dict:
	pressed = tint(action, SOFT_ACTIVE_WEIGHT)

	return {
		"--portal-action-soft": tint(action, SOFT_WEIGHT),
		"--portal-action-soft-hover": tint(action, SOFT_HOVER_WEIGHT),
		"--portal-action-soft-active": pressed,
		"--portal-action-deep": deep(action, channels(pressed), TEXT_CONTRAST),
	}


def header_action(primary, action):
	# A secondary that can't clear 3:1 on the band (HDFC red on navy) takes the band's ink.
	band = channels(tint(primary, SOFT_WEIGHT))
	if contrast(action, band) >= UI_CONTRAST:
		return action

	return channels(ink_for(band))


def button_tokens(prefix, rgb) -> dict:
	return {
		prefix: to_hex(rgb),
		f"{prefix}-hover": shade(rgb, HOVER_SHADE),
		f"{prefix}-active": shade(rgb, ACTIVE_SHADE),
		f"{prefix}-ink": ink_for(rgb),
	}


def brand_tokens(primary_color, secondary_color) -> dict:
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
	"""Wrapped in a div since DOMPurify drops a leading <style>; :root so teleported dialogs see it."""
	tokens = brand_tokens(primary_color, secondary_color)
	if not tokens:
		return ""

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
		rules += [
			f"{HEADER} {SUBTLE_BUTTON_ONLY} {{ background-color: var(--surface-gray-2); color: var(--ink-gray-8); }}",
			f"{HEADER} {SUBTLE_BUTTON_ONLY}:hover {{ background-color: var(--surface-gray-3); }}",
			f"{HEADER} {SUBTLE_BUTTON_ONLY}:active {{ background-color: var(--surface-gray-4); }}",
		]
		rules.append(f"{AVATAR} {{ {declarations(AVATAR_VARIABLES)} }}")
		rules.append(f"{PROFILE_AVATAR} {{ {declarations(PROFILE_AVATAR_VARIABLES)} }}")
		rules += button_rules(HEADER_BUTTON, "--portal-header-action")

	return "<div><style>%s</style></div>" % " ".join(rules)
