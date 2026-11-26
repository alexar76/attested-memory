"""Review proposals and inspect access history from an operator terminal."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys

from .config import get_settings
from .models import ValidityWindow
from .store import MemoryStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    queue = commands.add_parser("list", help="list pending proposals")
    queue.add_argument("--limit", type=int, choices=range(1, 101), default=30, metavar="1..100")
    queue.add_argument("--offset", type=int, default=0)
    history = commands.add_parser("grant-history", help="list access events for a memory")
    history.add_argument("memory_id")
    history.add_argument("--limit", type=int, choices=range(1, 101), default=30, metavar="1..100")
    history.add_argument("--offset", type=int, default=0)
    for name in ("show", "approve", "reject", "validity"):
        command = commands.add_parser(name)
        command.add_argument("memory_id")
        if name == "validity":
            command.add_argument("--from", dest="valid_from", help="inclusive RFC 3339 instant")
            command.add_argument("--until", dest="valid_until", help="exclusive RFC 3339 instant")
    args = parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("memory review requires an interactive operator terminal")

    store = MemoryStore(get_settings().db_path)
    try:
        if args.command in {"list", "grant-history"}:
            if args.offset < 0:
                parser.error("--offset cannot be negative")
            rows = (store.pending_reviews(args.limit, args.offset) if args.command == "list"
                    else store.grant_history(args.memory_id, args.limit, args.offset))
            print(json.dumps(rows, indent=2))
            return 0

        unit = store.get_unchecked(args.memory_id)
        print(json.dumps(unit.model_dump(mode="json"), indent=2))
        if args.command == "show":
            return 0

        window = None
        if args.command == "validity":
            window = ValidityWindow(valid_from=args.valid_from, valid_until=args.valid_until)
            print(window.model_dump_json())
        confirmation = f"{args.command} {unit.id}"
        if input(f"Type {confirmation} to confirm: ").strip() != confirmation:
            print("Review cancelled", file=sys.stderr)
            return 1

        reviewer = f"operator:{pwd.getpwuid(os.getuid()).pw_name}"
        if window is not None:
            unit = store.correct_validity(unit.id, window, reviewer)
        else:
            unit = store.review(unit.id, {"approve": "approved", "reject": "rejected"}[args.command], reviewer)
        print(json.dumps({"memory_id": unit.id, "review_state": unit.review_state,
                          "validity": unit.model_dump(mode="json")["validity"]}))
        return 0
    except (EOFError, KeyError, PermissionError, ValueError) as error:
        print(f"Memory review: {error}", file=sys.stderr)
        return 1
    finally:
        store.connection.close()


if __name__ == "__main__":
    sys.exit(main())
