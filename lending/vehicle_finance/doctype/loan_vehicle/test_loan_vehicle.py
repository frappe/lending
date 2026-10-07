# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from random import randint

import frappe
from frappe.desk.query_report import run
from frappe.utils import add_days, getdate, nowdate

from lending.loan_management.doctype.loan_application.loan_application import (
	create_loan_security_assignment,
)
from lending.loan_management.doctype.loan_security_shortfall.loan_security_shortfall import (
	check_for_ltv_shortfall,
)
from lending.tests.test_utils import (
	create_loan_application,
	create_loan_product,
	create_loan_with_security,
	make_customer,
	make_loan_disbursement_entry,
	master_init,
)
from lending.tests.utils import LendingTestSuite
from lending.vehicle_finance.doctype.post_disbursal_document.post_disbursal_document import (
	mark_overdue_documents,
)
from lending.vehicle_finance.loan_hooks import issue_noc

APPLICANT = "_Test CV Customer"
PRODUCT = "CV Loan"


class TestLoanVehicle(LendingTestSuite):
	def setUp(self):
		master_init()
		make_customer(APPLICANT)
		setup_vehicle_masters()
		setup_cv_loan_product()
		frappe.db.set_single_value("Lending Settings", "block_on_rc_owner_name_mismatch", 0)
		frappe.db.set_single_value("Lending Settings", "issue_noc_on_settled_loans", 0)

	def test_vehicle_creates_loan_security_and_blocks_duplicates(self):
		vehicle = create_vehicle(chassis_number="mat 448 012 a1b2c3d4")

		self.assertEqual(vehicle.chassis_number, "MAT448012A1B2C3D4")
		loan_security = frappe.get_doc("Loan Security", vehicle.loan_security)
		self.assertEqual(loan_security.vehicle, vehicle.name)
		self.assertEqual(loan_security.original_security_value, 1000000)

		self.assertRaises(frappe.ValidationError, create_vehicle, chassis_number=vehicle.chassis_number)

	def test_ltv_rule_caps_loan_amount(self):
		lcv = create_vehicle()
		application = make_application([lcv])
		self.assertEqual(application.maximum_loan_amount, 850000)
		self.assertEqual(application.proposed_pledges[0].haircut, 15)

		hcv = create_vehicle(vehicle_model="_Test Tata Signa 4825", invoice_value=4000000)
		application = make_application([hcv])
		self.assertEqual(application.maximum_loan_amount, 3600000)

		refinance = create_used_vehicle(asset_condition="Refinance")
		self.assertRaises(frappe.ValidationError, make_application, [refinance])

	def test_age_and_valuation_checks_on_approval(self):
		old_vehicle = create_used_vehicle(manufacturing_year=getdate().year - 9)
		create_valuation(old_vehicle.name)
		self.assertRaises(frappe.ValidationError, make_application, [old_vehicle], approve=True)

		used = create_used_vehicle()
		self.assertRaises(frappe.ValidationError, make_application, [used])

		create_valuation(used.name, valuation_date=add_days(nowdate(), -120))
		self.assertRaises(frappe.ValidationError, make_application, [used], approve=True)

		create_valuation(used.name, market_value=600000)
		application = make_application([used], approve=True)
		self.assertEqual(application.maximum_loan_amount, 420000)

	def test_rc_owner_name_mismatch(self):
		used = create_used_vehicle(rc_owner_name="Someone Else Entirely")
		create_valuation(used.name)

		make_application([used], approve=True)

		frappe.db.set_single_value("Lending Settings", "block_on_rc_owner_name_mismatch", 1)
		self.assertRaises(frappe.ValidationError, make_application, [used], approve=True)

	def test_new_vehicle_pledge_disbursement_and_pdd(self):
		vehicle = create_vehicle(chassis_number=None, engine_number=None)
		loan = make_loan([vehicle])

		vehicle.reload()
		self.assertEqual(vehicle.status, "Financed")
		self.assertEqual(vehicle.current_loan, loan.name)

		self.assertRaises(
			frappe.ValidationError, make_application, [vehicle]
		)
		self.assertRaises(
			frappe.ValidationError, make_loan_disbursement_entry, loan.name, 100000, disbursement_date="2026-04-01"
		)

		vehicle.chassis_number = "MAT448012A1B2C3D9"
		vehicle.engine_number = "ENG0001"
		vehicle.save()

		make_loan_disbursement_entry(
			loan.name, 400000, disbursement_date="2026-04-01", repayment_start_date="2026-05-05"
		)
		documents = {
			d.document_type: d
			for d in frappe.get_all(
				"Post Disbursal Document",
				filters={"loan": loan.name},
				fields=["document_type", "due_date", "blocks_next_disbursement"],
			)
		}
		self.assertEqual(set(documents), {"RC", "Tax Invoice", "Insurance Policy"})
		self.assertEqual(getdate(documents["RC"].due_date), getdate("2026-04-11"))
		self.assertTrue(documents["RC"].blocks_next_disbursement)

	def test_overdue_blocking_pdd_blocks_next_tranche(self):
		vehicle = create_vehicle()
		loan = make_loan([vehicle])
		make_loan_disbursement_entry(
			loan.name, 400000, disbursement_date="2026-04-01", repayment_start_date="2026-05-05"
		)

		mark_overdue_documents()
		rc = frappe.get_doc("Post Disbursal Document", {"loan": loan.name, "document_type": "RC"})
		self.assertEqual(rc.status, "Overdue")

		self.assertRaises(
			frappe.ValidationError,
			make_loan_disbursement_entry,
			loan.name,
			100000,
			disbursement_date="2026-04-20",
			repayment_start_date="2026-05-05",
		)

		rc.file = "/files/rc.pdf"
		registration_number = f"MH12AB{randint(1000, 9999)}"
		rc.registration_number = registration_number.lower()
		rc.registration_date = "2026-04-10"
		rc.hypothecation_endorsed = 1
		rc.status = "Verified"
		rc.save()

		vehicle.reload()
		self.assertEqual(vehicle.registration_number, registration_number)
		self.assertEqual(vehicle.hypothecation_status, "Endorsed")

		make_loan_disbursement_entry(
			loan.name, 100000, disbursement_date="2026-04-20", repayment_start_date="2026-05-05"
		)

	def test_shortfall_skips_vehicle_only_loans(self):
		vehicle = create_vehicle()
		loan = make_loan([vehicle])
		make_loan_disbursement_entry(
			loan.name, 500000, disbursement_date="2026-04-01", repayment_start_date="2026-05-05"
		)

		check_for_ltv_shortfall(None, loan=loan.name, applicant=APPLICANT)

		self.assertFalse(frappe.db.exists("Loan Security Shortfall", {"loan": loan.name}))
		self.assertFalse(
			frappe.db.exists("Loan Security Shortfall", {"applicant": APPLICANT, "status": "Pending"})
		)

	def test_issue_noc_releases_vehicle(self):
		vehicle = create_vehicle()
		loan = make_loan([vehicle])
		frappe.db.set_value("Loan Vehicle", vehicle.name, "hypothecation_status", "Endorsed")

		self.assertRaises(frappe.ValidationError, issue_noc, loan.name)

		loan.db_set("status", "Settled")
		self.assertRaises(frappe.ValidationError, issue_noc, loan.name)

		loan.db_set("status", "Loan Closure Requested")
		self.assertEqual(issue_noc(loan.name), [vehicle.name])

		vehicle.reload()
		loan.reload()
		self.assertEqual(loan.status, "Closed")
		self.assertEqual(vehicle.status, "Released")
		self.assertEqual(vehicle.hypothecation_status, "Termination Requested")
		self.assertEqual(getdate(vehicle.noc_issued_on), getdate())
		self.assertFalse(
			frappe.db.exists("Loan Security Assignment", {"loan": loan.name, "status": "Pledged"})
		)
		self.assertRaises(frappe.ValidationError, issue_noc, loan.name)

		noc = frappe.get_print("Loan Vehicle", vehicle.name, print_format="Vehicle NOC")
		self.assertIn("No Objection Certificate", noc)
		form_35 = frappe.get_print("Loan Vehicle", vehicle.name, print_format="Vehicle Form 35")
		self.assertEqual(form_35.count("FORM 35"), 2)

	def test_reports(self):
		vehicle = create_vehicle()
		loan = make_loan([vehicle])
		make_loan_disbursement_entry(
			loan.name, 400000, disbursement_date="2026-04-01", repayment_start_date="2026-05-05"
		)

		ageing = run("PDD Ageing", filters={"loan": loan.name, "as_on_date": "2026-05-01"})["result"]
		rc = next(row for row in ageing if row["document_type"] == "RC")
		self.assertEqual(rc["days_overdue"], 20)
		self.assertEqual(rc["bucket"], "0-30")

		portfolio = run("Vehicle Portfolio", filters={"group_by": "Segment"})["result"]
		self.assertTrue(any(row["group"] == "LCV" and row["outstanding_principal"] > 0 for row in portfolio))

		register = run("Hypothecation Register", filters={})["result"]
		self.assertIn(vehicle.name, [row["name"] for row in register])

		age_profile = run("Vehicle Age Profile", filters={})["result"]
		self.assertIn(vehicle.name, [row["name"] for row in age_profile])

	def test_issue_noc_on_settled_loan_follows_setting(self):
		vehicle = create_vehicle()
		loan = make_loan([vehicle])
		loan.db_set("status", "Settled")

		frappe.db.set_single_value("Lending Settings", "issue_noc_on_settled_loans", 1)
		self.assertEqual(issue_noc(loan.name), [vehicle.name])

	def test_assignment_cancel_reverts_vehicle(self):
		vehicle = create_vehicle()
		loan = make_loan([vehicle])

		frappe.get_doc("Loan Security Assignment", {"loan": loan.name}).cancel()

		vehicle.reload()
		self.assertEqual(vehicle.status, "Proposed")
		self.assertFalse(vehicle.current_loan)


