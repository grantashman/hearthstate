from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path


def backup_database(source: str | Path, destination: str | Path) -> Path:
    """Create an atomic, consistent SQLite backup using SQLite's backup API."""
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"database not found: {source_path}")
    if source_path == destination_path:
        raise ValueError("backup destination must differ from the source database")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination_path.with_name(f".{destination_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    try:
        with sqlite3.connect(source_path) as source_connection:
            with sqlite3.connect(temporary_path) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.execute("PRAGMA synchronous = FULL")
                destination_connection.commit()
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, destination_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return destination_path


def prune_backups(directory: str | Path, *, keep: int = 14) -> list[Path]:
    """Delete old Hearthstate backups, retaining the newest ``keep`` files."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    directory_path = Path(directory).expanduser().resolve()
    backups = sorted(directory_path.glob("hearthstate-*.db"), key=lambda path: path.name)
    removed = backups[:-keep]
    for path in removed:
        path.unlink()
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an atomic Hearthstate SQLite backup.")
    parser.add_argument("--database", default="hearthstate.db", help="Source SQLite database path")
    parser.add_argument("--output-dir", default="backups", help="Directory for timestamped backups")
    parser.add_argument("--keep", type=int, default=14, help="Number of newest Hearthstate backups to retain")
    args = parser.parse_args()

    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    destination = Path(args.output_dir) / f"hearthstate-{timestamp}.db"
    result = backup_database(args.database, destination)
    prune_backups(args.output_dir, keep=args.keep)
    print(result)


if __name__ == "__main__":
    main()
