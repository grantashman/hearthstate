import sqlite3
import tempfile
import unittest
from pathlib import Path

from family_planner.store import PlannerStore
from scripts.backup_db import backup_database


class BackupDatabaseTests(unittest.TestCase):
    def test_creates_consistent_sqlite_backup_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "family_planner.db"
            destination = root / "backups" / "snapshot.db"
            store = PlannerStore(str(source))
            store.add_grocery_item("oat milk", "grant")
            before = source.stat().st_size

            result = backup_database(source, destination)

            self.assertEqual(result, destination)
            self.assertTrue(destination.exists())
            self.assertEqual(source.stat().st_size, before)
            with sqlite3.connect(destination) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("SELECT name FROM grocery_items").fetchone()[0], "oat milk")
            store.close()


if __name__ == "__main__":
    unittest.main()
