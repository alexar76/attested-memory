"""Give every unattested Memory Unit its ledger receipt.

    python -m memory_market.reconcile_provenance          # attest what is missing
    python -m memory_market.reconcile_provenance --count  # only count; writes nothing
    python -m memory_market.reconcile_provenance --check  # compare attested units with the ledger
    python -m memory_market.reconcile_provenance --export-heads
    python -m memory_market.reconcile_provenance --check --against previously-exported-heads.json
    python -m memory_market.reconcile_provenance --export-heads --against - < previously-exported-heads.json

A write asks the Provenance Ledger for a ``created`` receipt once, and a ledger that is down or slow
leaves the unit ``unattested``. This finishes those: for each unit it first looks for a ``created``
receipt of the same content in the owner's name already in the ledger (an attest that landed while
its answer was lost; a receipt someone else appended with the same hash is not taken),
and only asks for a new one when there is none, so running it again never doubles a receipt. A unit
the ledger still cannot take stays unattested and is counted. scripts/systemd/ has an hourly timer
that runs it and then compares and advances a host-retained checkpoint. Both operations page by id
and are safe beside the service.

``--check`` is the comparison from outside the ledger. The ledger's own ``chain_head`` check holds
its database against itself, so whoever can write that database can delete receipts and move the
head together. The market keeps, for every attested unit, the receipt id and chain root the ledger
returned; ``--check`` requires that receipt to still be in the unit's chain with that root, and the
ledger to verify all receipts and their links from genesis to its current head. A mismatch is printed
per unit and the command exits 2. A valid suffix removed together with its head can still escape
detection if it starts after the market's stored receipt. A writer to the shared database can also
change the market's anchor. Detecting those cases requires a separately retained head.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .clients import TrustClients
from .config import get_settings


HEADS_FORMAT = "attested-memory-heads-v1"


def reconcile(store, clients: TrustClients, *, write: bool = True, page: int = 200) -> dict[str, int]:
    result = {"unattested": 0, "linked": 0, "attested": 0, "failed": 0}
    after = ""
    while True:
        units = store.unattested(page, after)
        if not units:
            return result
        for unit in units:
            result["unattested"] += 1
            if not write:
                continue
            receipt = clients.created_receipt(unit)
            if receipt:
                result["linked"] += 1
            else:
                receipt = clients.attest(unit, "created", unit.owner_id)
                if not receipt:
                    result["failed"] += 1
                    continue
                result["attested"] += 1
            store.set_provenance(unit.id, receipt["id"], receipt["chain_root"], created=True)
        after = units[-1].id


def check(store, clients: TrustClients, *, page: int = 200,
          against: dict | None = None, observed_heads: dict | None = None) -> dict:
    result: dict = {"attested": 0, "matching": 0, "unreachable": 0, "mismatched": []}
    checkpoint = against or {}
    pending = set(checkpoint)
    after = ""
    while True:
        units = store.attested(page, after)
        if not units:
            result["mismatched"].extend({
                "memory_id": memory_id, "receipt_id": checkpoint[memory_id]["receipt_id"],
                "problem": "the checkpoint memory is missing from the attested market records",
            } for memory_id in sorted(pending))
            return result
        for unit in units:
            pending.discard(unit.id)
            result["attested"] += 1
            lineage = clients.lineage(unit.id)
            verdict = clients.verify_receipt(unit.provenance.receipt_id) if unit.provenance.receipt_id else None
            if lineage is None or (unit.provenance.receipt_id and verdict is None):
                result["unreachable"] += 1
                continue
            problem = _mismatch(unit, lineage, verdict)
            if not problem and unit.id in checkpoint:
                anchor = checkpoint[unit.id]
                if not any(r.get("id") == anchor["receipt_id"] and r.get("chain_root") == anchor["chain_root"]
                           for r in (lineage.get("receipts") or [])):
                    problem = "the independently retained head is no longer in the ledger chain"
            if not problem and observed_heads is not None:
                head = lineage["receipts"][-1]
                confirmed = (verdict if head["id"] == unit.provenance.receipt_id
                             else clients.verify_receipt(head["id"]))
                if confirmed and confirmed.get("valid") and confirmed.get("checks", {}).get("full_lineage"):
                    observed_heads[unit.id] = {"receipt_id": head["id"], "chain_root": head["chain_root"]}
                else:
                    problem = "could not verify the observed head for export"
            if problem:
                result["mismatched"].append({"memory_id": unit.id, "receipt_id": unit.provenance.receipt_id,
                                             "problem": problem})
            else:
                result["matching"] += 1
        after = units[-1].id


def _mismatch(unit, lineage: dict, verdict: dict | None) -> str | None:
    receipt_id, root = unit.provenance.receipt_id, unit.provenance.lineage_root
    if not receipt_id or not root:
        return "attested here without a receipt id or chain root"
    in_chain = [r for r in lineage.get("receipts") or [] if r.get("id") == receipt_id]
    if not in_chain:
        return "the recorded receipt is no longer in the ledger chain"
    if in_chain[0].get("chain_root") != root:
        return "the receipt's chain root differs from the one the ledger returned on append"
    if not (verdict or {}).get("valid"):
        failed = sorted(k for k, ok in ((verdict or {}).get("checks") or {}).items() if not ok)
        return "the ledger does not verify the receipt: " + (", ".join(failed) or "invalid")
    if not verdict.get("checks", {}).get("full_lineage"):
        return "the ledger did not verify the full lineage"
    return None


def read_heads(path: Path) -> dict:
    data = json.load(sys.stdin) if path == Path("-") else json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != HEADS_FORMAT or not isinstance(data.get("heads"), dict):
        raise ValueError("expected an Attested Memory heads export")
    heads = data["heads"]
    for memory_id, head in heads.items():
        if (not re.fullmatch(r"mem_[0-9a-f]{24}", memory_id) or not isinstance(head, dict)
                or not isinstance(head.get("receipt_id"), str) or not head["receipt_id"]
                or not isinstance(head.get("chain_root"), str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", head["chain_root"])):
            raise ValueError("invalid memory, receipt id or chain root in heads export")
    return heads


def main(argv: list[str] | None = None) -> int:
    from .app import store

    parser = argparse.ArgumentParser(prog="python -m memory_market.reconcile_provenance",
                                     description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--count", action="store_true", help="only count unattested units")
    mode.add_argument("--check", action="store_true",
                      help="compare each attested unit's recorded receipt and root with the ledger")
    mode.add_argument("--export-heads", action="store_true", help="export verified chain heads for independent retention")
    parser.add_argument("--against", type=Path,
                        help="also require each head in this retained export (use - for stdin)")
    args = parser.parse_args(argv)
    if args.against and not (args.check or args.export_heads):
        parser.error("--against requires --check or --export-heads")
    if args.check or args.export_heads:
        try:
            previous = read_heads(args.against) if args.against else None
        except (ValueError, OSError) as error:
            parser.error(str(error))
        heads = {} if args.export_heads else None
        outcome = check(store(), TrustClients(get_settings()), against=previous, observed_heads=heads)
        status = 2 if outcome["mismatched"] else (1 if outcome["unreachable"] else 0)
        if not args.export_heads:
            print(json.dumps(outcome))
        elif status:
            print(json.dumps(outcome), file=sys.stderr)
        else:
            print(json.dumps({"format": HEADS_FORMAT, "heads": heads}))
        return status
    result = reconcile(store(), TrustClients(get_settings()), write=not args.count)
    print(json.dumps(result))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
