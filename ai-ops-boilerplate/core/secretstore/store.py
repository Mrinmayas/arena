"""Secret storage interface.

``SecretStore`` is the abstraction consuming code depends on. Concrete backends
(Windows Credential Manager, macOS Keychain, in-memory, ...) implement it, so the
storage mechanism can be swapped without touching callers. Every method takes a
``SecretKey``, keeping all operations grounded on the key registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .keys import SecretKey


class SecretStoreError(Exception):
    """Base error for any secret storage/retrieval failure."""


class SecretNotFoundError(SecretStoreError):
    """Raised when a required secret is absent from the store."""


class SecretStore(ABC):
    @abstractmethod
    def set_secret(self, key: SecretKey, value: str) -> None: ...

    @abstractmethod
    def get_secret(self, key: SecretKey) -> str | None: ...

    @abstractmethod
    def delete_secret(self, key: SecretKey) -> None: ...

    @abstractmethod
    def has_secret(self, key: SecretKey) -> bool: ...

    def require_secret(self, key: SecretKey) -> str:
        value = self.get_secret(key)
        if value is None:
            raise SecretNotFoundError(f"No secret stored for {key.name} ({key.value})")
        return value
