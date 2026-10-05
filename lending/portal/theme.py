# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _

PORTAL_PATH = "/borrower-portal"

LIGHT = "light"
DARK = "dark"
SYSTEM = "system"

CHOICES = (LIGHT, DARK, SYSTEM)
SETTING_CHOICES = {"Light": LIGHT, "Dark": DARK, "System": SYSTEM}

# Per-user DefaultValue holding the borrower's own pick; it outranks the site's default.
CHOICE_KEY = "lending_portal_appearance"

# Runs in <head>, before the first paint, so a dark page never flashes light. It checks the
# attribute on each change because the borrower can leave "system" without a reload.
FOLLOW_DEVICE = (
	"<script>(function () {"
	"var root = document.documentElement;"
	'var query = matchMedia("(prefers-color-scheme: dark)");'
	"function apply() {"
	'if (root.dataset.appearance === "system") root.dataset.theme = query.matches ? "dark" : "light";'
	"}"
	'apply(); query.addEventListener("change", apply);'
	"})();</script>"
)

# :root plus an attribute outranks the renderer's own :root and [data-theme="dark"], whatever the order.
SURFACES = (
	"<style>"
	# frappe-ui's quiet text is 4.17:1 on white and the same grey as its placeholder in dark;
	# these clear 4.5:1 (icons 3:1) on the page, the cards and every preset's rail.
	':root:not([data-theme="dark"]) { --ink-gray-5: #666666; }'
	':root[data-theme="dark"] {'
	" --ink-gray-4: #7d7d7d; --ink-gray-5: #9c9c9c; --ink-gray-6: #a6a6a6;"
	# Cards sit a step above the page; tiles a step above the cards.
	" --portal-panel: var(--surface-elevation-1);"
	" --portal-tile: var(--surface-gray-2); --portal-tile-line: var(--outline-gray-2);"
	" --portal-hover-line: var(--outline-gray-5);"
	" }"
	':root:not([data-theme="dark"]) .portal-logo-dark, :root[data-theme="dark"] .portal-logo-light'
	" { display: none !important; }"
	".borrower-portal .portal-pressable:hover {"
	" --portal-panel-line: var(--portal-hover-line, var(--outline-gray-3)); }"
	"</style>"
)

HTML_TAG = re.compile(r"<html\b")
HEAD_TAG = re.compile(r"<head\b[^>]*>")


@frappe.whitelist(methods=["POST"])
def set_appearance(appearance: str) -> str:
	if appearance not in CHOICES:
		frappe.throw(_("Appearance must be light, dark or system."), frappe.ValidationError)

	frappe.defaults.set_user_default(CHOICE_KEY, appearance)

	return appearance


def after_request(response, request):
	"""Studio's app template has a fixed <head>, so the theme goes onto the page here, on the server."""
	if not is_portal_page(request, response):
		return

	html = response.get_data(as_text=True)
	response.set_data(themed(html, appearance()))


def appearance() -> str:
	return borrower_choice() or site_default()


def borrower_choice() -> str | None:
	if frappe.session.user == "Guest":
		return None

	choice = frappe.defaults.get_user_default(CHOICE_KEY)
	return choice if choice in CHOICES else None


def site_default() -> str:
	setting = frappe.db.get_single_value("Lending Settings", "portal_appearance")
	return SETTING_CHOICES.get(setting, SYSTEM)


def themed(html: str, choice: str) -> str:
	"""`data-appearance` keeps the choice itself, so the account menu can tick "System"."""
	head = SURFACES + (FOLLOW_DEVICE if choice == SYSTEM else "")
	html = HEAD_TAG.sub(lambda tag: tag.group(0) + head, html, count=1)

	if choice == SYSTEM:
		return HTML_TAG.sub(f'<html data-appearance="{SYSTEM}"', html, count=1)

	return HTML_TAG.sub(f'<html data-appearance="{choice}" data-theme="{choice}"', html, count=1)


def is_portal_page(request, response) -> bool:
	path = request.path

	return (
		(path == PORTAL_PATH or path.startswith(PORTAL_PATH + "/"))
		and response.status_code == 200
		and response.mimetype == "text/html"
		and not response.direct_passthrough
	)
