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


def test_paid_content_search_requires_read_access(tmp_path):
    store = make_store(tmp_path)
    unit = store.create(MemoryCreate(title="For sale", content="hidden-unique-password",
                                     visibility="paid", price_usdc="1"), "owner")
    for actor in (None, "unpaid"):
        assert store.catalog("hidden-unique", actor, 20, 0)[1] == 0
        assert store.catalog("For sale", actor, 20, 0)[1] == 1
    assert store.catalog("hidden-unique", "owner", 20, 0)[1] == 1
    store.grant(unit.id, "buyer", "owner")
    assert store.catalog("hidden-unique", "buyer", 20, 0)[1] == 1
    public = store.create(MemoryCreate(title="Public", content="public-unique-password",
                                       visibility="public"), "owner")
    assert store.catalog("public-unique", None, 20, 0)[0][0].id == public.id


def test_team_catalog_treats_underscore_as_literal(tmp_path):
    store = make_store(tmp_path)
    store.create(MemoryCreate(title="Other team", content="Other team secret",
                              visibility="shared", tags=["team:teamXvictim"]), "owner")
    assert store.catalog("", "reader", 20, 0, "team_victim")[1] == 0
    unit = store.create(MemoryCreate(title="My team", content="team-body-secret",
                                     visibility="shared", tags=["team:team_victim"]), "owner")
    assert store.catalog("team-body-secret", "reader", 20, 0, "team_victim")[0][0].id == unit.id
