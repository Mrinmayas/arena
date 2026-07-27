"""macOS Keychain secret store.

Stores secrets in the login Keychain via keyring's macOS backend. The backend is
instantiated explicitly (rather than through keyring's global, auto-selected
backend) so secrets are guaranteed to live in the Keychain rather than a fallback
store -- mirroring how ``WindowsSecretStore`` pins the Credential Manager backend.

The backend class moved module path across keyring versions
(``keyring.backends.macOS`` on modern keyring, ``keyring.backends.OS_X`` on older
releases), so both import paths are attempted.
"""

from __future__ import annotations

from keyring.errors import KeyringError, PasswordDeleteError

from .keys import SERVICE_NAME, SecretKey
from .store import SecretStore, SecretStoreError


class MacOSSecretStore(SecretStore):
    def __init__(self) -> None:
        keyring_cls = None
        try:
            from keyring.backends.macOS import Keyring as keyring_cls  # type: ignore[no-redef]
        except ImportError:
            try:
                from keyring.backends.OS_X import Keyring as keyring_cls  # type: ignore[no-redef]
            except ImportError as e:  # backend unavailable (e.g. non-macOS host)
                raise SecretStoreError(
                    "macOS Keychain backend is not available on this platform"
                ) from e
        self._kr = keyring_cls()

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
            # Deleting an absent secret is a no-op, matching the other backends so
            # the interface contract is consistent.
            pass

    def has_secret(self, key: SecretKey) -> bool:
        return self.get_secret(key) is not None
