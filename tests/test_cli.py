import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SessionIdentityCliTests(unittest.TestCase):
    def test_hearthstate_db_env_sets_the_default_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "hearthstate.db"
            environment = os.environ.copy()
            environment["HEARTHSTATE_DB"] = str(database)
            environment.pop("FAMILY_PLANNER_DB", None)
            environment["HERMES_SESSION_USER_ID"] = "+614****0001"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "family_planner.cli",
                    "--from-session",
                    "Add oat milk to the grocery list",
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            database_created = database.exists()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Added to groceries: oat milk.")
        self.assertTrue(database_created)

    def test_from_session_uses_hermes_session_user_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "planner.db"
            environment = os.environ.copy()
            environment["HERMES_SESSION_USER_ID"] = "+61400000001"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "family_planner.cli",
                    "--from-session",
                    "--database",
                    str(database),
                    "Add oat milk to the grocery list",
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Added to groceries: oat milk.")


if __name__ == "__main__":
    unittest.main()
