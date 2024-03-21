from pypika import CustomFunction

import frappe
from frappe.query_builder.custom import ConstantColumn
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate


def get_payment_entries_for_bank_clearance(
	from_date, to_date, account, bank_account, include_reconciled_entries, include_pos_transactions
):
	entries = []

	loan_disbursement = frappe.qb.DocType("Loan Disbursement")

	query = (
		frappe.qb.from_(loan_disbursement)
		.select(
			ConstantColumn("Loan Disbursement").as_("payment_document"),
			loan_disbursement.name.as_("payment_entry"),
			loan_disbursement.disbursed_amount.as_("credit"),
			ConstantColumn(0).as_("debit"),
			loan_disbursement.reference_number.as_("cheque_number"),
			loan_disbursement.reference_date.as_("cheque_date"),
			loan_disbursement.clearance_date.as_("clearance_date"),
			loan_disbursement.disbursement_date.as_("posting_date"),
			loan_disbursement.applicant.as_("against_account"),
		)
		.where(loan_disbursement.docstatus == 1)
		.where(loan_disbursement.disbursement_date >= from_date)
		.where(loan_disbursement.disbursement_date <= to_date)
		.where(loan_disbursement.disbursement_account.isin([bank_account, account]))
		.orderby(loan_disbursement.disbursement_date)
		.orderby(loan_disbursement.name, order=frappe.qb.desc)
	)

	if not include_reconciled_entries:
		query = query.where(loan_disbursement.clearance_date.isnull())

	loan_disbursements = query.run(as_dict=1)

	loan_repayment = frappe.qb.DocType("Loan Repayment")

	query = (
		frappe.qb.from_(loan_repayment)
		.select(
			ConstantColumn("Loan Repayment").as_("payment_document"),
			loan_repayment.name.as_("payment_entry"),
			loan_repayment.amount_paid.as_("debit"),
			ConstantColumn(0).as_("credit"),
			loan_repayment.reference_number.as_("cheque_number"),
			loan_repayment.reference_date.as_("cheque_date"),
			loan_repayment.clearance_date.as_("clearance_date"),
			loan_repayment.applicant.as_("against_account"),
			loan_repayment.posting_date,
		)
		.where(loan_repayment.docstatus == 1)
		.where(loan_repayment.posting_date >= from_date)
		.where(loan_repayment.posting_date <= to_date)
		.where(loan_repayment.payment_account.isin([bank_account, account]))
	)

	if not include_reconciled_entries:
		query = query.where(loan_repayment.clearance_date.isnull())

	if frappe.db.has_column("Loan Repayment", "repay_from_salary"):
		query = query.where((loan_repayment.repay_from_salary == 0))

	query = query.orderby(loan_repayment.posting_date).orderby(
		loan_repayment.name, order=frappe.qb.desc
	)

	loan_repayments = query.run(as_dict=True)

	entries = list(loan_disbursements) + list(loan_repayments)

	return entries


def get_matching_queries(
	bank_account,
	company,
	transaction,
	document_types,
	exact_match,
	account_from_to,
	from_date,
	to_date,
	filter_by_reference_date,
	from_reference_date,
	to_reference_date,
	common_filters,
):
	queries = []

	if transaction.withdrawal > 0.0 and "loan_disbursement" in document_types:
		queries.append(get_ld_matching_query(bank_account, exact_match, transaction))

	if transaction.deposit > 0.0 and "loan_repayment" in document_types:
		queries.append(get_lr_matching_query(bank_account, exact_match, transaction))

	return queries


