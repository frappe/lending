# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Creating the Studio App, its pages and its components.

Studio owns the export. A Studio App and every page under it are saved with
`is_standard` and `frappe_app = lending`, and Studio's own exporters write them to
lending/studio/borrower_portal/ on each save -- the app JSON, one folder per page
holding its JSON and its `setup()` module, and the shared components beside them.
Nothing in this package writes those files.

The route is `borrower-portal`, not `borrower`. The Builder pages still answer on
/borrower/*, /apply and /track, and this migration does not take anything away from
them: the two portals run side by side until whoever owns the cutover says otherwise,
and a cutover is then a rename of one field.
"""

import json
import os

import frappe

from lending.portal.studio_build import merge

APP_NAME = "borrower-portal"
APP_TITLE = "Borrower Portal"
FRAPPE_APP = "lending"

# What a Studio Page Resource row carries. Read off an existing page so a data source
# added on the canvas comes back intact after a merge.
RESOURCE_FIELDS = (
	"resource_type",
	"resource_name",
	"url",
	"method",
	"params",
	"auto",
	"document_type",
	"document_name",
	"fields",
	"filters",
	"limit",
	"sort_field",
	"sort_order",
	"transform",
	"whitelisted_methods",
	"fetch_document_using_filters",
	"on_success",
	"on_error",
)

# The file every page's `setup()` module imports. Written here rather than through
# Studio, which exports documents and knows nothing about the app's own source tree.
SHARED_UTILS_PATH = ("utils", "portal.ts")
SHARED_UTILS = '''// Shared by every page's setup() module, as "@app/utils/portal".

import { onScopeDispose, ref, watch } from "vue"
import { call } from "frappe-ui"

const TONES: Record<string, string> = { info: "blue", ok: "green", warn: "orange", danger: "red" }

/** A payload tone -- "", "info", "ok", "warn", "danger" -- as a frappe-ui Badge theme. */
export function tone(value?: string): string {
\treturn TONES[value || ""] || "gray"
}

// A portal URL from the data layer as this app's own route.
//
// Every endpoint answers with the Builder portal's paths -- "/borrower/loan/L-0001" --
// because the Builder pages still serve them. The data layer is shared and is not
// forked for this app, so the prefix comes off here instead.
//
// Line comments rather than a JSDoc block: a continuation line of one begins with a
// space, and pycodestyle takes the first space-indented line in a file as its indent
// character -- after which every tab in this tab-indented module reads as E117.
export function appRoute(url?: string): string {
\tif (!url) return ""
\treturn url.replace(/^\\/borrower(-portal)?/, "") || "/overview"
}

// Ends the session and lands on the apply page, the one page a guest can use.
//
// A full load rather than router.push: the session and its CSRF token are gone, and
// every page already open would otherwise keep what it read as the borrower.
export async function logout(router: any) {
\tawait call("logout")
\twindow.location.href = router.resolve("/apply").href
}

const FIND_URL = "/api/method/lending.portal.search.find"

// The command palette behind Ctrl+K, as the desk's own awesomebar opens: the same
// shortcut on every page, arrows to move, Enter to go. The dialog is the shell's
// borrower_search component; everything it reads is returned from here.
//
// The results are fetched here rather than through a page data source. A source
// re-fetches the moment its parameters change, with nothing to hold it back while the
// borrower is still typing, and every page would have to declare one. `asked` drops an
// answer that arrives after a newer question was sent.
//
// A GET, because find() reads and changes nothing.
export function useSearch(open: (url?: string) => void) {
\tconst showSearch = ref(false)
\tconst searchText = ref("")
\tconst searchResults = ref<any[]>([])
\tconst searchNote = ref("")
\tconst searchIndex = ref(0)
\tlet asked = 0
\tlet timer: ReturnType<typeof setTimeout> | undefined

\tasync function find(query: string) {
\t\tconst ticket = ++asked
\t\tconst response = await fetch(`${FIND_URL}?q=${encodeURIComponent(query)}`, {
\t\t\theaders: { Accept: "application/json" },
\t\t})
\t\tif (ticket !== asked || !response.ok) return

\t\tconst { message } = await response.json()
\t\tsearchResults.value = message.results
\t\tsearchNote.value = message.note
\t\tsearchIndex.value = 0
\t}

\twatch(searchText, (query) => {
\t\tclearTimeout(timer)
\t\ttimer = setTimeout(() => find(query.trim()), 150)
\t})

\t// Every opening starts from an empty box, which answers with the portal's own pages.
\twatch(showSearch, (shown) => {
\t\tif (!shown) return
\t\tsearchText.value = ""
\t\tfind("")
\t})

\tfunction chooseResult(item?: { url?: string }) {
\t\tif (!item) return
\t\tshowSearch.value = false
\t\topen(item.url)
\t}

\tfunction move(step: number) {
\t\tconst count = searchResults.value.length
\t\tif (count) searchIndex.value = (searchIndex.value + step + count) % count
\t}

\tfunction onKeydown(event: KeyboardEvent) {
\t\tif ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
\t\t\tevent.preventDefault()
\t\t\tshowSearch.value = !showSearch.value
\t\t\treturn
\t\t}
\t\tif (!showSearch.value || event.isComposing) return

\t\tif (event.key === "ArrowDown" || event.key === "ArrowUp") {
\t\t\tevent.preventDefault()
\t\t\tmove(event.key === "ArrowDown" ? 1 : -1)
\t\t} else if (event.key === "Enter") {
\t\t\tevent.preventDefault()
\t\t\tchooseResult(searchResults.value[searchIndex.value])
\t\t}
\t}

