from dataclasses import replace
from datetime import datetime, timezone

import pytest

from memory_market.config import get_settings
from memory_market.models import MemoryCreate
from memory_market.payments import TRANSFER_TOPIC, PaymentDesk, PaymentError, RpcPool, RpcUnavailable, topic_address
from memory_market.store import MemoryStore

RECIPIENT = "0x1111111111111111111111111111111111111111"
PAYER = "0x2222222222222222222222222222222222222222"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TX = "0x" + "a" * 64


class FakeBase:
    def __init__(self):
        self.head = 100
        self.receipts = {}
        self.timestamps = {100: int(datetime.now(timezone.utc).timestamp())}
        self.block_hashes = {100: "0x" + "1" * 64}

    def call(self, method, params):
        if method == "eth_blockNumber":
            return hex(self.head)
        if method == "eth_getTransactionReceipt":
            return self.receipts.get(params[0])
        if method == "eth_getBlockByNumber":
            block = int(params[0], 16)
            return {
                "timestamp": hex(self.timestamps.get(block, self.timestamps[100])),
                "hash": self.block_hashes.setdefault(block, "0x" + f"{block:064x}"),
            }
        if method == "eth_getLogs":
            start, end = int(params[0]["fromBlock"], 16), int(params[0]["toBlock"], 16)
            return [
                log for receipt in self.receipts.values() for log in receipt["logs"]
                if start <= int(log["blockNumber"], 16) <= end
            ]
        raise AssertionError(method)

    def pay(self, amount_raw: int, block: int = 100, tx_hash: str = TX):
        self.timestamps[block] = int(datetime.now(timezone.utc).timestamp())
        block_hash = self.block_hashes.setdefault(block, "0x" + f"{block:064x}")
        self.receipts[tx_hash] = {
            "status": "0x1", "blockNumber": hex(block), "blockHash": block_hash,
            "logs": [{
                "address": USDC, "topics": [TRANSFER_TOPIC, topic_address(PAYER), topic_address(RECIPIENT)],
                "data": hex(amount_raw), "blockNumber": hex(block), "blockHash": block_hash,
                "transactionHash": tx_hash,
            }],
        }


def desk(tmp_path):
    store = MemoryStore(str(tmp_path / "market.sqlite3"))
    memory = store.create(MemoryCreate(
        title="Paid field note", content="Evidence that is licensed per read.",
        visibility="paid", price_usdc="2.50",
    ), "agent:publisher")
    settings = replace(
        get_settings(), db_path=str(tmp_path / "market.sqlite3"),
        payment_recipient=RECIPIENT, payment_token_address=USDC,
        payment_min_confirmations=5, payment_order_ttl_minutes=60,
        payment_late_grace_hours=24,
    )
    chain = FakeBase()
    return store, memory, chain, PaymentDesk(store, settings, rpc=chain)


def test_exact_finalized_payment_grants_memory_access(tmp_path):
    store, memory, chain, payments = desk(tmp_path)
    order = payments.create(memory.id, "agent:buyer")
    assert order.amount_usdc.startswith("2.50")
    assert int(order.amount_raw) > 2_500_000
    assert order.eip681.startswith(f"ethereum:{USDC}@8453/transfer")

    chain.pay(int(order.amount_raw))
    with pytest.raises(PaymentError, match="confirmations"):
        payments.confirm(order.order_id, TX)

    chain.head = 104
    settled = payments.confirm(order.order_id, TX)
    assert settled.settled is True
    assert settled.payer == PAYER
    assert store.has_grant(memory.id, "agent:buyer") is True
    assert store.can_read(memory, "agent:buyer") is True


def test_scanner_settles_only_matching_transfer(tmp_path):
    store, memory, chain, payments = desk(tmp_path)
    order = payments.create(memory.id, "agent:scanner")
    chain.pay(int(order.amount_raw), block=101)
    chain.head = 105
    assert payments.poll_once() == 1
    assert payments.get(order.order_id).settled is True
    assert store.has_grant(memory.id, "agent:scanner") is True


def test_wrong_amount_never_grants_access(tmp_path):
    store, memory, chain, payments = desk(tmp_path)
    order = payments.create(memory.id, "agent:no-access")
    chain.pay(int(order.amount_raw) - 1)
    chain.head = 104
    with pytest.raises(PaymentError, match="exact USDC"):
        payments.confirm(order.order_id, TX)
    assert store.has_grant(memory.id, "agent:no-access") is False


def test_transfer_from_before_order_is_rejected(tmp_path):
    store, memory, chain, payments = desk(tmp_path)
    order = payments.create(memory.id, "agent:old-transfer")
    chain.pay(int(order.amount_raw), block=99)
    chain.head = 103
    with pytest.raises(PaymentError, match="predates"):
        payments.confirm(order.order_id, TX)
    assert store.has_grant(memory.id, "agent:old-transfer") is False


def test_late_transfer_inside_grace_window_is_settled(tmp_path):
    store, memory, chain, payments = desk(tmp_path)
    order = payments.create(memory.id, "agent:late")
    current = int(datetime.now(timezone.utc).timestamp())
    with store.connection:
        store.connection.execute(
            "UPDATE payment_orders SET expires_unix=?, state='expired' WHERE order_id=?",
            (current - 10, order.order_id),
        )
    chain.pay(int(order.amount_raw), block=101)
    chain.timestamps[101] = current - 5
    chain.head = 105
    settled = payments.confirm(order.order_id, TX)
    assert settled.settled is True
    assert settled.late is True
    assert store.has_grant(memory.id, "agent:late") is True


def test_transaction_hash_cannot_unlock_two_orders(tmp_path):
    store, memory, chain, payments = desk(tmp_path)
    first = payments.create(memory.id, "agent:first")
    second = payments.create(memory.id, "agent:second")
    with store.connection:
        store.connection.execute(
            "UPDATE payment_orders SET amount_raw=?, amount_usdc=? WHERE order_id=?",
            (first.amount_raw, first.amount_usdc, second.order_id),
        )
    chain.pay(int(first.amount_raw))
    chain.head = 104
    assert payments.confirm(first.order_id, TX).settled is True
    with pytest.raises(PaymentError, match="already bound"):
        payments.confirm(second.order_id, TX)
    assert store.has_grant(memory.id, "agent:second") is False


def test_confirmed_payment_is_revoked_after_block_reorg(tmp_path):
    store, memory, chain, payments = desk(tmp_path)
    order = payments.create(memory.id, "agent:reorg")
    chain.pay(int(order.amount_raw))
    chain.head = 104
    assert payments.confirm(order.order_id, TX).settled is True
    assert store.has_grant(memory.id, "agent:reorg") is True

    chain.block_hashes[100] = "0x" + "f" * 64
    payments.poll_once()

    assert payments.get(order.order_id).settled is False
    assert store.has_grant(memory.id, "agent:reorg") is False


def test_every_rpc_failover_is_bound_to_base_mainnet(monkeypatch):
    pool = RpcPool(("https://base.invalid", "https://wrong.invalid"))
    base_down = False

    def fake_post(url, payload):
        method = payload["method"]
        if method == "eth_chainId":
            return {"result": "0x2105" if url == "https://base.invalid" else "0x1"}
        if url == "https://base.invalid" and not base_down:
            return {"result": "0x64"}
        raise OSError("endpoint unavailable")

    monkeypatch.setattr(pool, "_post", fake_post)
    assert pool.call("eth_blockNumber", []) == "0x64"
    base_down = True
    with pytest.raises(RpcUnavailable, match="chain 1, expected Base mainnet 8453"):
        pool.call("eth_blockNumber", [])