def get_ld_matching_query(bank_account, exact_match, transaction):
	loan_disbursement = frappe.qb.DocType("Loan Disbursement")

	matching_reference = loan_disbursement.reference_number == transaction.get("reference_number")
	ref_rank = frappe.qb.terms.Case().when(matching_reference, 1).else_(0)

	matching_party = (
		(loan_disbursement.applicant_type == transaction.party_type)
		& (loan_disbursement.applicant == transaction.party)
		& loan_disbursement.applicant.isnotnull()
	)
	party_rank = frappe.qb.terms.Case().when(matching_party, 1).else_(0)

	query = (
		frappe.qb.from_(loan_disbursement)
		.select(
			(ref_rank + party_rank + 1).as_("rank"),
			ConstantColumn("Loan Disbursement").as_("doctype"),
			loan_disbursement.name,
			(loan_disbursement.disbursed_amount).as_("paid_amount"),
			(loan_disbursement.reference_number).as_("reference_no"),
			loan_disbursement.reference_date,
			(loan_disbursement.applicant_type).as_("party_type"),
			(loan_disbursement.applicant).as_("party"),
			loan_disbursement.disbursement_date,
		)
		.where(loan_disbursement.docstatus == 1)
		.where(loan_disbursement.clearance_date.isnull())
		.where(loan_disbursement.disbursement_account == bank_account)
	)

	if exact_match:
		query.where(loan_disbursement.disbursed_amount == transaction.unallocated_amount)
	else:
		query.where(loan_disbursement.disbursed_amount > 0.0)

	return query


def get_lr_matching_query(bank_account, exact_match, transaction):
	loan_repayment = frappe.qb.DocType("Loan Repayment")

	matching_reference = loan_repayment.reference_number == transaction.get("reference_number")
	ref_rank = frappe.qb.terms.Case().when(matching_reference, 1).else_(0)

	matching_party = (
		(loan_repayment.applicant_type == transaction.party_type)
		& (loan_repayment.applicant == transaction.party)
		& loan_repayment.applicant.isnotnull()
	)
	party_rank = frappe.qb.terms.Case().when(matching_party, 1).else_(0)

	query = (
		frappe.qb.from_(loan_repayment)
		.select(
			(ref_rank + party_rank + 1).as_("rank"),
			ConstantColumn("Loan Repayment").as_("doctype"),
			loan_repayment.name,
			(loan_repayment.amount_paid).as_("paid_amount"),
			(loan_repayment.reference_number).as_("reference_no"),
			loan_repayment.reference_date,
			(loan_repayment.applicant_type).as_("party_type"),
			(loan_repayment.applicant).as_("party"),
			loan_repayment.posting_date,
		)
		.where(loan_repayment.docstatus == 1)
		.where(loan_repayment.clearance_date.isnull())
		.where(loan_repayment.payment_account == bank_account)
	)

	if frappe.db.has_column("Loan Repayment", "repay_from_salary"):
		query = query.where((loan_repayment.repay_from_salary == 0))

	if exact_match:
		query.where(loan_repayment.amount_paid == transaction.unallocated_amount)
	else:
		query.where(loan_repayment.amount_paid > 0.0)

	return query


def get_entries_for_bank_clearance_summary(filters):
	entries = []

	loan_disbursement = frappe.qb.DocType("Loan Disbursement")

	query = (
		frappe.qb.from_(loan_disbursement)
		.select(
			ConstantColumn("Loan Disbursement").as_("payment_document_type"),
			loan_disbursement.name.as_("payment_entry"),
			loan_disbursement.disbursement_date.as_("posting_date"),
			loan_disbursement.reference_number.as_("cheque_no"),
			loan_disbursement.clearance_date.as_("clearance_date"),
			loan_disbursement.applicant.as_("against"),
			-loan_disbursement.disbursed_amount.as_("amount"),
		)
		.where(loan_disbursement.docstatus == 1)
		.where(loan_disbursement.disbursement_date >= filters["from_date"])
		.where(loan_disbursement.disbursement_date <= filters["to_date"])
		.where(loan_disbursement.disbursement_account == filters["account"])
		.orderby(loan_disbursement.disbursement_date, order=frappe.qb.desc)
		.orderby(loan_disbursement.name, order=frappe.qb.desc)
	)

	if filters.get("from_date"):
		query = query.where(loan_disbursement.disbursement_date >= filters["from_date"])
	if filters.get("to_date"):
		query = query.where(loan_disbursement.disbursement_date <= filters["to_date"])

	loan_disbursements = query.run(as_list=1)

	loan_repayment = frappe.qb.DocType("Loan Repayment")

	query = (
		frappe.qb.from_(loan_repayment)
		.select(
			ConstantColumn("Loan Repayment").as_("payment_document_type"),
			loan_repayment.name.as_("payment_entry"),
			loan_repayment.posting_date.as_("posting_date"),
			loan_repayment.reference_number.as_("cheque_no"),
			loan_repayment.clearance_date.as_("clearance_date"),
			loan_repayment.applicant.as_("against"),
			loan_repayment.amount_paid.as_("amount"),
		)
		.where(loan_repayment.docstatus == 1)
		.where(loan_repayment.posting_date >= filters["from_date"])
		.where(loan_repayment.posting_date <= filters["to_date"])
		.where(loan_repayment.payment_account == filters["account"])
		.orderby(loan_repayment.posting_date, order=frappe.qb.desc)
		.orderby(loan_repayment.name, order=frappe.qb.desc)
	)

	if filters.get("from_date"):
		query = query.where(loan_repayment.posting_date >= filters["from_date"])
	if filters.get("to_date"):
		query = query.where(loan_repayment.posting_date <= filters["to_date"])

	loan_repayments = query.run(as_list=1)

	entries = loan_disbursements + loan_repayments

	return entries


