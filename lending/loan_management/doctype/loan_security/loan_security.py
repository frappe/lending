# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class LoanSecurity(Document):
	pass


def update_utilized_loan_securities_value_of_loan(loan, amount, increase=False, decrease=False):
	if (increase and decrease) or (not increase and not decrease):
		frappe.throw(("Utilized loan security value can either be increased or decreased, not both"))

	if not frappe.db.get_value("Loan", loan, "is_secured_loan"):
		return

	loan_securities_utilized_to_original_post_haircut_security_ratios = []

	for loan_security_pledge in frappe.db.get_all(
		"Loan Security Pledge", {"loan": loan}, pluck="name"
	):
		loan_securities = frappe.db.get_all(
			"Pledge", {"parent": loan_security_pledge}, pluck="loan_security"
		)

		for loan_security in loan_securities:
			utilized_security_value, original_post_haircut_value = frappe.db.get_value(
				"Loan Security", loan_security, ["utilized_security_value", "original_post_haircut_value"]
			)
			utilized_to_original_security_ratio = flt(utilized_security_value / original_post_haircut_value)
			loan_securities_utilized_to_original_post_haircut_security_ratios.append(
				frappe._dict(
					{
						"loan_security": loan_security,
						"utilized_security_value": utilized_security_value,
						"original_post_haircut_value": original_post_haircut_value,
						"ratio": utilized_to_original_security_ratio,
					}
				)
			)

	sorted_loan_securities_ratios = sorted(
		loan_securities_utilized_to_original_post_haircut_security_ratios,
		key=lambda k: k["ratio"],
		reverse=increase,
	)

	for loan_security_with_ratio in sorted_loan_securities_ratios:
		if amount <= 0:
			break

		if increase:
			if (
				loan_security_with_ratio.utilized_security_value + amount
				> loan_security_with_ratio.original_post_haircut_value
			):
				new_utilized_security_value = loan_security_with_ratio.original_post_haircut_value
				amount = (
					amount
					- loan_security_with_ratio.original_post_haircut_value
					+ loan_security_with_ratio.utilized_security_value
				)
			else:
				new_utilized_security_value = loan_security_with_ratio.utilized_security_value + amount
				amount = 0
		else:
			if loan_security_with_ratio.utilized_security_value >= amount:
				new_utilized_security_value = loan_security_with_ratio.utilized_security_value - amount
				amount = 0
			else:
				new_utilized_security_value = 0
				amount = amount - loan_security_with_ratio.utilized_security_value

		frappe.db.set_value(
			"Loan Security",
			loan_security_with_ratio.loan_security,
			"utilized_security_value",
			new_utilized_security_value,
		)