def setup_vehicle_masters():
	for make in ("_Test Tata", "_Test Ashok Leyland"):
		if not frappe.db.exists("Vehicle Make", make):
			frappe.get_doc({"doctype": "Vehicle Make", "make_name": make}).insert()

	for make, model, segment in (
		("_Test Ashok Leyland", "Dost", "LCV"),
		("_Test Tata", "Signa 4825", "HCV"),
	):
		if not frappe.db.exists("Vehicle Model", f"{make} {model}"):
			frappe.get_doc(
				{"doctype": "Vehicle Model", "make": make, "model_name": model, "segment": segment}
			).insert()


def setup_cv_loan_product():
	product = create_loan_product(PRODUCT, PRODUCT, 5000000, 14)
	product.max_vehicles_per_loan = 2
	product.valuation_validity_days = 90
	product.set(
		"vehicle_ltv_rules",
		[
			{"asset_condition": "New", "max_ltv_percent": 85, "max_age_at_sanction_years": 1, "max_age_at_maturity_years": 10},
			{"asset_condition": "New", "segment": "HCV", "max_ltv_percent": 90},
			{"asset_condition": "Used", "max_ltv_percent": 70, "max_age_at_sanction_years": 8, "max_age_at_maturity_years": 12},
		],
	)
	product.set(
		"pdd_requirements",
		[
			{"document_type": "RC", "due_in_days": 10, "blocks_next_disbursement": 1},
			{"document_type": "Tax Invoice", "asset_condition": "New", "due_in_days": 15},
			{"document_type": "Insurance Policy", "due_in_days": 15},
		],
	)
	product.save()


