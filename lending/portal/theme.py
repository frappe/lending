# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe

PORTAL_PATH = "/borrower-portal"

LIGHT = "light"
DARK = "dark"
SYSTEM = "system"

# Borrower's choice follows the device until a borrower can pick one.
APPEARANCES = {"Light": LIGHT, "Dark": DARK, "Borrower's choice": SYSTEM}

# Runs in <head>, before the first paint, so a dark page never flashes light.
FOLLOW_DEVICE = (
	"<script>(function () {"
	'var query = matchMedia("(prefers-color-scheme: dark)");'
	'function apply() { document.documentElement.dataset.theme = query.matches ? "dark" : "light"; }'
	'apply(); query.addEventListener("change", apply);'
	"})();</script>"
)

HTML_TAG = re.compile(r"<html\b")
HEAD_TAG = re.compile(r"<head\b[^>]*>")


def after_request(response, request):
	"""Studio's app template has a fixed <head>, so the theme goes onto the page here, on the server."""
	if not is_portal_page(request, response):
		return

	html = response.get_data(as_text=True)
	response.set_data(themed(html, appearance()))


def appearance() -> str:
	setting = frappe.db.get_single_value("Lending Settings", "portal_appearance")
	return APPEARANCES.get(setting, LIGHT)


def themed(html: str, mode: str) -> str:
	if mode == SYSTEM:
		return HEAD_TAG.sub(lambda tag: tag.group(0) + FOLLOW_DEVICE, html, count=1)

	return HTML_TAG.sub(f'<html data-theme="{mode}"', html, count=1)


def is_portal_page(request, response) -> bool:
	path = request.path

	return (
		(path == PORTAL_PATH or path.startswith(PORTAL_PATH + "/"))
		and response.status_code == 200
		and response.mimetype == "text/html"
		and not response.direct_passthrough
	)
