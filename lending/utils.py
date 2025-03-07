from datetime import date, timedelta

import frappe
from frappe.utils import now_datetime
from frappe.utils.user import is_website_user

from erpnext.setup.utils import enable_all_roles_and_domains


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True

	if is_website_user():
		return False

	enable_all_roles_and_domains()
	frappe.db.commit()  # nosemgrep


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True

	if is_website_user():
		return False

	return True


def daterange(start_date: date, end_date: date):
	days = int((end_date - start_date).days)
	for n in range(days):
		yield start_date + timedelta(n)
