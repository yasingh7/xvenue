"""Parse and temporal errors with a source location."""

from __future__ import annotations


class RDSLError(Exception):
    """A problem in an RDSL file, or a window that cannot be placed on the civil clock."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        line: int = 1,
        column: int = 1,
        source_line: str | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.line = line
        self.column = column
        self.source_line = source_line
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.path:
            head = f"{self.path}:{self.line}:{self.column}: {self.message}"
        else:
            head = f"{self.line}:{self.column}: {self.message}"
        if self.source_line is None:
            return head
        caret_at = self.column if self.column >= 1 else 1
        caret = " " * (caret_at - 1) + "^"
        return f"{head}\n{self.source_line}\n{caret}"


class TemporalError(ValueError):
    """A timestamp or timezone that cannot be normalized. ``code`` selects the source span."""

    def __init__(self, message: str, *, code: str = "time") -> None:
        super().__init__(message)
        self.code = code
