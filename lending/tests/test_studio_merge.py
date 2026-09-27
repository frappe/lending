# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from lending.portal.studio_build.blocks import block
from lending.portal.studio_build.merge import identify, merge_blocks, merge_resources


class TestStudioMerge(IntegrationTestCase):
	def test_ids_are_the_same_on_every_run(self):
		first = identify([self.generated()], "/overview")
		second = identify([self.generated()], "/overview")

		self.assertEqual(self.ids(first), self.ids(second))
		self.assertEqual(first[0]["componentId"], "overview-0")

	def test_ids_do_not_move_when_another_component_is_added_beside_them(self):
		before = self.ids(identify([self.generated()], "/overview"))

		grown = self.generated()
		grown["children"].insert(0, block("Badge", {"label": "New"}))
		after = self.ids(identify([grown], "/overview"))

		self.assertTrue(set(before) <= set(after))

	def test_a_hand_edited_prop_survives_a_rebuild(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))
		live[0]["children"][0]["componentProps"]["label"] = "Renamed by hand"

		new = identify([self.generated(title="Generator's new title")], "/overview")
		merged = merge_blocks(base, live, new)

		self.assertEqual(merged[0]["children"][0]["componentProps"]["label"], "Renamed by hand")

	def test_an_untouched_prop_takes_the_new_value(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))

		new = identify([self.generated(title="Generator's new title")], "/overview")
		merged = merge_blocks(base, live, new)

		self.assertEqual(merged[0]["children"][0]["componentProps"]["label"], "Generator's new title")

	def test_a_hand_added_block_survives_a_rebuild(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))
		live[0]["children"].append(block("Badge", {"label": "Mine"}, componentId="hand-added"))

		merged = merge_blocks(base, live, identify([self.generated()], "/overview"))

		self.assertIn("hand-added", self.ids(merged))

	def test_a_hand_edited_block_survives_the_generator_dropping_it(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))
		live[0]["children"][0]["componentProps"]["label"] = "Kept"

		emptied = identify([block("container", children=[])], "/overview")
		merged = merge_blocks(base, live, emptied)

		self.assertEqual(merged[0]["children"][0]["componentProps"]["label"], "Kept")

	def test_the_generator_may_drop_a_block_nobody_touched(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))

		emptied = identify([block("container", children=[])], "/overview")
		merged = merge_blocks(base, live, emptied)

		self.assertEqual(merged[0]["children"], [])

	def test_a_page_studio_has_only_normalised_is_not_hand_edited(self):
		"""Studio saves an untouched block with None for {} and its own `classes: []`."""
		base = identify([self.with_slot(), self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))
		for node in self.nodes(live):
			node.update(componentProps=node["componentProps"] or None, componentEvents=None, classes=[])
			for name, slot in node["componentSlots"].items():
				slot.update(parentBlockId=node["componentId"], slotId=f"{node['componentId']}:{name}")

		new = identify([self.with_slot(), block("container", classes=["hover:border-outline-gray-3"])], "/overview")
		merged = merge_blocks(base, live, new)

		self.assertEqual(self.ids(merged), self.ids(new))
		self.assertEqual(merged[1]["classes"], ["hover:border-outline-gray-3"])

	def test_a_hand_edited_style_survives_a_rebuild(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))
		live[0]["baseStyles"]["backgroundColor"] = "pink"

		new = identify([self.generated()], "/overview")
		new[0]["baseStyles"]["gap"] = "2rem"
		merged = merge_blocks(base, live, new)

		self.assertEqual(merged[0]["baseStyles"]["backgroundColor"], "pink")
		self.assertEqual(merged[0]["baseStyles"]["gap"], "2rem")

	def test_a_block_deleted_by_hand_is_not_put_back(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))
		live[0]["children"] = []

		merged = merge_blocks(base, live, identify([self.generated()], "/overview"))

		self.assertEqual(merged[0]["children"], [])

	def test_a_hand_added_data_source_survives_a_rebuild(self):
		live = [{"resource_name": "overview", "url": "old"}, {"resource_name": "mine", "url": "custom"}]
		new = [{"resource_name": "overview", "url": "new"}]

		merged = merge_resources(live, new)

		self.assertEqual({row["resource_name"]: row["url"] for row in merged}, {"overview": "new", "mine": "custom"})

	def test_a_hand_edited_slot_survives_a_rebuild(self):
		base = identify([self.with_slot()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))
		live[0]["componentSlots"]["default"]["slotContent"][0]["componentProps"]["label"] = "Kept"

		merged = merge_blocks(base, live, identify([self.with_slot()], "/overview"))

		self.assertEqual(
			merged[0]["componentSlots"]["default"]["slotContent"][0]["componentProps"]["label"], "Kept"
		)

	def test_a_slot_the_generator_dropped_goes_unless_it_was_edited(self):
		base = identify([self.with_slot()], "/overview")
		new = identify([block("Card")], "/overview")

		untouched = merge_blocks(base, frappe.parse_json(frappe.as_json(base)), new)
		self.assertNotIn("default", untouched[0].get("componentSlots") or {})

		edited = frappe.parse_json(frappe.as_json(base))
		edited[0]["componentSlots"]["default"]["slotContent"][0]["componentProps"]["label"] = "Kept"
		self.assertIn("default", merge_blocks(base, edited, new)[0]["componentSlots"])

	def test_a_page_that_matches_its_baseline_takes_the_rebuild_whole(self):
		base = identify([self.generated()], "/overview")
		live = frappe.parse_json(frappe.as_json(base))

		reshaped = identify([block("container", children=[block("HTML", {"html": "<svg/>"})])], "/overview")
		merged = merge_blocks(base, live, reshaped)

		self.assertEqual(merged, reshaped)

	def test_a_baseline_that_is_not_the_page_strands_the_rebuild(self):
		"""The baseline must be what was written to the page, or the new tree never lands."""
		live = identify([self.generated()], "/overview")
		new = identify([block("container", children=[block("HTML", {"html": "<svg/>"})])], "/overview")

		merged = merge_blocks(new, live, new)

		self.assertEqual(self.ids(merged), self.ids(live))
		self.assertNotIn("overview-0-html1", self.ids(merged))

	@staticmethod
	def generated(title="Overview"):
		return block(
			"container",
			children=[block("TextBlock", {"label": title}), block("Badge", {"label": "Active"})],
			styles={"display": "flex"},
		)

	@staticmethod
	def with_slot():
		return block(
			"Card",
			slots={"default": {"slotName": "default", "slotContent": [block("TextBlock", {"label": "Hi"})]}},
		)

	def nodes(self, blocks):
		for node in blocks:
			yield node
			yield from self.nodes(node.get("children") or [])
			for slot in (node.get("componentSlots") or {}).values():
				yield from self.nodes(slot.get("slotContent") or [])

	def ids(self, blocks):
		found = []
		for node in blocks:
			found.append(node["componentId"])
			found += self.ids(node.get("children") or [])
			for slot in (node.get("componentSlots") or {}).values():
				found += self.ids(slot.get("slotContent") or [])

		return found
