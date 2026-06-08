# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe.query_builder.functions import Sum
from frappe.utils.dashboard import cache_source

from lending.loan_management.report.applicant_wise_loan_security_exposure.applicant_wise_loan_security_exposure import (
	get_loan_security_details,
)


@frappe.whitelist()
@cache_source
def get_data(
	chart_name: str | None = None,
	chart: str | None = None,
	no_cache: str | None = None,
	filters: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	timespan: str | None = None,
	time_interval: str | None = None,
	heatmap_year: str | None = None,
) -> dict:
	if chart_name:
		chart = frappe.get_doc("Dashboard Chart", chart_name)
	else:
		chart = frappe._dict(frappe.parse_json(chart))

	filters = {}
	current_pledges = {}

	if filters:
		filters = frappe.parse_json(filters)[0]

	labels = []
	values = []

	company = filters.get("company")

	loan_security_details = get_loan_security_details()

	lsr = frappe.qb.DocType("Loan Security Release")
	unpledge = frappe.qb.DocType("Unpledge")
	unpledge_query = (
		frappe.qb.from_(lsr)
		.inner_join(unpledge)
		.on(unpledge.parent == lsr.name)
		.select(unpledge.loan_security, Sum(unpledge.qty).as_("qty"))
		.where(lsr.status == "Approved")
		.groupby(unpledge.loan_security)
	)
	if company:
		unpledge_query = unpledge_query.where(lsr.company == company)

	unpledges = frappe._dict(unpledge_query.run(as_list=1))

	lsa = frappe.qb.DocType("Loan Security Assignment")
	pledge = frappe.qb.DocType("Pledge")
	pledge_query = (
		frappe.qb.from_(lsa)
		.inner_join(pledge)
		.on(pledge.parent == lsa.name)
		.select(pledge.loan_security, Sum(pledge.qty).as_("qty"))
		.where(lsa.status == "Pledged")
		.groupby(pledge.loan_security)
	)
	if company:
		pledge_query = pledge_query.where(lsa.company == company)

	pledges = frappe._dict(pledge_query.run(as_list=1))

	for security, qty in pledges.items():
		current_pledges.setdefault(security, qty)
		current_pledges[security] -= unpledges.get(security, 0.0)

	sorted_pledges = dict(sorted(current_pledges.items(), key=lambda item: item[1], reverse=True))

	count = 0
	for security, qty in sorted_pledges.items():
		values.append(qty * loan_security_details.get(security, {}).get("latest_price", 0))
		labels.append(security)
		count += 1

		# Just need top 10 securities
		if count == 10:
			break

	return {
		"labels": labels,
		"datasets": [{"name": "Top 10 Securities", "chartType": "bar", "values": values}],
	}
