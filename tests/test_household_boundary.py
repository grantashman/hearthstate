import tempfile
import unittest
from pathlib import Path

from hearthstate.accounts import HouseholdDirectory
from hearthstate.store import PlannerStore


class HouseholdDirectoryTests(unittest.TestCase):
    def test_owner_and_member_can_be_resolved_with_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            accounts = HouseholdDirectory(str(Path(directory) / "accounts.db"))
            try:
                accounts.create_account("grant", "Grant Ashman", "grant@example.test")
                accounts.create_account("billie", "Billie Ashman", "billie@example.test")
                accounts.create_household("home", "Ashman Household", "grant")
                accounts.add_member("home", "billie", "member")

                self.assertEqual(accounts.household_for("grant"), "home")
                self.assertEqual(accounts.household_for("billie"), "home")
                self.assertEqual(accounts.role_for("grant", "home"), "owner")
                self.assertTrue(accounts.can_access("billie", "home"))
            finally:
                accounts.close()

    def test_membership_is_required_for_access(self):
        with tempfile.TemporaryDirectory() as directory:
            accounts = HouseholdDirectory(str(Path(directory) / "accounts.db"))
            try:
                accounts.create_account("grant", "Grant")
                accounts.create_account("stranger", "Stranger")
                accounts.create_household("home", "Home", "grant")

                self.assertFalse(accounts.can_access("stranger", "home"))
                with self.assertRaises(ValueError):
                    accounts.require_access("stranger", "home")
            finally:
                accounts.close()


class HouseholdPlannerIsolationTests(unittest.TestCase):
    def test_planner_data_isolated_by_household_context(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "planner.db")
            home = PlannerStore(database, household_id="home")
            cabin = PlannerStore(database, household_id="cabin")
            same_home = PlannerStore(database, household_id="home")
            try:
                home.add_task("home task", None, None, False, "grant")
                cabin.add_task("cabin task", None, None, False, "grant")

                self.assertEqual([task["title"] for task in home.list_tasks()], ["home task"])
                self.assertEqual([task["title"] for task in same_home.list_tasks()], ["home task"])
                self.assertEqual([task["title"] for task in cabin.list_tasks()], ["cabin task"])
                self.assertEqual(home.household_id, "home")
                self.assertNotEqual(home.database_path, cabin.database_path)
            finally:
                home.close()
                cabin.close()
                same_home.close()

    def test_default_context_preserves_existing_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "planner.db")
            store = PlannerStore(database)
            try:
                self.assertEqual(store.household_id, "default")
                self.assertEqual(store.database_path, database)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
