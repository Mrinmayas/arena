"""Registry of secret keys.

Every secret this package can touch is identified by a member of ``SecretKey``.
Stores operate only on these members, so the set of credentials the codebase can
read or write is grounded on this single, reviewable list.

**Pattern for a new project:**
  1. Rename ``SERVICE_NAME`` to your project/client (it namespaces every entry in
     the OS credential store, e.g. the Windows Credential Manager *target* prefix
     or the macOS Keychain *service*).
  2. Add one member per secret. The member's *value* is the stable identifier
     persisted by the backend (the keyring *username*), so keep values unique and
     stable once a secret is in use. One username/password pair per portal is the
     usual shape -- the matching ``Portal`` subclass fetches them in ``login()``
     via ``require_secret``.

The two ``EXAMPLE_PORTAL_*`` members below are illustrative; replace or extend
them with your real keys.
"""

from __future__ import annotations

from enum import StrEnum

# Namespace for all credentials this project stores. Used as the keyring *service*,
# grouping every entry under one target prefix. RENAME THIS PER PROJECT/CLIENT.
SERVICE_NAME = "ai-ops-automation"


class SecretKey(StrEnum):
    # EXAMPLE credentials for one portal -- copy this pair per real portal and
    # rename (e.g. ACME_PORTAL_USERNAME / ACME_PORTAL_PASSWORD).
    EXAMPLE_PORTAL_USERNAME = "example.portal.username"
    EXAMPLE_PORTAL_PASSWORD = "example.portal.password"  # nosec B105 - keyring identifier, not a value
