"""Run one CI build's share of the lending tests, split by recorded runtime instead of test count.

Usage, from the bench's sites directory:
	~/frappe-bench/env/bin/python ../apps/lending/.github/helper/run_parallel_tests.py <site> <build-number> <total-builds>
"""

import json
import os
import sys

import frappe
from frappe.coverage import CodeCoverage
from frappe.parallel_test_runner import ParallelTestRunner, get_all_tests

APP = "lending"
TIMINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_timings.json")
# seconds assumed for a test file missing from the timings file
DEFAULT_SECONDS = 30


class TimedParallelTestRunner(ParallelTestRunner):
	def get_test_file_list(self):
		with open(TIMINGS_FILE) as f:
			timings = json.load(f)

		app_root = os.path.dirname(frappe.get_app_path(self.app))

		def seconds(test):
			return timings.get(os.path.relpath(os.path.join(*test), app_root), DEFAULT_SECONDS)

		builds = [[] for _ in range(self.total_builds)]
		loads = [0.0] * self.total_builds
		for test in sorted(get_all_tests(self.app), key=seconds, reverse=True):
			build = loads.index(min(loads))
			builds[build].append(test)
			loads[build] += seconds(test)

		return builds[self.build_number - 1]


if __name__ == "__main__":
	site, build_number, total_builds = sys.argv[1:4]
	with CodeCoverage(bool(os.environ.get("CAPTURE_COVERAGE")), APP):
		TimedParallelTestRunner(
			APP, site=site, build_number=build_number, total_builds=total_builds, lightmode=True
		).setup_and_run()