\t// Studio's editor has a Ctrl+K of its own, and runs a page's setup() on its canvas.
\tif (!window.location.pathname.startsWith("/studio")) {
\t\twindow.addEventListener("keydown", onKeydown)
\t}
\tonScopeDispose(() => {
\t\twindow.removeEventListener("keydown", onKeydown)
\t\tclearTimeout(timer)
\t})

\treturn { showSearch, searchText, searchResults, searchNote, searchIndex, chooseResult }
}
'''

# A page's `setup()` module. An exported Studio app keeps its state in code rather than
# in Studio Page Variables, so this is where a page's refs and handlers live, and
# whatever it returns is what the page's blocks can bind to and its events can write.
#
# Every page returns the six the frame itself reads: the tone helper its badges take
# their colour from, the one way a row opens the record it stands for, the sign-out
# behind the account menu, the two pieces of state behind the bell, and whether the
# sidebar is shut. They are here rather than in
# the header component because a Studio Component holds blocks and no state of its own.
#
# `sidebarCollapsed` starts as null rather than false: that is Sidebar's own reading of
# "nobody has said yet", under which it collapses on mobile and not otherwise. It is
# bound out of the Sidebar as a v-model so the blocks in the rail can read it as well --
# a block cannot inject what frappe-ui's own sidebar parts inject. See shell.EXPANDED.
#
# A framed page also spreads in useSearch, which is the Ctrl+K palette the frame draws.
SCRIPT_TEMPLATE = '''import {{ computed, ref, watch }} from "vue"
import {{ call, toast }} from "frappe-ui"
import {{ tone, appRoute, logout as endSession{search_import} }} from "@app/utils/portal"

