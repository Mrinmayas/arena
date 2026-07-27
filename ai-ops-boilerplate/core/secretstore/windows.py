"""Windows Credential Manager secret store.

Stores secrets in Windows Credential Manager via keyring's ``WinVaultKeyring``
backend. The backend is instantiated explicitly (rather than through keyring's
global, auto-selected backend) so secrets are guaranteed to live in Credential
Manager rather than a fallback store.
"""

from __future__ import annotations

from keyring.errors import KeyringError, PasswordDeleteError

from .keys import SERVICE_NAME, SecretKey
from .store import SecretStore, SecretStoreError


class WindowsSecretStore(SecretStore):
    def __init__(self) -> None:
        try:
            from keyring.backends.Windows import WinVaultKeyring
        except ImportError as e:  # backend unavailable (e.g. non-Windows host)
            raise SecretStoreError(
                "Windows Credential Manager backend is not available on this platform"
            ) from e
        self._kr = WinVaultKeyring()

    def set_secret(self, key: SecretKey, value: str) -> None:
        try:
            self._kr.set_password(SERVICE_NAME, key.value, value)
        except KeyringError as e:
            raise SecretStoreError(f"Failed to store secret {key.name}") from e

    def get_secret(self, key: SecretKey) -> str | None:
        return self._kr.get_password(SERVICE_NAME, key.value)

    def delete_secret(self, key: SecretKey) -> None:
        try:
            self._kr.delete_password(SERVICE_NAME, key.value)
        except PasswordDeleteError:
            # Deleting an absent secret is a no-op, matching InMemorySecretStore so
            # the interface contract is consistent across backends.
            pass

    def has_secret(self, key: SecretKey) -> bool:
        return self.get_secret(key) is not None
