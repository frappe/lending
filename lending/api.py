import frappe

@frappe.whitelist()
def get_loan_list(hub=None,loan_act=None,cust_urn=None,cust_name=None):
	filters = {}
	loan = ''
	if hub != None:
		filters["hub"] = hub
	if loan_act != None:
		filters["loan_account_number"] = loan_act
	if cust_name:
		cust_name = frappe.db.get_value('Customer',{'customer_name':cust_name},'customer_urn')
	if not cust_urn  and cust_name:
		filters["applicant"] = cust_name
	if cust_urn  and not cust_name:
		filters["applicant"] = cust_urn
	if (cust_urn and cust_name) and (cust_urn  == cust_name):
		filters["applicant"] = cust_urn
	if filters != {}:
		loan = frappe.db.get_list('Loan',filters = filters, pluck='name')
	if (cust_urn and cust_name) and (cust_urn  != cust_name):
		a = []
		loan_urn = frappe.db.get_list('Loan',filters = {'applicant':cust_urn}, pluck='name')
		a.extend(loan_urn)
		loan_name = frappe.db.get_list('Loan',filters = {'applicant':cust_name}, pluck='name')
		a.extend(loan_name)
		if loan:
			loan.extend(a)
		else:
			loan = a
	return loan