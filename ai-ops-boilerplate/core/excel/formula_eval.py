"""Excel-formula → Python evaluation (hybrid, in-house).

Operators author Excel formulas in the rules file; the framework evaluates them
in Python so the *value* is authoritative in the data model, while the live
formula string is still written to the cell for the operator. This module is
that evaluator.

A design spike confirmed:

* an in-house AST-safe evaluator handles the row-local subset with no new
  dependencies and survives dirty cells; and
* the ``formulas`` library pulls heavy deps (scipy), emits SyntaxWarnings, and
  still needs a full workbook model for cross-sheet VLOOKUP — so it is **not**
  adopted. It can be slotted in later behind :class:`FormulaEvaluator` if ever
  needed.

Contract: the evaluator works on **Excel-letter-keyed, already-typed** frames
(columns named ``"A"``, ``"B"``, ``"P"`` …). Typing/coercion is the model's job;
the evaluator just computes. ``{row}`` in a template means "this row".

Supported v1 backends:

* :class:`RowLocalEvaluator` — IF / arithmetic / comparison / ROUND / ABS / …
* :class:`LookupEvaluator`   — ``VLOOKUP(key, 'Sheet'!C1:C2, idx, 0)`` → merge
* :class:`AggregateEvaluator`— ``SUM`` / ``SUBTOTAL(9, …)`` → column sum
"""

from __future__ import annotations

import ast
import enum
import re
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd
from openpyxl.utils import column_index_from_string, get_column_letter

from . import coerce
from .errors import FormulaEvalError


class FormulaClass(enum.Enum):
    ROW_LOCAL = "row_local"
    LOOKUP = "lookup"
    AGGREGATE = "aggregate"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ColumnMap:
    """Resolution context for a formula.

    ``sheet_frames`` maps a sheet name to its Excel-letter-keyed DataFrame, used
    to resolve cross-sheet lookups (e.g. ``'GL Dump'!P:S``).
    """

    sheet_frames: dict[str, pd.DataFrame] = field(default_factory=dict)


# ── template helpers ─────────────────────────────────────────────────────────
def apply_template(template: str, row: int) -> str:
    """Substitute ``{row}`` in a formula template with a concrete row number."""
    return template.replace("{row}", str(row))


def col_to_index(letter: str) -> int:
    """Excel column letter → 1-based index ('A'→1, 'AA'→27)."""
    return column_index_from_string(letter)


def index_to_col(index: int) -> str:
    """1-based index → Excel column letter (1→'A', 27→'AA')."""
    return get_column_letter(index)


# Matches a same-row cell reference: U{row}, T{row}, AA{row}
_ROW_CELL_RE = re.compile(r"(?<![A-Za-z0-9_'])([A-Z]{1,3})\{row\}")
# Matches any A1 cell ref with an absolute row number: H1, AA12
_ABS_CELL_RE = re.compile(r"(?<![A-Za-z0-9_'!])([A-Z]{1,3})(\d+)")
# Function names appearing as NAME(
_FUNC_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")

_VLOOKUP_RE = re.compile(
    r"^VLOOKUP\(\s*(?P<key>[A-Z]{1,3}\{row\})\s*,\s*"
    r"(?:'(?P<sheet>[^']+)'|(?P<sheet2>[A-Za-z0-9_]+))!"
    r"(?P<c1>[A-Z]{1,3}):(?P<c2>[A-Z]{1,3})\s*,\s*"
    r"(?P<idx>\d+)\s*,\s*(?P<exact>0|FALSE)\s*\)$",
    re.IGNORECASE,
)
_AGG_RE = re.compile(
    r"^(?:SUM\(|SUBTOTAL\(\s*9\s*,)\s*"
    r"(?:'[^']+'!)?(?P<c1>[A-Z]{1,3})\d+:(?P<c2>[A-Z]{1,3})\d+\s*\)$",
    re.IGNORECASE,
)

_ALLOWED_ROW_FUNCS = {"IF", "ROUND", "ABS", "AND", "OR", "NOT", "MIN", "MAX"}


def _strip(formula: str) -> str:
    return formula.lstrip("=").strip()


# ── AST-safe row-local evaluator ─────────────────────────────────────────────
def _num(x):
    """Coerce a Series/scalar to numeric for arithmetic, leaving numbers alone."""
    if isinstance(x, pd.Series):
        if pd.api.types.is_numeric_dtype(x):
            return x
        return x.map(coerce.to_number)
    if isinstance(x, (int, float, np.number)):
        return x
    return coerce.to_number(x)


