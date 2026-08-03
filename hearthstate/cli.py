from __future__ import annotations

import argparse
import os

from .app import Hearthstate
from .store import PlannerStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Handle one Hearthstate message.")
    parser.add_argument(
        "--from-session",
        action="store_true",
        help="Use HERMES_SESSION_USER_ID as the sender (for Photon/iMessage).",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("HEARTHSTATE_DB", "hearthstate.db"),
        help="SQLite database path (default: HEARTHSTATE_DB or hearthstate.db)",
    )
    parser.add_argument("parts", nargs="+", help="[sender] message text")
    args = parser.parse_args()

    if args.from_session:
        sender = os.environ.get("HERMES_SESSION_USER_ID", "").strip()
        if not sender:
            parser.error("--from-session requires HERMES_SESSION_USER_ID")
        message_parts = args.parts
    else:
        if len(args.parts) < 2:
            parser.error("explicit mode requires a sender followed by a message")
        sender, *message_parts = args.parts

    store = PlannerStore(args.database)
    try:
        response = Hearthstate(store).handle_message(sender, " ".join(message_parts))
        print(response)
    finally:
        store.close()


if __name__ == "__main__":
    main()
