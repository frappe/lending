# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PledgedArticle(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		article_kind: DF.Data | None
		deduction_details: DF.SmallText | None
		deduction_weight: DF.Float
		defects: DF.SmallText | None
		description: DF.Data | None
		fineness: DF.Int
		gold_article: DF.Link
		gross_weight: DF.Float
		image: DF.AttachImage | None
		loan_security: DF.Link | None
		metal: DF.Data | None
		net_weight: DF.Float
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pieces: DF.Int
		qty: DF.Float
		released_or_sold_in: DF.DynamicLink | None
		released_or_sold_in_type: DF.Link | None
		status: DF.Literal["", "Pledged", "Released", "Sold"]
	# end: auto-generated types

	pass
