from datetime import date, timedelta

import frappe
from frappe.utils.user import is_website_user


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True

	if is_website_user():
		return False

	return True


def daterange(start_date: date, end_date: date):
	days = int((end_date - start_date).days)
	for n in range(days + 1):
		yield start_date + timedelta(n)
