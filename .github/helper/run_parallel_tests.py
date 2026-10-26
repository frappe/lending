"""Run one CI build's share of the lending tests, split by number of test methods instead of file count.

Usage, from the bench's sites directory:
	~/frappe-bench/env/bin/python ../apps/lending/.github/helper/run_parallel_tests.py <site> <build-number> <total-builds>
"""

import os
import re
import sys

from frappe.coverage import CodeCoverage
from frappe.parallel_test_runner import ParallelTestRunner, get_all_tests

APP = "lending"
TEST_METHOD = re.compile(r"^\s+def test_", re.MULTILINE)


class BalancedParallelTestRunner(ParallelTestRunner):
	def get_test_file_list(self):
		def test_count(test):
			with open(os.path.join(*test)) as f:
				return len(TEST_METHOD.findall(f.read())) or 1

		builds = [[] for _ in range(self.total_builds)]
		loads = [0] * self.total_builds
		for test in sorted(get_all_tests(self.app), key=test_count, reverse=True):
			build = loads.index(min(loads))
			builds[build].append(test)
			loads[build] += test_count(test)

		return builds[self.build_number - 1]


if __name__ == "__main__":
	site, build_number, total_builds = sys.argv[1:4]
	with CodeCoverage(bool(os.environ.get("CAPTURE_COVERAGE")), APP):
		BalancedParallelTestRunner(
			APP, site=site, build_number=build_number, total_builds=total_builds, lightmode=True
		).setup_and_run()
