from frappe.tests import IntegrationTestCase

from lending.loan_management.report.alm_audit_report.alm_audit_report import (
	get_ageing_bucket,
	get_ageing_map,
	get_columns,
)


class TestALMAuditReport(IntegrationTestCase):
	def test_alm_audit_report_gets_ageing_bucket(self):
		bucket = get_ageing_bucket("2024-01-31", "2024-01-31")
		self.assertEqual(bucket, "Overdue")

	def test_alm_audit_report_returns_expected_ageing_map(self):
		ageing_map = get_ageing_map()
		expected_ageing_map = {
			"0-0": "Overdue",
			"0-31": "1 day to 30/31 days (one month)",
			"32-60": "1 to 2 Months",
			"61-90": "Over 2 Months upto 3 Months",
			"91-180": "Over 3 Months to 6 Months",
			"181-365": "Over 6 Months to 1 Year",
			"365-1095": "1 to 3 Years",
			"1096-1825": "3 to 5 Years",
			"1826-100000": "Over 5 Years",
		}
		self.assertEqual(ageing_map, expected_ageing_map)

	def test_alm_audit_report_defines_columns(self):
		columns = get_columns()
		self.assertGreater(len(columns), 3)
