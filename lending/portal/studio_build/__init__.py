# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Borrower portal as a Studio app: run `build`, then `bundle`, via bench execute."""

from lending.portal.studio_build import (
	accounts_page,
	app,
	application_pages,
	apply_page,
	loan_pages,
	merge,
	new_application_page,
	overview_page,
	profile_page,
	shell,
	statement_pages,
	track_page,
)


def build(reset=False):
	"""Rebuild the frame and every page, merging onto canvas edits; `reset` discards them all."""
	with merge.reset(reset):
		app.upsert_app()
		shell.upsert_frame()

		pages = [
			overview_page.build(),
			accounts_page.build(),
			*loan_pages.build(),
			*application_pages.build(),
			new_application_page.build(),
			*statement_pages.build(),
			profile_page.build(),
			apply_page.build(),
			track_page.build(),
		]

	print(f"built {len(pages)} Studio pages under /{app.APP_NAME}")

	return pages


def bundle():
	"""Build the frontend bundle; Studio does not do this on migrate for an exported app."""
	import frappe

	result = frappe.get_doc("Studio App", app.APP_NAME).generate_app_build()
	if error := result.get("build_error"):
		print(f"build failed -- see Error Log {error.get('error_log')}")
	else:
		print(f"built the bundle for {app.APP_NAME}")

	return result
