# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The borrower portal, built again as a Frappe Studio app.

Run the whole thing once with

	bench --site <site> execute lending.portal.studio_build.build

and then, so the app has a bundle to serve rather than only a definition,

	bench --site <site> execute lending.portal.studio_build.bundle

after which the portal answers at /borrower-portal/overview. Until the bundle exists the
route falls back to Studio's own renderer, which serves the pages from the editor's
assets -- fine for a look, not for a borrower.

What this package is
--------------------
The portal was first built on Frappe Builder. This package lays the same portal out as
Studio pages, against the same endpoints -- `lending.portal.*`, unchanged -- so the
move was a re-layout rather than a rewrite: what changed is the thing that draws the
payload, not the thing that produces it.

The Builder portal is not on this branch. It lives on feature/borrower-portal, where it
still answers on /borrower/*, /apply and /track; here there is one portal, and it is
this one.

What moved, and what it became
------------------------------
	Builder                                Studio
	a styled span with a data-tone         a frappe-ui Badge
	a grid of divs with column widths      the List family
	an <input> and a client script         FormControl over a page-script ref
	a hand-built tab strip                 TabButtons and a ref
	seven panels and a display toggle      a `step` ref and visibility conditions
	one component wrapped round a page     three components beside the content
	a Python data script in safe_exec      an API Resource on the same endpoint
	the shared client script               each page's setup() module

The one thing that did not survive the move is the portal's own design system: some
thirty CSS custom properties driven by Lending Settings, and the inline styles on every
block. The Studio pages take frappe-ui's own appearance instead, which is the point of
asking for components rather than divs -- what is on the canvas now is a component to
restyle rather than a div already painted. The logo and the two colours came back
afterwards, read per request -- see lending.portal.brand; radius and font are not
wired in.

Where the work is
-----------------
`blocks` is the vocabulary, `app` creates the documents, `shell` is the frame, and one
module per page after that. Studio's own exporters write everything to
lending/studio/borrower_portal/ as it is saved.
"""

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
	"""Create or update the whole app: the frame first, then every page.

	Safe to re-run, and it has to be re-run as a whole: the pages share the frame's
	components, so a change to one of those reaches a page only when its own blocks
	are rebuilt around it.

	Re-running does not cost anything laid out by hand. A page that already exists is
	merged rather than replaced, and the canvas wins every disagreement -- see the merge
	module for the rule and for what a rebuild is still allowed to change.

	The first run against a page built before the merge existed is the exception, and it
	says so as it goes: that page has no baseline to merge against, so it is replaced
	once and gains one. Read what the build prints.

	`reset` says to do that for every page, whatever baselines are on disk: overwrite the
	app with what the generator makes of it and record that as the new baseline. It
	throws away every hand edit, which is the point of it. Reach for it when a rebuild
	has left a page holding two of something -- a card's old shape beside its new one --
	which is what a merge does when it cannot tell the two apart.
	"""
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
	"""Build the app's frontend bundle, which is what the published route serves.

	Studio rebuilds this itself on migrate for its own apps; an app exported into
	another Frappe app is built when somebody asks, so this is the asking.
	"""
	import frappe

	result = frappe.get_doc("Studio App", app.APP_NAME).generate_app_build()
	if error := result.get("build_error"):
		print(f"build failed -- see Error Log {error.get('error_log')}")
	else:
		print(f"built the bundle for {app.APP_NAME}")

	return result
