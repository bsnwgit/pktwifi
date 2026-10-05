"""
Builds the WHERE clause of a filtered query.

Every list endpoint here assembles one from optional filters: each filter adds
a fixed SQL fragment with `?` placeholders and the values to bind to them. Doing
that by hand means keeping two lists in step; `Where` keeps them together and
refuses a fragment whose placeholders do not match its values. Only fragments
written in the source may be added — a value from a request goes in `params`,
never into the fragment.
"""
from __future__ import annotations

from typing import Any


class Where:
    def __init__(self) -> None:
        self._clauses: list[str] = []
        self.params: list[Any] = []

    def add(self, clause: str, *params: Any) -> None:
        if clause.count("?") != len(params):
            raise ValueError(f"{clause!r} has {clause.count('?')} placeholder(s) but {len(params)} value(s)")
        self._clauses.append(clause)
        self.params.extend(params)

    @property
    def sql(self) -> str:
        """`WHERE a AND b`, or an empty string when nothing was added."""
        return ("WHERE " + " AND ".join(self._clauses)) if self._clauses else ""

    def with_params(self, *extra: Any) -> list[Any]:
        """The bound values followed by more (LIMIT, OFFSET), without
        changing this builder."""
        return [*self.params, *extra]
