import unittest
from datetime import datetime, timezone

from family_planner.timezone import PROJECT_TIMEZONE_NAME, local_now


class ProjectTimezoneTests(unittest.TestCase):
    def test_family_planner_uses_australia_sydney(self):
        self.assertEqual(PROJECT_TIMEZONE_NAME, "Australia/Sydney")
        expected = datetime.now(timezone.utc).astimezone().replace(tzinfo=None)
        actual = local_now()
        self.assertEqual(actual.strftime("%Y-%m-%d %H:%M"), expected.strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    unittest.main()
