import sqlite3
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hearthstate.store import PlannerStore
from scripts.backup_db import backup_database, main as backup_main, prune_backups


class BackupDatabaseTests(unittest.TestCase):
    def test_cli_creates_backup_and_prunes_old_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hearthstate.db"
            output_dir = root / "backups"
            store = PlannerStore(str(source))
            store.add_grocery_item("oat milk", "grant")
            for name in (
                "hearthstate-20260801-020000.db",
                "hearthstate-20260802-020000.db",
            ):
                (output_dir / name).parent.mkdir(parents=True, exist_ok=True)
                (output_dir / name).write_bytes(b"backup")

            output = io.StringIO()
            with patch.object(sys, "argv", [
                "backup_db.py",
                "--database", str(source),
                "--output-dir", str(output_dir),
                "--keep", "2",
            ]), redirect_stdout(output):
                backup_main()

            self.assertEqual(len(list(output_dir.glob("hearthstate-*.db"))), 2)
            self.assertIn("hearthstate-", output.getvalue())
            store.close()

    def test_retains_only_newest_timestamped_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backups = root / "backups"
            backups.mkdir()
            for name in (
                "hearthstate-20260801-020000.db",
                "hearthstate-20260802-020000.db",
                "hearthstate-20260803-020000.db",
            ):
                (backups / name).write_bytes(b"backup")
            (backups / "unrelated.db").write_bytes(b"keep")

            removed = prune_backups(backups, keep=2)

            self.assertEqual([path.name for path in removed], ["hearthstate-20260801-020000.db"])
            self.assertFalse((backups / "hearthstate-20260801-020000.db").exists())
            self.assertTrue((backups / "hearthstate-20260802-020000.db").exists())
            self.assertTrue((backups / "hearthstate-20260803-020000.db").exists())
            self.assertTrue((backups / "unrelated.db").exists())

    def test_creates_consistent_sqlite_backup_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hearthstate.db"
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
