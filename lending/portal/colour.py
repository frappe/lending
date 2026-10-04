# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

# Colours land inside a <style>, so anything that is not a hex colour must be dropped.
HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.IGNORECASE)

WHITE = (255, 255, 255)
LIGHT_INK = WHITE
DARK_INK = (23, 23, 23)

# APCA 0.0.98G constants.
APCA_BLACK_THRESHOLD = 0.022
APCA_BLACK_CLAMP = 1.414
APCA_SCALE = 1.14
APCA_LOW_CLIP = 0.1
APCA_OFFSET = 0.027

# Rounding to whole channels can leave a colour just short of its bar; step until it clears.
NUDGE = 0.02


def ink_for(rgb) -> str:
	# APCA, not WCAG: WCAG picks black on saturated mid-tones like #ef6f21 where white reads.
	return to_hex(max((LIGHT_INK, DARK_INK), key=lambda ink: apca(ink, rgb)))


def deep(rgb, ground, bar) -> str:
	"""The colour, darkened only as far as needed to reach `bar` contrast on `ground`."""
	if contrast(rgb, ground) >= bar:
		return to_hex(rgb)

	target = (luminance(ground) + 0.05) / bar - 0.05
	darker = channels(to_hex(relight(rgb, target)))

	while contrast(darker, ground) < bar:
		darker = channels(shade(darker, NUDGE))

	return to_hex(darker)


def lift(rgb, ground, bar) -> str:
	"""The colour, lightened only as far as needed to reach `bar` contrast on a dark `ground`."""
	if contrast(rgb, ground) >= bar:
		return to_hex(rgb)

	target = min(1.0, bar * (luminance(ground) + 0.05) - 0.05)
	lighter = channels(to_hex(relight(rgb, target)))

	# A saturated channel clips at 255 and falls short; mixing in white makes up the rest.
	while contrast(lighter, ground) < bar:
		lighter = channels(mix(lighter, WHITE, 1 - NUDGE))

	return to_hex(lighter)


def under(ink: str, rgb, bar) -> str:
	"""The fill, moved only as far as needed for `ink` to reach `bar` on it."""
	label = channels(ink)
	move = lift if luminance(label) < 0.5 else deep

	return move(rgb, label, bar)


def mix(rgb, ground, weight: float) -> str:
	"""`weight` of the colour over the rest of `ground`."""
	return to_hex(part * weight + base * (1 - weight) for part, base in zip(rgb, ground, strict=True))


def shade(rgb, amount: float) -> str:
	return to_hex(part * (1 - amount) for part in rgb)


def relight(rgb, target: float):
	"""Scaled on linear channels so the hue holds."""

	def encode(part):
		part = max(0.0, min(1.0, part))
		return 255 * (part * 12.92 if part <= 0.0031308 else 1.055 * part ** (1 / 2.4) - 0.055)

	current = luminance(rgb)
	scale = target / current if current else 0

	return tuple(encode(linear(part) * scale) for part in rgb)


def contrast(first, second) -> float:
	high, low = sorted((luminance(first), luminance(second)), reverse=True)

	return (high + 0.05) / (low + 0.05)


def luminance(rgb) -> float:
	red, green, blue = (linear(part) for part in rgb)

	return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def apca(text, background) -> float:
	"""Unsigned APCA Lc, 0 to about 106."""
	text_y, back_y = apca_y(text), apca_y(background)

	if back_y > text_y:
		raw = (back_y**0.56 - text_y**0.57) * APCA_SCALE
		return 0.0 if raw < APCA_LOW_CLIP else (raw - APCA_OFFSET) * 100

	raw = (back_y**0.65 - text_y**0.62) * APCA_SCALE

	return 0.0 if -raw < APCA_LOW_CLIP else -(raw + APCA_OFFSET) * 100


def apca_y(rgb) -> float:
	red, green, blue = ((part / 255) ** 2.4 for part in rgb)
	brightness = 0.2126729 * red + 0.7151522 * green + 0.0721750 * blue

	if brightness >= APCA_BLACK_THRESHOLD:
		return brightness

	return brightness + (APCA_BLACK_THRESHOLD - brightness) ** APCA_BLACK_CLAMP


def linear(part) -> float:
	part /= 255
	return part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4


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
