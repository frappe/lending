# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
import os

import frappe

from lending.portal.studio_build import merge

APP_NAME = "borrower-portal"
APP_TITLE = "Borrower Portal"
FRAPPE_APP = "lending"

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

# Written here because Studio exports documents only, not the app's own source files.
SHARED_UTILS_PATH = ("utils", "portal.ts")
SHARED_UTILS = '''import { onScopeDispose, ref, watch } from "vue"
import { call } from "frappe-ui"

const TONES: Record<string, string> = { info: "blue", ok: "green", warn: "orange", danger: "red" }

export function tone(value?: string): string {
\treturn TONES[value || ""] || "gray"
}

// The shared endpoints still return /borrower/* paths, so the prefix comes off here.
export function appRoute(url?: string): string {
\tif (!url) return ""
\treturn url.replace(/^\\/borrower(-portal)?/, "") || "/overview"
}

// A full load, not router.push: open pages would keep what they read before logout.
export async function logout(router: any) {
\tawait call("logout")
\twindow.location.href = router.resolve("/apply").href
}

const FIND_URL = "/api/method/lending.portal.search.find"

// Not a page data source: that refetches on every keystroke; `asked` drops stale answers.
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

# Every page returns the frame's bindings here, since a Studio Component holds no state.
# sidebarCollapsed starts null, Sidebar's "unset" value that auto-collapses on mobile.
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
	"""A page's setup() module; `state` is (name, initial) ref pairs, `returns` names from `body`."""
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
	return {
		"resource_type": "API Resource",
		"resource_name": name,
		"url": method,
		"method": "GET",
		"auto": auto,
		"params": json.dumps(params) if params else None,
	}


def upsert_app():
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
	"""Write utils/portal.ts unless it was hand-edited since the last baseline."""
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
	"""Create a frame component or merge onto it; unchanged ones are not saved, to spare open editors."""
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
	"""Create a page or merge onto it, looked up by route since Studio discards a chosen name."""
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
	doc = frappe.get_doc(
		dict(doctype="Studio Page", blocks=frappe.as_json(blocks), script=script, **fields)
	).insert()

	# must follow the insert, which creates the export folder the .ts lives in
	doc.write_script_file()
	_save_baseline(route, blocks, script)

	frappe.clear_document_cache("Studio Page", doc.name)
	print(f"created Studio Page {doc.name} at /{APP_NAME}{route}")

	return doc.name


def _merge_page(doc, route, blocks, script, fields, baseline):
	base = baseline.get("blocks") or []
	live = frappe.parse_json(doc.blocks or "[]")
	fields["blocks"] = frappe.as_json(merge.merge_blocks(base, live, blocks))

	# the canvas loads draft_blocks over blocks, so the draft needs the same merge
	if doc.draft_blocks and doc.draft_blocks != "[]":
		draft = frappe.parse_json(doc.draft_blocks)
		fields["draft_blocks"] = frappe.as_json(merge.merge_blocks(base, draft, blocks))

	# no ids to merge a script on, so rewrite it only if untouched since the baseline
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
	# Without a baseline the live ids can't be matched, so a merge would duplicate every block.
	fields["blocks"] = frappe.as_json(blocks)
	fields["script"] = script
	# a leftover draft would be loaded over the blocks just written
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
	if doc.has_script_file():
		return frappe.read_file(doc.get_script_file_path())

	return doc.script


def _resource_rows(doc):
	return [
		{field: row.get(field) for field in RESOURCE_FIELDS if row.get(field) is not None}
		for row in doc.resources
	]
