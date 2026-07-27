"""Pluggable, cross-platform secret storage and retrieval.

Layers:
  - ``SecretKey`` / ``SERVICE_NAME`` (keys): the registry of secrets the project may store.
  - ``SecretStore`` (store): the interface consuming code depends on.
  - ``WindowsSecretStore`` / ``MacOSSecretStore`` / ``InMemorySecretStore``: interchangeable backends.

``STORE_FACTORIES`` is the single source of truth for selectable backends. Select
one by name with ``get_store(name)`` (``"default"`` resolves per platform), or call
``get_default_store()`` for the platform-appropriate store.

Platform-aware default selection (mechanic-parity with the OS credential vault):
  - Windows  -> Windows Credential Manager (``"wincred"``)
  - macOS    -> login Keychain (``"keychain"``)
  - other    -> a clear error, unless the ``AI_OPS_SECRET_STORE`` environment
    variable names a backend to use (e.g. ``"memory"`` on Linux/CI).

Add a backend by adding one entry to ``STORE_FACTORIES`` (and a label).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

from .keys import SERVICE_NAME, SecretKey
from .macos import MacOSSecretStore
from .memory import InMemorySecretStore
from .store import SecretNotFoundError, SecretStore, SecretStoreError
from .windows import WindowsSecretStore

__all__ = [
    "SERVICE_NAME",
    "SecretKey",
    "SecretStore",
    "SecretStoreError",
    "SecretNotFoundError",
    "WindowsSecretStore",
    "MacOSSecretStore",
    "InMemorySecretStore",
    "STORE_FACTORIES",
    "STORE_LABELS",
    "ENV_STORE_VAR",
    "get_store",
    "get_default_store",
]

# Name -> factory for every selectable backend. Single source of truth.
STORE_FACTORIES: dict[str, Callable[[], SecretStore]] = {
    "wincred": WindowsSecretStore,
    "keychain": MacOSSecretStore,
    "memory": InMemorySecretStore,
}

# Human-friendly labels (e.g. for a management GUI), keyed by STORE_FACTORIES name.
STORE_LABELS: dict[str, str] = {
    "wincred": "Windows Credential Manager (WinCred)",
    "keychain": "macOS Keychain",
    "memory": "In-memory (non-persistent; dev/tests)",
}

# Environment variable that overrides platform detection for the "default" store.
ENV_STORE_VAR = "AI_OPS_SECRET_STORE"


def _default_store_name() -> str:
    """Resolve the backend name for ``"default"`` in a platform-aware way.

    An explicit ``AI_OPS_SECRET_STORE`` override wins (useful on Linux/CI). Then
    Windows -> ``wincred``, macOS -> ``keychain``. Any other platform without an
    override raises a clear error.
    """
    override = os.environ.get(ENV_STORE_VAR)
    if override:
        return override
    if sys.platform.startswith("win"):
        return "wincred"
    if sys.platform == "darwin":
        return "keychain"
    raise SecretStoreError(
        f"No default secret store for platform {sys.platform!r}. "
        f"Set {ENV_STORE_VAR} to one of: {', '.join(STORE_FACTORIES)}."
    )


def get_store(name: str = "default") -> SecretStore:
    key = _default_store_name() if name == "default" else name
    try:
        factory = STORE_FACTORIES[key]
    except KeyError:
        valid = ", ".join(["default", *STORE_FACTORIES])
        raise ValueError(f"Unknown secret store {name!r}. Valid options: {valid}") from None
    return factory()


def get_default_store() -> SecretStore:
    return get_store("default")
