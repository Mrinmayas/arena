"""In-memory secret store.

A non-persistent backend that keeps secrets in a dict for the lifetime of the
process. Useful for tests and local development so consuming code can run without
touching the real OS credential store, and a working example of the swappable
``SecretStore`` design.
"""

from __future__ import annotations

from .keys import SecretKey
from .store import SecretStore


class InMemorySecretStore(SecretStore):
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def set_secret(self, key: SecretKey, value: str) -> None:
        self._secrets[key.value] = value

    def get_secret(self, key: SecretKey) -> str | None:
        return self._secrets.get(key.value)

    def delete_secret(self, key: SecretKey) -> None:
        self._secrets.pop(key.value, None)

    def has_secret(self, key: SecretKey) -> bool:
        return key.value in self._secrets
