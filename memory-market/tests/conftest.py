"""Unset AIFACTORY_PROD now means PRODUCTION; the suite opts into dev mode explicitly."""
import os

os.environ.setdefault("AIFACTORY_DEV", "1")
