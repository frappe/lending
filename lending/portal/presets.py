# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from typing import NamedTuple

CUSTOM = "Custom"


class Preset(NamedTuple):
	primary: str | None
	secondary: str | None
	dark_primary: str | None = None
	dark_secondary: str | None = None
	# APCA picks white on some dark-mode buttons where white falls short of WCAG 4.5:1.
	dark_ink: str | None = None


# Shades from the frappe-ui palette (tailwind/colors.json); dark values come from its dark ramp,
# which is darker at each step, so they carry different shade names. No red: red means danger.
PRESETS = {
	# blue-800, blue-700 / blue-300, blue-500
	"Ocean": Preset("#005cad", "#0475d3", "#349bef", "#1c6ec4"),
	# blue-800, teal-700 / blue-300, teal-500
	"Navy & Teal": Preset("#005cad", "#10736b", "#349bef", "#1c7169"),
	# green-800, green-700 / green-300, green-400
	"Forest": Preset("#085e35", "#14804d", "#369768", "#128251"),
	# teal-800, orange-700 / teal-400, orange-400
	"Teal & Orange": Preset("#125c57", "#bd3e0c", "#2da094", "#e16915", "#171717"),
	# violet-800, pink-700 / violet-300, pink-500; pink-600 is 4.47:1 under white
	"Royal": Preset("#392980", "#9c2671", "#9175f0", "#ac377d"),
	# purple-800, purple-600 / purple-300, purple-400
	"Plum": Preset("#5c2f83", "#8e49ca", "#b168e8", "#a26fce", "#171717"),
	# violet-800, violet-600 / violet-300, violet-400
	"Indigo": Preset("#392980", "#6e57d1", "#9175f0", "#6c4dd5"),
	# gray-800, blue-700 / gray-300, blue-500
	"Graphite": Preset("#383838", "#0475d3", "#999999", "#1c6ec4"),
}


def resolve(theme, primary_color, secondary_color) -> Preset:
	"""A named preset, or the two colour fields with no dark pair for Custom or no theme."""
	return PRESETS.get(theme) or Preset(primary_color, secondary_color)