export default function setup(context: any) {{
\tconst {{ router }} = context
\tconst showAlerts = ref(false)
\tconst alertsTab = ref("attention")
\tconst sidebarCollapsed = ref<boolean | null>(null)
{state}
\tconst open = (url?: string) => {{
\t\tconst to = appRoute(url)
\t\tif (to) router.push(to)
\t}}
\tconst logout = () => endSession(router)
{search}{body}
\treturn {{ tone, open, logout, showAlerts, alertsTab, sidebarCollapsed{search_returns}{returns} }}
}}
'''


def page_script(state=(), body="", returns=(), search=True):
	"""One page's setup() module: the frame's own bindings, plus whatever the page adds.

	`state` is (name, initial value) pairs declared as refs, `body` is extra source
	dropped in before the return, and `returns` names anything in `body` the blocks
	need to reach. `search` is off for the pages that have no frame, and so no palette
	for Ctrl+K to open.
	"""
	declarations = "".join(f'\tconst {name} = ref({initial})\n' for name, initial in state)
	extra = ", ".join(name for name, _initial in state) + (", " if state and returns else "")

	return SCRIPT_TEMPLATE.format(
		state=declarations,
		search_import=", useSearch" if search else "",
		search="\tconst search = useSearch(open)\n" if search else "",
		search_returns=", ...search" if search else "",
		body=f"\n{body}\n" if body else "",
		returns=f", {extra}{', '.join(returns)}" if (state or returns) else "",
	)


PAGE_SCRIPT = page_script()


def api_resource(name, method, params=None, auto=1):
	"""A page's data source: one whitelisted endpoint, called as the page loads.

	The endpoints are the portal's own, unchanged. That is the whole reason this
	migration is a re-layout rather than a rewrite: `lending.portal.*` already answers
	with formatted, translated payloads through @frappe.whitelist, so a Studio page
	reads exactly what a Builder data script read.
	"""
	return {
		"resource_type": "API Resource",
		"resource_name": name,
		"url": method,
		"method": "GET",
		"auto": auto,
		"params": json.dumps(params) if params else None,
	}


def upsert_app():
	"""Create or update the Studio App. Safe to re-run."""
	fields = {
		"app_name": APP_NAME,
		"app_title": APP_TITLE,
		"route": APP_NAME,
		"is_standard": 1,
		"frappe_app": FRAPPE_APP,
	}

	if frappe.db.exists("Studio App", APP_NAME):
		doc = frappe.get_doc("Studio App", APP_NAME)
		doc.update(fields)
		doc.save()
		action = "updated"
	else:
		doc = frappe.get_doc(dict(doctype="Studio App", name=APP_NAME, **fields)).insert()
		action = "created"

	write_shared_utils()
	print(f"{action} Studio App {doc.name} at /{APP_NAME}")

	return doc.name


def write_shared_utils():
	"""Put utils/portal.ts in the exported app folder, creating the folder if Studio has not.

	Left alone once it has been edited by hand. It is generated, but it is still source
	somebody may have reached for, and a rebuild is not a reason to lose what they wrote
	there. A text file has no ids to merge on, so this is the whole file or none of it.

	Until it has a baseline, though, there is nothing to read an edit against, and the
	run that gives it one writes it -- as _replace_page does, and for the same reason.
	"""
	folder = frappe.get_app_source_path(FRAPPE_APP, "studio", APP_NAME, SHARED_UTILS_PATH[0])
	frappe.create_folder(folder)
	path = os.path.join(folder, SHARED_UTILS_PATH[1])
	key = f"file-{merge.baseline_key(SHARED_UTILS_PATH[1])}"

	baseline = merge.read_baseline(key)
	if baseline is not None and os.path.exists(path):
		current = frappe.read_file(path)
		if current not in (SHARED_UTILS, baseline.get("source")):
			print(f"kept the hand-edited {SHARED_UTILS_PATH[1]}")
			return

	with open(path, "w") as source:
		source.write(SHARED_UTILS)

	merge.write_baseline(key, {"path": path, "source": SHARED_UTILS})


def upsert_component(component_id, component_name, tree, inputs=()):
	"""Create one shared piece of the frame, or merge this build into the one already there.

	Merged the same way a page is, and for the same reason: the header and the sidebar
	are as much a thing to restyle on the canvas as any page is.

	An unchanged component is left alone: saving one publishes a document change to
	every open editor, and eleven pages built in a row would do it eleven times over.
	"""
	tree = merge.identify([tree], component_id)[0]
	key = f"component-{merge.baseline_key(component_id)}"
	fields = {
		"component_name": component_name,
		"component_id": component_id,
		"inputs": [{"input_name": name, "type": "string", "description": note} for name, note in inputs],
	}

	if not frappe.db.exists("Studio Component", component_id):
		doc = frappe.get_doc(dict(doctype="Studio Component", block=json.dumps(tree, indent=1), **fields))
		doc.insert()
		merge.write_baseline(key, {"component_id": component_id, "block": tree})
		print(f"created Studio Component {doc.name}")
		return doc.name

	doc = frappe.get_doc("Studio Component", component_id)
	live = frappe.parse_json(doc.block or "{}")
	baseline = merge.read_baseline(key)

	if baseline is None:
		# No third tree to merge against, so this one run still replaces -- see _replace_page.
		merged = [tree]
	else:
		merged = merge.merge_blocks([baseline["block"]], [live], [tree])

	fields["block"] = json.dumps(merged[0] if merged else live, indent=1)
	merge.write_baseline(key, {"component_id": component_id, "block": tree})

	if doc.block == fields["block"]:
		return doc.name

	doc.update(fields)
	doc.save()
	print(f"{'replaced' if baseline is None else 'merged into'} Studio Component {doc.name}")

	return doc.name


def upsert_page(title, route, blocks, resources, script=PAGE_SCRIPT, allow_guest=False):
	"""Create one page of the app, or merge this build into the page already there.

	Found by the route it answers on. Not by name: Studio names a page `page-<hash>` and
	frappe clears any name handed to an insert before naming runs, so there is no name to
	look a page up by that this module could choose. The route is the page's real identity
	anyway -- it is what a borrower reaches it at, and what Studio itself refuses to let
	two pages share.

	The exported folder is named after the title, so a retitle relocates it. Studio
	handles that move; what it cannot handle is two pages built for one route, which is
	why this looks the route up rather than trusting a name.

	An existing page is never replaced. What this build produces is merged onto what is
	on the canvas and the canvas wins every disagreement, so a rebuild carries a change
	into a page without taking a hand edit out of it -- see the merge module.
	"""
	blocks = merge.identify(blocks, route)
	fields = {
		"page_title": title,
		"route": route,
		"studio_app": APP_NAME,
		"published": 1,
		"allow_guest": 1 if allow_guest else 0,
		"is_standard": 1,
		"frappe_app": FRAPPE_APP,
		"resources": resources,
	}

	existing = frappe.db.get_value("Studio Page", {"studio_app": APP_NAME, "route": route}, "name")
	if not existing:
		return _create_page(route, blocks, script, fields)

	doc = frappe.get_doc("Studio Page", existing)
	baseline = merge.read_baseline(merge.baseline_key(route))
	if baseline is None:
		return _replace_page(doc, route, blocks, script, fields)

	return _merge_page(doc, route, blocks, script, fields, baseline)


def _create_page(route, blocks, script, fields):
	"""A page nobody has opened yet: write it, and record it as the base of the next merge."""
	doc = frappe.get_doc(
		dict(doctype="Studio Page", blocks=frappe.as_json(blocks), script=script, **fields)
	).insert()

	# The script lives in the page's companion .ts once the page is exported, and the
	# DB field is cleared. Writing it has to come after the save that created the folder.
	doc.write_script_file()
	_save_baseline(route, blocks, script)

	frappe.clear_document_cache("Studio Page", doc.name)
	print(f"created Studio Page {doc.name} at /{APP_NAME}{route}")

	return doc.name


def _merge_page(doc, route, blocks, script, fields, baseline):
	"""Carry this build into a page that is already laid out, keeping every hand edit."""
	base = baseline.get("blocks") or []
	live = frappe.parse_json(doc.blocks or "[]")
	fields["blocks"] = frappe.as_json(merge.merge_blocks(base, live, blocks))

	# The canvas keeps unpublished work in draft_blocks and the published page in blocks,
	# and loads the draft in preference to the page. Both are merged against the same
	# baseline, so neither reading of the page loses what was drawn on it.
	if doc.draft_blocks and doc.draft_blocks != "[]":
		draft = frappe.parse_json(doc.draft_blocks)
		fields["draft_blocks"] = frappe.as_json(merge.merge_blocks(base, draft, blocks))

	# The script is a file the canvas can edit too, and a text file has no ids to merge
	# on. Rewrite it only while it still reads as the generator left it.
	live_script = _page_script(doc)
	rewrite_script = live_script in (None, "", baseline.get("script"))
	if rewrite_script:
		fields["script"] = script

	live_resources = _resource_rows(doc)
	resources = fields.pop("resources")
	doc.resources = []
	doc.update(fields)
	for row in merge.merge_resources(live_resources, resources):
		doc.append("resources", row)
	doc.save()

	if rewrite_script:
		doc.write_script_file()
	else:
		print(f"kept the hand-edited script for /{APP_NAME}{route}")

	_save_baseline(route, blocks, script if rewrite_script else live_script)
	frappe.clear_document_cache("Studio Page", doc.name)
	print(f"merged into Studio Page {doc.name} at /{APP_NAME}{route}")

	return doc.name


def _replace_page(doc, route, blocks, script, fields):
	"""The one run that still overwrites: a page built before there was a baseline.

	A merge needs three trees and such a page has two, and the third cannot be guessed,
	because of what the ids are made of. A block's `componentId` is stamped from its
	position, so a baseline of what this build *would* have written describes the shape
	of the new tree and not the shape of the page. Nothing on the page matches it, every
	block there reads as hand-added and is kept, and the rebuild stacks the new page on
	top of the old one -- two of every card, in one card's worth of space.

	Reading the page itself as the baseline lines the ids up but says the same thing this
	does, only more quietly: whatever is on the canvas is the generator's to overwrite.
	Better to overwrite it once, in the open, exactly as every run before the merge
	existed did. The page and its baseline are then the same tree, which is what makes
	the next run, and every run after it, a merge that keeps hand edits.
	"""
	fields["blocks"] = frappe.as_json(blocks)
	fields["script"] = script
	# A leftover draft outranks what this just wrote: the canvas loads draft_blocks when
	# it has one, and so does the published page's preview.
	fields["draft_blocks"] = None

	doc.resources = []
	doc.update(fields)
	doc.save()
	doc.write_script_file()

	_save_baseline(route, blocks, script)
	frappe.clear_document_cache("Studio Page", doc.name)
	print(f"replaced /{APP_NAME}{route} -- it had no baseline, and now has one")

	return doc.name


def _save_baseline(route, blocks, script):
	merge.write_baseline(merge.baseline_key(route), {"route": route, "blocks": blocks, "script": script})


def _page_script(doc):
	"""The page's script, from its companion .ts once exported and from the field before that."""
	if doc.has_script_file():
		return frappe.read_file(doc.get_script_file_path())

	return doc.script


def _resource_rows(doc):
	"""The page's data sources as plain rows, ready to append back after a merge."""
	return [
		{field: row.get(field) for field in RESOURCE_FIELDS if row.get(field) is not None}
		for row in doc.resources
	]
