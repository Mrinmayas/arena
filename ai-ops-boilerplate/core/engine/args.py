"""Argument schema declaration and validation for automations.

An automation may declare ``ARG_SPECS: list[ArgSpec]`` alongside its other metadata.
The runner validates supplied arguments against that schema before starting the run,
then seeds them into working memory.

An automation with an empty (or absent) schema accepts any arguments without
validation — the schema is optional.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArgSpec:
    """Declaration of one argument an automation accepts.

    ``kind`` is ``"value"`` for plain data (passed with ``--arg key=value``) and
    ``"file"`` for file paths (passed with ``--input key=path``).
    """

    name: str
    mandatory: bool = False
    description: str = ""
    kind: str = "value"  # "value" | "file"


class ArgumentValidationError(ValueError):
    """Raised before a run starts when supplied arguments fail schema validation."""


def validate_arguments(
    schema: list[ArgSpec],
    values: dict[str, object],
    files: dict[str, Path],
) -> None:
    """Validate supplied arguments against the automation's declared schema.

    Raises ``ArgumentValidationError`` if:
    - a mandatory argument is absent from both *values* and *files*; or
    - an argument name is supplied that is not in *schema* (only when schema is
      non-empty — an empty schema disables unknown-argument checking).

    Does nothing if *schema* is empty.
    """
    if not schema:
        return

    supplied = set(values) | set(files)
    known = {s.name for s in schema}

    missing = [s.name for s in schema if s.mandatory and s.name not in supplied]
    unknown = [n for n in sorted(supplied) if n not in known]

    errors: list[str] = []
    if missing:
        errors.append(f"missing mandatory argument(s): {', '.join(missing)}")
    if unknown:
        errors.append(f"unknown argument(s): {', '.join(unknown)}")
    if errors:
        raise ArgumentValidationError("; ".join(errors))
