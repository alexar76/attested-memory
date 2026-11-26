#!/usr/bin/env python3
"""Retain verified heads on the Compose host, outside the service containers."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def validate_export(data: object) -> dict:
    if (not isinstance(data, dict) or data.get("format") != "attested-memory-heads-v1"
            or not isinstance(data.get("heads"), dict)):
        raise ValueError("expected a verified heads export from Memory Market")
    for memory_id, head in data["heads"].items():
        if (not re.fullmatch(r"mem_[0-9a-f]{24}", memory_id) or not isinstance(head, dict)
                or not isinstance(head.get("receipt_id"), str) or not head["receipt_id"]
                or not isinstance(head.get("chain_root"), str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", head["chain_root"])):
            raise ValueError("invalid provenance checkpoint entry")
    return data["heads"]


def update(directory: Path, *, initialize: bool) -> int:
    checkpoint = directory / "heads.json"
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            retained = checkpoint.read_bytes()
        except FileNotFoundError:
            if not initialize:
                raise
            retained = None

        command = ["/usr/bin/docker", "compose", "exec", "-T", "memory-market", "python",
                   "-m", "memory_market.reconcile_provenance", "--export-heads"]
        if retained is not None:
            command.extend(["--against", "-"])

        with tempfile.NamedTemporaryFile(dir=directory, prefix=".heads-", delete=False) as output:
            pending = Path(output.name)
            try:
                result = subprocess.run(command, input=retained or b"", stdout=output, check=False)
                if result.returncode:
                    return result.returncode if result.returncode > 0 else 1
                output.seek(0)
                candidate = validate_export(json.load(output))
                if retained is not None and not validate_export(json.loads(retained)).keys() <= candidate.keys():
                    raise ValueError("the verified export omitted a retained memory")
                os.fsync(output.fileno())
                pending.replace(checkpoint)
                descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                pending.unlink(missing_ok=True)
    print(f"Verified and retained {len(candidate)} provenance heads")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--initialize", action="store_true", help="allow an explicit first baseline")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        return update(args.directory, initialize=args.initialize)
    except (OSError, ValueError) as error:
        print(f"Provenance checkpoint: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
