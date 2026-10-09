"""Python client for Attested Memory — verifiable memory for AI agents."""

__version__ = "0.1.0"

from .actor import Actor  # noqa: E402
from .client import AttestedMemoryError, Client, IntegrityError, check_integrity, content_hash  # noqa: E402

__all__ = ["Actor", "AttestedMemoryError", "Client", "IntegrityError", "check_integrity", "content_hash",
           "__version__"]