def unique_suffix():
	return frappe.generate_hash(length=8).upper()


def create_vehicle(**kwargs):
	today = getdate()
	values = {
		"doctype": "Loan Vehicle",
		"vehicle_model": "_Test Ashok Leyland Dost",
		"asset_condition": "New",
		"loan_security_type": "Vehicle",
		"chassis_number": f"MAT448012{unique_suffix()}",
		"engine_number": f"ENG{unique_suffix()}",
		"manufacturing_month": "January",
		"manufacturing_year": today.year,
		"applicant_type": "Customer",
		"applicant": APPLICANT,
		"invoice_value": 1000000,
	}
	values.update(kwargs)
	return frappe.get_doc(values).insert()


def create_used_vehicle(**kwargs):
	values = {
		"asset_condition": "Used",
		"registration_number": f"MH12CD{randint(1000, 9999)}",
		"rc_copy": "/files/rc.pdf",
		"manufacturing_year": getdate().year - 3,
		"invoice_value": 0,
	}
	values.update(kwargs)
	return create_vehicle(**values)


def create_valuation(vehicle, market_value=500000, valuation_date=None):
	valuation = frappe.get_doc(
		{
			"doctype": "Vehicle Valuation",
			"vehicle": vehicle,
			"valuation_date": valuation_date or nowdate(),
			"market_value": market_value,
		}
	)
	valuation.insert()
	valuation.submit()
	return valuation


def make_application(vehicles, approve=False):
	application = create_loan_application(
		"_Test Company",
		APPLICANT,
		PRODUCT,
		[{"vehicle": vehicle.name} for vehicle in vehicles],
		"Repay Over Number of Periods",
		48,
		do_not_save=True,
	)
	application.status = "Approved" if approve else "Open"
	application.save()
	return application


def make_loan(vehicles):
	application = make_application(vehicles, approve=True)
	application.submit()
	create_loan_security_assignment(application.name)

	loan = create_loan_with_security(
		APPLICANT,
		PRODUCT,
		"Repay Over Number of Periods",
		48,
		application.name,
		posting_date="2026-04-01",
		repayment_start_date="2026-05-05",
	)
	loan.submit()
	return loan
