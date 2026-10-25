# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BorrowerKYC(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		customer: DF.Link
		customer_name: DF.Data | None
		date_of_birth: DF.Date | None
		kyc_address: DF.SmallText | None
		kyc_reference: DF.Data | None
		kyc_request_id: DF.Data | None
		kyc_status: DF.Literal["", "Pending", "Verified", "Rejected"]
		kyc_verified_on: DF.Datetime | None
		name_as_per_kyc: DF.Data | None
		name_on_pan: DF.Data | None
		pan: DF.Data | None
		pan_reference: DF.Data | None
		pan_verified_on: DF.Datetime | None
	# end: auto-generated types

	@property
	def pan_verified(self) -> bool:
		return bool(self.pan_verified_on)

	@property
	def kyc_verified(self) -> bool:
		return self.kyc_status == "Verified"
