import frappe
from frappe.utils import flt


def execute():
	types = frappe.get_all("Loan Security Type", fields=["name", "haircut", "loan_to_value_ratio"])
	old_type_ltv = {t.name: flt(t.loan_to_value_ratio) for t in types}
	type_haircut = {}

	for t in types:
		haircut, ltv = flt(t.haircut), flt(t.loan_to_value_ratio)
		# The haircut defaults to 0, so 0 next to a set LTV means the haircut was never entered.
		if not haircut and ltv:
			haircut = 100 - ltv

		type_haircut[t.name] = haircut
		if (haircut, 100 - haircut) != (flt(t.haircut), ltv):
			frappe.db.set_value(
				"Loan Security Type",
				t.name,
				{"haircut": haircut, "loan_to_value_ratio": 100 - haircut},
				update_modified=False,
			)
			print(f"Loan Security Type {t.name}: {flt(t.haircut)}/{ltv} -> {haircut}/{100 - haircut}")

	for s in frappe.get_all(
		"Loan Security", fields=["name", "loan_security_type", "haircut", "loan_to_value_ratio"]
	):
		haircut = type_haircut.get(s.loan_security_type, flt(s.haircut))
		values = {"override_haircut": 0, "haircut": haircut, "loan_to_value_ratio": 100 - haircut}

		# Only the LTV could be typed on a security. Raising or lowering a limit is left to a
		# person, so a typed LTV is kept for the form to show rather than applied.
		ltv = flt(s.loan_to_value_ratio)
		if ltv and ltv != old_type_ltv.get(s.loan_security_type):
			values["ltv_before_upgrade"] = ltv
			print(f"Loan Security {s.name}: typed LTV {ltv} kept for review, follows type at {100 - haircut}")

		if (flt(s.haircut), ltv) != (values["haircut"], values["loan_to_value_ratio"]) or values.get(
			"ltv_before_upgrade"
		):
			frappe.db.set_value("Loan Security", s.name, values, update_modified=False)