def get_entries_for_bank_reconciliation_statement(filters):
	loan_entries = []
	for doctype in ["Loan Disbursement", "Loan Repayment"]:
		loan_doc = frappe.qb.DocType(doctype)
		ifnull = CustomFunction("IFNULL", ["value", "default"])

		if doctype == "Loan Disbursement":
			amount_field = (loan_doc.disbursed_amount).as_("credit")
			posting_date = (loan_doc.disbursement_date).as_("posting_date")
			account = loan_doc.disbursement_account
		else:
			amount_field = (loan_doc.amount_paid).as_("debit")
			posting_date = (loan_doc.posting_date).as_("posting_date")
			account = loan_doc.payment_account

		query = (
			frappe.qb.from_(loan_doc)
			.select(
				ConstantColumn(doctype).as_("payment_document"),
				(loan_doc.name).as_("payment_entry"),
				(loan_doc.reference_number).as_("reference_no"),
				(loan_doc.reference_date).as_("ref_date"),
				amount_field,
				posting_date,
			)
			.where(loan_doc.docstatus == 1)
			.where(account == filters.get("account"))
			.where(posting_date <= getdate(filters.get("report_date")))
			.where(ifnull(loan_doc.clearance_date, "4000-01-01") > getdate(filters.get("report_date")))
		)

		if doctype == "Loan Repayment" and frappe.db.has_column("Loan Repayment", "repay_from_salary"):
			query = query.where((loan_doc.repay_from_salary == 0))

		entries = query.run(as_dict=1)
		loan_entries.extend(entries)

	return list(loan_entries)


def get_amounts_not_reflected_in_system_for_bank_reconciliation_statement(filters):
	total_amount = 0
	for doctype in ["Loan Disbursement", "Loan Repayment"]:
		loan_doc = frappe.qb.DocType(doctype)
		ifnull = CustomFunction("IFNULL", ["value", "default"])

		if doctype == "Loan Disbursement":
			amount_field = Sum(loan_doc.disbursed_amount)
			posting_date = (loan_doc.disbursement_date).as_("posting_date")
			account = loan_doc.disbursement_account
		else:
			amount_field = Sum(loan_doc.amount_paid)
			posting_date = (loan_doc.posting_date).as_("posting_date")
			account = loan_doc.payment_account

		query = (
			frappe.qb.from_(loan_doc)
			.select(amount_field)
			.where(loan_doc.docstatus == 1)
			.where(account == filters.get("account"))
			.where(posting_date > getdate(filters.get("report_date")))
			.where(ifnull(loan_doc.clearance_date, "4000-01-01") <= getdate(filters.get("report_date")))
		)

		if doctype == "Loan Repayment" and frappe.db.has_column("Loan Repayment", "repay_from_salary"):
			query = query.where((loan_doc.repay_from_salary == 0))

		amount = query.run()[0][0]
		total_amount += flt(amount)

	return total_amount
