"""Base class shared by every enterprise-portal automation.

A :class:`Portal` encapsulates the lifecycle every portal has in common so
individual automations never re-implement it:

  1. open a browser context, either
       * **seeded** from a harvested ``storage_state.json`` (username/password
         pattern), or
       * backed by a **persistent profile** ``user_data_dir`` (SSO pattern);
  2. detect whether that context is already authenticated; if not, run the
     subclass's scripted :meth:`login` and re-harvest the seed (for the seeded
     pattern) so the next run skips login;
  3. provide ``navigate`` / ``download`` / ``upload`` primitives.

Concrete portals subclass this and implement just :meth:`_on_login_page` and
:meth:`login`. Use it as an async context manager so the browser always closes::

    async with await ExamplePortal.open(
        secrets=store, workspace=Path("runs/today"), headless=False
    ) as portal:
        await portal.download(dest, click="#export")

This module is framework-agnostic: it depends only on the standard library and
``playwright``. All run state is injected explicitly (``secrets``, ``workspace``,
``headless`` and an optional ``log`` callback) rather than pulled from any
engine/run-context object.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from playwright.async_api import BrowserContext, Page

from .browser import BrowserHandle, launch_context, launch_persistent_context


@runtime_checkable
class SecretProvider(Protocol):
    """Structural type for the secret store injected into a portal.

    Any object exposing ``require_secret(key) -> str`` satisfies it -- e.g. the
    sibling ``secretstore.SecretStore``. Declared structurally (and with an
    ``Any`` key) so the portals package stays decoupled from any concrete secret
    backend or key registry.
    """

    def require_secret(self, key: Any) -> str: ...


class Portal(ABC):
    #: Subclasses set these class attributes.
    name: str = "portal"
    login_url: str = ""
    #: Where a recorder-harvested auth seed lives (gitignored). ``None`` = no seed.
    #: Used by the seeded (username/password) pattern.
    storage_state_path: Path | None = None
    #: On-disk persistent profile dir. When set, the SSO-persistent-profile pattern
    #: is used instead of a seeded context. ``None`` = seeded context.
    user_data_dir: Path | None = None

    def __init__(
        self,
        *,
        secrets: SecretProvider,
        workspace: Path,
        headless: bool = False,
        log: Callable[[str], None] | None = None,
        channel: str | None = None,
    ) -> None:
        """
        Args:
            secrets: secret store used by :meth:`login` to fetch credentials.
            workspace: directory for run output; also the browser downloads dir.
            headless: run without a visible window (use ``False`` for interactive SSO).
            log: optional sink for human-readable progress lines. ``None`` = silent.
            channel: browser channel passed through to the launcher (e.g. ``"msedge"``).
        """
        self.secrets = secrets
        self.workspace = workspace
        self.headless = headless
        self._log = log
        self.channel = channel
        self._handle: BrowserHandle | None = None
        self.page: Page | None = None

    @property
    def context(self) -> BrowserContext:
        if self._handle is None:
            raise RuntimeError("Portal not opened")
        return self._handle.context

    def log(self, message: str) -> None:
        """Emit a progress line through the injected ``log`` callback, if any."""
        if self._log is not None:
            self._log(message)

    @classmethod
    async def open(
        cls,
        *,
        secrets: SecretProvider,
        workspace: Path,
        headless: bool = False,
        log: Callable[[str], None] | None = None,
        channel: str | None = None,
    ) -> "Portal":
        self = cls(
            secrets=secrets,
            workspace=workspace,
            headless=headless,
            log=log,
            channel=channel,
        )
        await self._launch()
        await self._configure_page()
        if not await self._is_authenticated():
            self.log(f"{self.name}: not authenticated, logging in")
            await self.login()
            await self.save_storage_state()
        return self

    def _profile_dir(self) -> Path | None:
        """Resolve the persistent-profile directory, or ``None`` for a seeded context.

        Default: the ``user_data_dir`` class attribute. Subclasses may override to
        compute the directory dynamically (e.g. one sub-folder per browser channel).
        """
        return self.user_data_dir

    async def _launch(self) -> None:
        """Launch the browser context (persistent profile or seeded) and grab a page."""
        profile = self._profile_dir()
        if profile is not None:
            self._handle = await launch_persistent_context(
                user_data_dir=profile,
                downloads_dir=self.workspace,
                headless=self.headless,
                channel=self.channel,
            )
        else:
            self._handle = await launch_context(
                storage_state=self.storage_state_path,
                downloads_dir=self.workspace,
                headless=self.headless,
                channel=self.channel,
            )
        # A persistent context opens with a blank page already; reuse it.
        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()

    async def _configure_page(self) -> None:
        """Hook to configure the freshly-opened page (e.g. default timeouts). No-op."""

    async def _is_authenticated(self) -> bool:
        """Navigate to the portal and decide whether we're already logged in.

        Default heuristic: load ``login_url`` and ask the subclass whether the login
        form is showing. Override for portals that need a different probe.
        """
        assert self.page is not None
        await self.page.goto(self.login_url, wait_until="domcontentloaded")
        return not await self._on_login_page()

    @abstractmethod
    async def _on_login_page(self) -> bool:
        """Return True if the current page is the portal's login screen."""

    @abstractmethod
    async def login(self) -> None:
        """Authenticate the current page.

        Two supported patterns:
          * username/password -- fill and submit the login form using credentials
            from ``self.secrets``;
          * SSO-persistent-profile -- wait for the operator to complete an
            interactive sign-on, then wait for a post-login element.
        """

    async def save_storage_state(self) -> None:
        """Persist current auth back to the seed so the next run skips login.

        No-op unless ``storage_state_path`` is set (persistent-profile portals keep
        their auth in ``user_data_dir`` instead).
        """
        if self.storage_state_path is None:
            return
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(self.storage_state_path))

    async def navigate(self, url: str) -> None:
        assert self.page is not None
        await self.page.goto(url, wait_until="networkidle")

    async def download(
        self, dest: Path, *, click: str | None = None, goto: str | None = None
    ) -> Path:
        """Trigger a download (by clicking ``click`` or navigating to ``goto``) and
        save it to ``dest``. Returns the saved path."""
        assert self.page is not None
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self.page.expect_download() as dl:
            if click is not None:
                await self.page.click(click)
            elif goto is not None:
                await self.page.goto(goto)
            else:
                raise ValueError("download() needs either click= or goto=")
        download = await dl.value
        await download.save_as(str(dest))
        self.log(f"{self.name}: downloaded {dest.name}")
        return dest

    async def upload(self, file_input: str, path: Path) -> None:
        assert self.page is not None
        await self.page.set_input_files(file_input, str(path))
        self.log(f"{self.name}: selected {path.name} for upload")

    async def close(self) -> None:
        if self._handle is not None:
            await self._handle.close()
            self._handle = None

    async def __aenter__(self) -> "Portal":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()
