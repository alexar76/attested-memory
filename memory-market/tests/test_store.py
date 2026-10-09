from memory_market.models import MemoryCreate
from memory_market.store import MemoryStore


def make_store(tmp_path):
    return MemoryStore(str(tmp_path / "market.sqlite3"))


def test_private_memory_requires_owner_or_grant(tmp_path):
    store = make_store(tmp_path)
    unit = store.create(MemoryCreate(title="Deployment note", content="The migration completed."), "agent:owner")
    assert store.can_read(unit, None) is False
    assert store.can_read(unit, "agent:owner") is True
    store.grant(unit.id, "agent:reader", "agent:owner")
    assert store.can_read(unit, "agent:reader") is True


def test_paid_memory_is_discoverable_but_not_readable_without_grant(tmp_path):
    store = make_store(tmp_path)
    unit = store.create(MemoryCreate(
        title="Expert playbook", content="A licensed research memory", visibility="paid", price_usdc="2.50"
    ), "expert:one")
    items, total = store.catalog("playbook", None, 20, 0)
    assert total == 1
    assert items[0].id == unit.id
    assert store.can_read(unit, "buyer:one") is False


def test_one_rating_per_actor_is_updated(tmp_path):
    store = make_store(tmp_path)
    unit = store.create(MemoryCreate(title="Runbook", content="Step one"), "agent:owner")
    first = store.score(unit.id, "agent:reviewer", 3)
    second = store.score(unit.id, "agent:reviewer", 5)
    assert first.score_count == 1
    assert second.score_count == 1
    assert second.average_score == 5


def test_truth_and_provenance_are_properties_of_memory(tmp_path):
    store = make_store(tmp_path)
    unit = store.create(MemoryCreate(title="Finding", content="Evidence-backed finding"), "researcher")
    store.set_truth(unit.id, "supported", 0.92, "pack_test")
    store.set_provenance(unit.id, "rcpt_test", "sha256:" + "b" * 64)
    updated = store.get_unchecked(unit.id)
    assert updated.truth.status == "supported"
    assert updated.provenance.status == "attested"