class _SafeRowEval(ast.NodeVisitor):
    """Evaluate a whitelisted expression over Excel-letter column Series."""

    _FUNCS = {
        "IF": lambda c, a, b: np.where(c, a, b),
        "ROUND": lambda x, n=0: np.round(_num(x), coerce.to_int(n, 0)),
        "ABS": lambda x: np.abs(_num(x)),
        "AND": lambda *a: np.logical_and.reduce(a),
        "OR": lambda *a: np.logical_or.reduce(a),
        "NOT": np.logical_not,
        "MIN": lambda *a: np.minimum.reduce([_num(x) for x in a]),
        "MAX": lambda *a: np.maximum.reduce([_num(x) for x in a]),
    }

    def __init__(self, env: dict[str, pd.Series]):
        self.env = env

    def visit(self, node):  # noqa: C901 - a small, explicit dispatch table
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.env:
                return self.env[node.id]
            raise FormulaEvalError(f"unknown cell reference: {node.id}")
        if isinstance(node, ast.UnaryOp):
            v = self.visit(node.operand)
            if isinstance(node.op, ast.USub):
                return -_num(v)
            if isinstance(node.op, ast.UAdd):
                return +_num(v)
            raise FormulaEvalError("unsupported unary operator")
        if isinstance(node, ast.BinOp):
            left, right = _num(self.visit(node.left)), _num(self.visit(node.right))
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            raise FormulaEvalError("unsupported arithmetic operator")
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise FormulaEvalError("chained comparisons are not supported")
            left = self.visit(node.left)
            right = self.visit(node.comparators[0])
            op = node.ops[0]
            # Numeric comparison when either side is a numeric literal/series.
            if _is_numeric_compare(op, left, right):
                left, right = _num(left), _num(right)
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.Lt):
                return left < right
            if isinstance(op, ast.LtE):
                return left <= right
            if isinstance(op, ast.Gt):
                return left > right
            if isinstance(op, ast.GtE):
                return left >= right
            raise FormulaEvalError("unsupported comparison operator")
        if isinstance(node, ast.BoolOp):
            vals = [self.visit(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return np.logical_and.reduce(vals)
            return np.logical_or.reduce(vals)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaEvalError("only named function calls are allowed")
            fname = node.func.id.upper()
            if fname not in self._FUNCS:
                raise FormulaEvalError(f"unsupported function: {fname}")
            return self._FUNCS[fname](*[self.visit(a) for a in node.args])
        raise FormulaEvalError(f"unsupported syntax: {type(node).__name__}")


def _is_numeric_compare(op, left, right) -> bool:
    if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
        return True
    # Eq/NotEq: numeric only if neither side is a string literal.
    return not isinstance(left, str) and not isinstance(right, str)


_STR_LITERAL_RE = re.compile(r'"(?:[^"]|"")*"')


def _to_pyexpr(formula: str) -> str:
    body = _strip(formula)
    # Mask double-quoted string literals so the operator/cell-ref transforms below
    # never rewrite characters *inside* a string (e.g. ="a=b" or a "<>" in text).
    literals: list[str] = []

    def _mask(m: re.Match) -> str:
        literals.append(m.group(0))
        return f"\x00{len(literals) - 1}\x00"

    body = _STR_LITERAL_RE.sub(_mask, body)
    body = _ROW_CELL_RE.sub(lambda m: f"col_{m.group(1)}", body)
    body = body.replace("<>", "!=")
    body = re.sub(r"(?<![<>=!])=(?!=)", "==", body)  # Excel '=' → Python '=='
    for i, lit in enumerate(literals):
        body = body.replace(f"\x00{i}\x00", lit)
    return body


class FormulaEvaluator(Protocol):
    def supports(self, formula: str) -> bool: ...
    def eval_column(
        self, formula: str, frame: pd.DataFrame, colmap: ColumnMap, *, sheet_name: str
    ) -> pd.Series: ...


class RowLocalEvaluator:
    """Same-row scalar formulas: IF / arithmetic / comparison / ROUND / ABS."""

    def supports(self, formula: str) -> bool:
        body = _strip(formula)
        if _ABS_CELL_RE.search(body):  # absolute-row refs ⇒ not row-local
            return False
        if "{row}" not in body and not _looks_constant(body):
            return False
        funcs = {m.group(1).upper() for m in _FUNC_RE.finditer(body)}
        return funcs <= _ALLOWED_ROW_FUNCS

    def eval_column(self, formula, frame, colmap, *, sheet_name):
        cols = {m.group(1) for m in _ROW_CELL_RE.finditer(_strip(formula))}
        env: dict[str, pd.Series] = {}
        for col in cols:
            if col not in frame.columns:
                raise FormulaEvalError(
                    f"column {col!r} not present on sheet {sheet_name!r}",
                    formula=formula,
                )
            env[f"col_{col}"] = frame[col]
        tree = ast.parse(_to_pyexpr(formula), mode="eval")
        result = _SafeRowEval(env).visit(tree)
        if np.ndim(result) == 0:
            result = pd.Series([result] * len(frame), index=frame.index)
        return pd.Series(np.asarray(result), index=frame.index)


class LookupEvaluator:
    """``VLOOKUP(key,'Sheet'!C1:C2,idx,0)`` (exact match) → pandas merge/map."""

    def supports(self, formula: str) -> bool:
        return bool(_VLOOKUP_RE.match(_strip(formula)))

    def eval_column(self, formula, frame, colmap, *, sheet_name):
        m = _VLOOKUP_RE.match(_strip(formula))
        if not m:
            raise FormulaEvalError("malformed VLOOKUP", formula=formula)
        # Column letters are case-insensitive in Excel; frames are keyed by
        # upper-case letters, so normalise (the regex is IGNORECASE).
        key_col = m.group("key").split("{")[0].upper()
        sheet = m.group("sheet") or m.group("sheet2")
        c1, c2, idx = m.group("c1").upper(), m.group("c2").upper(), int(m.group("idx"))
        return_col = index_to_col(col_to_index(c1) + idx - 1)
        if col_to_index(return_col) > col_to_index(c2):
            raise FormulaEvalError(
                f"VLOOKUP index {idx} is outside the range {c1}:{c2}",
                formula=formula,
            )
        if sheet not in colmap.sheet_frames:
            raise FormulaEvalError(
                f"lookup sheet {sheet!r} not provided to the evaluator",
                formula=formula,
            )
        target = colmap.sheet_frames[sheet]
        for needed in (c1, return_col):
            if needed not in target.columns:
                raise FormulaEvalError(
                    f"column {needed!r} not present on lookup sheet {sheet!r}",
                    formula=formula,
                )
        # Exact-match VLOOKUP returns the FIRST match (drop later duplicates).
        lookup = target[[c1, return_col]].drop_duplicates(subset=c1, keep="first")
        mapping = dict(zip(lookup[c1], lookup[return_col]))
        if key_col not in frame.columns:
            raise FormulaEvalError(
                f"lookup key column {key_col!r} not present on sheet {sheet_name!r}",
                formula=formula,
            )
        return frame[key_col].map(mapping)


class AggregateEvaluator:
    """``SUM(C1:C2)`` / ``SUBTOTAL(9, C1:C2)`` → sum of the column, broadcast.

    Per-group sums (e.g. a reconciliation group total) are a *model* concern —
    register a Computed strategy for those rather than expressing grouping in a
    flat Excel range.
    """

    def supports(self, formula: str) -> bool:
        return bool(_AGG_RE.match(_strip(formula)))

    def eval_column(self, formula, frame, colmap, *, sheet_name):
        m = _AGG_RE.match(_strip(formula))
        if not m:
            raise FormulaEvalError("malformed aggregate", formula=formula)
        c1, c2 = m.group("c1").upper(), m.group("c2").upper()
        if c1 != c2:
            raise FormulaEvalError(
                "aggregate over a multi-column range is not supported",
                formula=formula,
            )
        if c1 not in frame.columns:
            raise FormulaEvalError(
                f"column {c1!r} not present on sheet {sheet_name!r}", formula=formula
            )
        total = float(frame[c1].map(coerce.to_number).sum())
        return pd.Series([total] * len(frame), index=frame.index)


def _looks_constant(body: str) -> bool:
    """A formula with no cell refs at all (e.g. ``=1`` or ``="x"``)."""
    return not _ROW_CELL_RE.search(body) and not _ABS_CELL_RE.search(body)


class HybridEvaluator:
    """Tries each backend in order; the first that ``supports`` the formula wins."""

    def __init__(self, backends: list[FormulaEvaluator] | None = None) -> None:
        self.backends: list[FormulaEvaluator] = backends or [
            RowLocalEvaluator(),
            LookupEvaluator(),
            AggregateEvaluator(),
        ]

    def classify(self, formula: str) -> FormulaClass:
        body = _strip(formula)
        if _VLOOKUP_RE.match(body):
            return FormulaClass.LOOKUP
        if _AGG_RE.match(body):
            return FormulaClass.AGGREGATE
        if RowLocalEvaluator().supports(formula):
            return FormulaClass.ROW_LOCAL
        return FormulaClass.UNSUPPORTED

    def supports(self, formula: str) -> bool:
        return any(b.supports(formula) for b in self.backends)

    def eval_column(
        self, formula: str, frame: pd.DataFrame, colmap: ColumnMap, *, sheet_name: str
    ) -> pd.Series:
        for backend in self.backends:
            if backend.supports(formula):
                return backend.eval_column(
                    formula, frame, colmap, sheet_name=sheet_name
                )
        raise FormulaEvalError(
            "no backend supports this formula; the supported set is row-local "
            "scalars (IF/arithmetic/ROUND/ABS), exact-match VLOOKUP, and "
            "SUM/SUBTOTAL(9,...) over one column",
            formula=formula,
        )
