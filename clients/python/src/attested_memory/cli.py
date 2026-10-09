"""attested-memory — command line for the Attested Memory API.

    attested-memory init                     # create your actor key (~/.config/attested-memory)
    attested-memory trial                    # claim the 7-day personal key for that actor
    attested-memory write "Title" "Text"     # or: --file notes.md
    attested-memory search "supplier"
    attested-memory read mem_…

Environment: ATTESTED_MEMORY_HOME (config dir), ATTESTED_MEMORY_URL (default
https://attestedmemory.net), ATTESTED_MEMORY_API_KEY (instead of the stored trial key).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .actor import Actor
from .client import DEFAULT_BASE_URL, AttestedMemoryError, Client


def _home() -> Path:
    return Path(os.environ.get("ATTESTED_MEMORY_HOME") or Path.home() / ".config" / "attested-memory")


def _actor_path() -> Path:
    return _home() / "actor.json"


def _key_path() -> Path:
    return _home() / "key.json"


def _load_actor() -> Actor:
    path = _actor_path()
    if not path.exists():
        raise SystemExit(f"no actor key at {path} — run: attested-memory init")
    return Actor.load(path)


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _client(args: argparse.Namespace, *, need_key: bool = True) -> Client:
    api_key = os.environ.get("ATTESTED_MEMORY_API_KEY")
    if not api_key and _key_path().exists():
        api_key = json.loads(_key_path().read_text(encoding="utf-8")).get("api_key")
    if need_key and not api_key:
        raise SystemExit("no API key — run: attested-memory trial (or set ATTESTED_MEMORY_API_KEY)")
    return Client(_load_actor(), api_key, base_url=args.url)


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def cmd_init(args: argparse.Namespace) -> int:
    path = _actor_path()
    if path.exists():
        print(f"actor already exists: {Actor.load(path).actor_id}  ({path})")
        return 0
    actor = Actor.generate()
    actor.save(path)
    print(f"created {actor.actor_id}\nkey file: {path} (mode 0600 — keep it; it is your identity)")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    actor = _load_actor()
    print(actor.actor_id)
    if _key_path().exists():
        stored = json.loads(_key_path().read_text(encoding="utf-8"))
        print(f"key: {stored.get('product')} {stored.get('plan')} until {stored.get('expires_at')}")
    return 0


def cmd_trial(args: argparse.Namespace) -> int:
    client = _client(args, need_key=False)
    result = client.start_trial(args.product)
    _write_private(_key_path(), {k: result.get(k) for k in ("api_key", "product", "plan", "expires_at", "key_id")})
    print(f"{result.get('plan')} until {result.get('expires_at')} — key saved to {_key_path()}")
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    content = Path(args.file).read_text(encoding="utf-8") if args.file else args.content
    if not content:
        raise SystemExit("give the text as an argument or with --file")
    _print(_client(args).write(args.title, content, tags=args.tag or (), visibility=args.visibility,
                               source_refs=args.source or ()))
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    _print(_client(args).read(args.memory_id))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    _print(_client(args).search(args.query, args.limit))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="attested-memory", description="Verifiable memory for AI agents.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--url", default=os.environ.get("ATTESTED_MEMORY_URL", DEFAULT_BASE_URL))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create your actor key").set_defaults(func=cmd_init)
    sub.add_parser("whoami", help="show your actor id and key").set_defaults(func=cmd_whoami)
    trial = sub.add_parser("trial", help="claim the free trial key for your actor")
    trial.add_argument("--product", default="personal", choices=["personal", "team", "expert-market"])
    trial.set_defaults(func=cmd_trial)
    write = sub.add_parser("write", help="store a memory")
    write.add_argument("title")
    write.add_argument("content", nargs="?")
    write.add_argument("--file")
    write.add_argument("--tag", action="append")
    write.add_argument("--source", action="append", help="a source reference (URL, doc id)")
    write.add_argument("--visibility", default="private", choices=["private", "shared", "public", "paid"])
    write.set_defaults(func=cmd_write)
    read = sub.add_parser("read", help="read a memory (content checked against its hash)")
    read.add_argument("memory_id")
    read.set_defaults(func=cmd_read)
    search = sub.add_parser("search", help="search memories you can see")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--limit", type=int, default=30)
    search.set_defaults(func=cmd_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AttestedMemoryError as error:
        print(f"attested-memory: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
