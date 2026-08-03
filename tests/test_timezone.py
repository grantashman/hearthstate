import unittest
from datetime import datetime, timezone

from hearthstate.timezone import PROJECT_TIMEZONE, PROJECT_TIMEZONE_NAME, local_now


class ProjectTimezoneTests(unittest.TestCase):
    def test_hearthstate_uses_australia_sydney(self):
        self.assertEqual(PROJECT_TIMEZONE_NAME, "Australia/Sydney")
        expected = datetime.now(timezone.utc).astimezone(PROJECT_TIMEZONE).replace(tzinfo=None)
        actual = local_now()
        self.assertEqual(actual.strftime("%Y-%m-%d %H:%M"), expected.strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    unittest.main()
