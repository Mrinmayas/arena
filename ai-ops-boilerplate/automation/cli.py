"""`uv run automate` entry point (also how the operator runs it on their machine)."""
from __future__ import annotations

import argparse
from pathlib import Path

from .automation import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="automate", description="Run the automation.")
    p.add_argument("--inputs", type=Path, default=Path("inputs"),
                   help="folder of input files (default: ./inputs)")
    p.add_argument("--outputs", type=Path, default=Path("outputs"),
                   help="where to write the deliverable (default: ./outputs)")
    p.add_argument("--operator", default=None,
                   help="who is running this (defaults to the OS user); recorded in the audit trail")
    p.add_argument("--redact", action="store_true",
                   help="mask money / document numbers in the audit trail")
    args = p.parse_args(argv)

    out = run(args.inputs, args.outputs, operator=args.operator, redact=args.redact)
    print(f"Done. Output: {out}")
    print("Audit trail: audit_logs/<latest>/run_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
