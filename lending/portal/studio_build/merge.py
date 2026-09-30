# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Three-way merge of generated pages (baseline, live, new) in which canvas edits always win."""

import json
import os
import re
from contextlib import contextmanager

import frappe

BASELINE_FOLDER = ("portal", "studio_build", "baseline")

# Studio adds these to every slot on load; they are not hand edits.
SLOT_BOOKKEEPING = ("parentBlockId", "slotId")

_RESET = False


@contextmanager
def reset(active=True):
	"""Treat every baseline as missing, so the build inside replaces pages outright."""
	global _RESET

	_RESET, previous = active, _RESET
	try:
		yield
	finally:
		_RESET = previous


def identify(blocks, route):
	"""Stamp a deterministic componentId onto every block of a generated tree."""
	for index, node in enumerate(blocks):
		_identify(node, f"{baseline_key(route)}-{index}")

	return blocks


def merge_blocks(base, live, new):
	"""The tree to save: `new` carried onto `live`, with the canvas's own work kept."""
	return PageMerge().children(base, live, new)


def same(first, second):
	"""Equality that ignores the empties and slot ids the canvas adds on load."""
	return _settled(first) == _settled(second)


def _settled(value):
	if isinstance(value, dict):
		kept = {key: _settled(item) for key, item in value.items() if key not in SLOT_BOOKKEEPING}
		return {key: item for key, item in kept.items() if item not in (None, "", [], {})} or None
	if isinstance(value, list):
		return [_settled(item) for item in value] or None

	return None if value == "" else value


def merge_resources(live, new):
	"""The generator's data sources, plus any the canvas added that it does not know about."""
	generated = {row["resource_name"] for row in new}

	return list(new) + [row for row in live if row.get("resource_name") not in generated]


class PageMerge:
	"""Take the generator's value only where live still equals base."""

	SCALARS = ("componentName", "blockName", "visibilityCondition", "originalElement", "classes")
	MAPS = (
		"componentProps",
		"componentEvents",
		"baseStyles",
		"mobileStyles",
		"tabletStyles",
		"attributes",
	)

	def __init__(self):
		self.kept = []

	def children(self, base, live, new):
		base_by_id = self._by_id(base)
		live_by_id = self._by_id(live)
		new_by_id = self._by_id(new)

		merged = []
		for node in new:
			node_id = node.get("componentId")
			if node_id in live_by_id:
				merged.append(self.node(base_by_id.get(node_id), live_by_id[node_id], node))
			elif node_id not in base_by_id:
				merged.append(node)
			# in base but not live: deleted on the canvas, so not re-added

		self._readd(merged, base_by_id, live, new_by_id)

		return merged

	def node(self, base, live, new):
		base = base or {}
		merged = dict(live)

		for field in self.SCALARS:
			if not same(live.get(field), base.get(field)):
				continue
			if field in new:
				merged[field] = new[field]
			else:
				merged.pop(field, None)

		for field in self.MAPS:
			self._set(merged, live, new, field, self.mapping(base.get(field) or {}, live.get(field) or {}, new.get(field) or {}))

		self._set(
			merged,
			live,
			new,
			"children",
			self.children(base.get("children") or [], live.get("children") or [], new.get("children") or []),
		)
		self._set(
			merged,
			live,
			new,
			"componentSlots",
			self.slots(
				base.get("componentSlots") or {},
				live.get("componentSlots") or {},
				new.get("componentSlots") or {},
			),
		)

		return merged

	@staticmethod
	def _set(merged, live, new, field, value):
		# don't add an empty field neither side had; it would bloat every exported diff
		if value or field in live or field in new:
			merged[field] = value
		else:
			merged.pop(field, None)

	def mapping(self, base, live, new):
		merged = dict(live)

		for key, value in new.items():
			if live.get(key) == base.get(key):
				merged[key] = value

		for key in base:
			if key not in new and live.get(key) == base.get(key):
				merged.pop(key, None)

		return merged

	def slots(self, base, live, new):
		merged = dict(live)

		for name, base_slot in base.items():
			if name in new or name not in live:
				continue
			if same(live[name].get("slotContent"), base_slot.get("slotContent")):
				merged.pop(name)

		for name, slot in new.items():
			live_slot = live.get(name)
			if live_slot is None:
				merged[name] = slot
				continue

			merged[name] = dict(
				live_slot,
				slotContent=self.children(
					(base.get(name) or {}).get("slotContent") or [],
					live_slot.get("slotContent") or [],
					slot.get("slotContent") or [],
				),
			)

		return merged

	def _readd(self, merged, base_by_id, live, new_by_id):
		# keep canvas-added blocks and generator-dropped blocks the canvas has changed
		for index, node in enumerate(live):
			node_id = node.get("componentId")
			if node_id in new_by_id:
				continue
			if node_id in base_by_id and same(node, base_by_id[node_id]):
				continue

			self.kept.append(node_id)
			merged.insert(min(index, len(merged)), node)

	@staticmethod
	def _by_id(blocks):
		return {node.get("componentId"): node for node in blocks if node.get("componentId")}


def read_baseline(key):
	path = _baseline_path(key)
	if _RESET or not os.path.exists(path):
		return None

	with open(path) as source:  # nosemgrep
		return json.load(source)


def write_baseline(key, record):
	# a file, not a doc field, so it survives a site rebuild and shows in diffs
	with open(_baseline_path(key), "w") as target:  # nosemgrep
		json.dump(record, target, indent=1)


def baseline_key(value):
	# routes carry params like /loan/:name, and the result doubles as a filename and id prefix
	return re.sub(r"\W+", "_", value).strip("_").lower() or "index"


def _baseline_path(key):
	folder = frappe.get_app_path("lending", *BASELINE_FOLDER)
	frappe.create_folder(folder)

	return os.path.join(folder, f"{key}.json")


def _identify(node, node_id):
	node["componentId"] = node_id
	_identify_siblings(node.get("children") or [], node_id)

	for name, slot in (node.get("componentSlots") or {}).items():
		content = slot.get("slotContent")
		if isinstance(content, list):
			_identify_siblings(content, f"{node_id}-{frappe.scrub(name)}")


def _identify_siblings(children, parent_id):
	# number per component name, so inserting a different-type sibling does not shift ids
	seen = {}
	for child in children:
		name = frappe.scrub(child.get("componentName") or "block")
		seen[name] = seen.get(name, 0) + 1
		_identify(child, f"{parent_id}-{name}{seen[name]}")
