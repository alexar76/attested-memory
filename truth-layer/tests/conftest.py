"""Unset AIFACTORY_PROD now means PRODUCTION; the suite opts into dev mode explicitly."""
import os

import pytest

os.environ.setdefault("AIFACTORY_DEV", "1")


@pytest.fixture
def approved_memory():
    """Prepare a unit by the same admission transition used by an operator."""

    def approve(store, request, owner_id):
        unit = store.create(request, owner_id)
        return store.review(unit.id, "approved", "operator:fixture")

    return approve
