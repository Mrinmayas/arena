"""CLI entry point for the recorder."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import (
    DEFAULT_API_PATH_PATTERN,
    DEFAULT_BROWSER_CHANNEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROFILE_DIR,
    RecorderConfig,
)
from .recorder import run_session


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="record",
        description=(
            "Launch a browser via Playwright with full session tracing and an "
            "in-page Capture button for tagged screenshot + HTML snapshots. "
            "Defaults target Microsoft Edge / Entra portals; override the flags "
            "below to point at any other portal."
        ),
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="about:blank",
        help="Initial URL to open (default: about:blank).",
    )
    parser.add_argument(
        "--session-name",
        help="Folder name under the output directory. Defaults to a timestamp.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Where to write session folders (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--user-data-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help=(
            f"Persistent browser profile directory, kept between runs so portal "
            f"logins are remembered (default: {DEFAULT_PROFILE_DIR})."
        ),
    )
    parser.add_argument(
        "--browser-channel",
        default=DEFAULT_BROWSER_CHANNEL,
        help=(
            "Playwright browser channel, e.g. 'msedge', 'chrome', "
            "'msedge-beta'. Use an empty string for the bundled Chromium "
            f"(default: {DEFAULT_BROWSER_CHANNEL})."
        ),
    )
    parser.add_argument(
        "--api-path-pattern",
        default=DEFAULT_API_PATH_PATTERN,
        help=(
            "Case-insensitive regex marking a URL as API-ish when curating "
            "api_calls.json. The default recognizes Microsoft/SharePoint/Graph "
            "shapes; override it for a non-Microsoft portal "
            f"(default: {DEFAULT_API_PATH_PATTERN!r})."
        ),
    )
    args = parser.parse_args()

    config = RecorderConfig(
        start_url=args.url,
        session_name=args.session_name,
        output_dir=Path(args.output_dir).resolve(),
        profile_dir=Path(args.user_data_dir).resolve(),
        browser_channel=args.browser_channel,
        api_path_pattern=args.api_path_pattern,
    )

    # Ensure the persistent profile and output roots exist before launching.
    config.profile_dir.mkdir(parents=True, exist_ok=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    asyncio.run(run_session(config))


if __name__ == "__main__":
    main()
