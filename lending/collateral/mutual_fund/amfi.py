# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import get_request_session

from lending.collateral.mutual_fund.registry import NavAdapter

NAV_FILE_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"


class AmfiNavAdapter(NavAdapter):
	key = "AMFI"

	def target_url(self):
		return NAV_FILE_URL

	def fetch_nav_file(self, context):
		response = get_request_session(max_retries=3).get(NAV_FILE_URL, timeout=60)
		response.raise_for_status()
		# Sent as text/plain with no charset, so requests would guess Latin-1
		content = response.content.decode("utf-8", errors="replace")
		return {"content": keep_site_schemes(content)}


def keep_site_schemes(content):
	# The full file is about 1.5 MB and every answer is logged, so only the site's own schemes are kept
	codes = set(
		frappe.get_all(
			"Loan Security",
			filters={"is_mutual_fund": 1, "amfi_scheme_code": ("is", "set")},
			pluck="amfi_scheme_code",
		)
	)
	lines = content.splitlines()
	return "\r\n".join(lines[:1] + [line for line in lines[1:] if line.split(";", 1)[0].strip() in codes])
