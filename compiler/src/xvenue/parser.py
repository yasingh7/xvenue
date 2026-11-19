"""Recursive-descent parser for the RDSL v0 grammar in ``compiler/RDSL.md``.

A file is a sequence of contracts. Comments are ``//`` to end of line.
Identifiers are a single token, so ``bls.cpi_u_yoy`` and ``America/New_York``
are written without spaces. The parser returns :class:`ResolutionSpec` values
whose windows are already UTC unix seconds.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn

from xvenue.errors import RDSLError, TemporalError
from xvenue.spec import OPS, REVISIONS, ResolutionSpec, canonical_cmp
from xvenue.temporal import absolute_to_utc, civil_to_utc, split_timestamp

_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?")
_NUM = re.compile(r"\d+(?:\.\d+)?[A-Za-z]*")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_./+-]*")
_SIMPLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUM_PARTS = re.compile(r"(\d+(?:\.\d+)?)([A-Za-z]+)?")

_FIELDS = ("observe", "window", "predicate", "revision", "void_if", "dispute")
_FIELD_SET = set(_FIELDS)
_OPS = set(OPS)


class _Tok:
    __slots__ = ("kind", "text", "line", "col")

    def __init__(self, kind: str, text: str, line: int, col: int) -> None:
        self.kind = kind
        self.text = text
        self.line = line
        self.col = col


def parse_path(path: str | Path) -> tuple[ResolutionSpec, ...]:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RDSLError(
            f"file is not valid UTF-8 ({exc.reason})",
            path=str(file),
            line=1,
            column=1,
        ) from exc
    return parse_rdsl(text, path=str(file))


def parse_rdsl(text: str, path: str | None = None) -> tuple[ResolutionSpec, ...]:
    if text.startswith("\ufeff"):
        text = text[1:]
    parser = _Parser(text, path)
    return parser.parse_file()


class _Parser:
    def __init__(self, text: str, path: str | None) -> None:
        self.path = path
        self.lines = text.splitlines()
        self.toks = _lex(text, path, self.lines)
        self.i = 0

    def parse_file(self) -> tuple[ResolutionSpec, ...]:
        specs: list[ResolutionSpec] = []
        seen: dict[str, _Tok] = {}
        while self.peek().kind != "EOF":
            spec, id_tok = self.parse_contract()
            if spec.contract_id in seen:
                self._error(f"duplicate contract id {spec.contract_id!r}", id_tok)
            seen[spec.contract_id] = id_tok
            specs.append(spec)
        if not specs:
            self._error("no contracts in file")
        return tuple(specs)

    def parse_contract(self) -> tuple[ResolutionSpec, _Tok]:
        self._expect_word("contract")
        id_tok = self._expect("WORD", what="a contract id")
        self._expect_word("on")
        venue = self._expect("WORD", what="a venue").text
        self._expect_punct("{")
        fields: dict[str, dict] = {}
        while not (self.peek().kind == "PUNCT" and self.peek().text == "}"):
            if self.peek().kind == "EOF":
                self._error("unclosed contract; expected '}'")
            name_tok = self._expect("WORD", what="a field name")
            name = name_tok.text
            if name not in _FIELD_SET:
                self._error(f"unknown field {name!r}", name_tok)
            if name in fields:
                self._error(f"duplicate field {name!r}", name_tok)
            fields[name] = self._parse_field(name)
        self._expect_punct("}")
        missing = [name for name in _FIELDS if name not in fields]
        if missing:
            listed = ", ".join(missing)
            self._error(f"contract {id_tok.text!r} is missing {listed}", id_tok)
        observe = fields["observe"]
        predicate = fields["predicate"]
        self._check_predicate(observe["alias"], predicate)
        window = fields["window"]
        revision = fields["revision"]
        spec = ResolutionSpec(
            contract_id=id_tok.text,
            venue=venue,
            source=observe["source"],
            alias=observe["alias"],
            predicate_ref=predicate["ref"],
            op=predicate["op"],
            threshold=predicate["threshold"],
            threshold_unit=predicate["unit"],
            predicate_lexeme=predicate["lexeme"],
            t0=window["t0"],
            t1=window["t1"],
            tz=window["tz"],
            revision=revision["policy"],
            revision_at=revision["at"],
            void_if=fields["void_if"]["conds"],
            dispute=fields["dispute"]["path"],
        )
        return spec, id_tok

    def _parse_field(self, name: str) -> dict:
        if name == "observe":
            return self._parse_observe()
        if name == "window":
            return self._parse_window()
        if name == "predicate":
            return self._parse_cmp()
        if name == "revision":
            return self._parse_revision()
        if name == "void_if":
            return self._parse_void()
        return self._parse_dispute()

    def _parse_observe(self) -> dict:
        src_tok = self._expect("WORD", what="<source>.<series>")
        source = src_tok.text
        if "." not in source:
            self._error("observe expects <source>.<series>", src_tok)
        alias = source.rsplit(".", 1)[1]
        if self.peek().kind == "WORD" and self.peek().text == "as":
            self._advance()
            alias_tok = self._expect("WORD", what="an alias")
            if _SIMPLE.fullmatch(alias_tok.text) is None:
                self._error("alias must be a simple name", alias_tok)
            alias = alias_tok.text
        return {"source": source, "alias": alias}

    def _parse_window(self) -> dict:
        self._expect_punct("[")
        start_tok = self._expect("TIMESTAMP", what="a start time")
        self._expect_punct(",")
        end_tok = self._expect("TIMESTAMP", what="an end time")
        self._expect_punct(")")
        self._expect_word("tz")
        tz_tok = self._expect("WORD", what="an IANA timezone")
        t0 = self._civil(start_tok, tz_tok)
        t1 = self._civil(end_tok, tz_tok)
        if t0 == t1:
            self._error("window is empty", start_tok)
        if t1 < t0:
            self._error("window ends before it starts", start_tok)
        return {"t0": t0, "t1": t1, "tz": tz_tok.text}

    def _civil(self, tok: _Tok, tz_tok: _Tok) -> int:
        try:
            naive, offset = split_timestamp(tok.text)
        except TemporalError as exc:
            self._error(str(exc), tok)
        if offset is not None:
            self._error(
                "window bounds are civil times; put the zone in the tz clause, not on the timestamp",
                tok,
            )
        try:
            return civil_to_utc(naive, tz_tok.text)
        except TemporalError as exc:
            loc = tz_tok if exc.code == "timezone" else tok
            self._error(str(exc), loc)

    def _parse_cmp(self) -> dict:
        ref_tok = self._expect("WORD", what="a reference")
        op_tok = self._expect("OP", what="a comparison operator")
        if op_tok.text not in _OPS:
            self._error(f"unsupported comparison {op_tok.text!r}", op_tok)
        lexeme, threshold, unit = self._parse_number()
        return {
            "ref": ref_tok.text,
            "op": op_tok.text,
            "threshold": threshold,
            "unit": unit,
            "lexeme": lexeme,
        }

    def _parse_number(self) -> tuple[str, float, str | None]:
        sign = 1
        sign_text = ""
        if self.peek().kind == "PUNCT" and self.peek().text == "-":
            self._advance()
            sign = -1
            sign_text = "-"
        num_tok = self._expect("NUMBER", what="a number")
        match = _NUM_PARTS.fullmatch(num_tok.text)
        if match is None:
            self._error(f"invalid number {num_tok.text!r}", num_tok)
        lexeme = sign_text + match.group(1)
        unit = match.group(2)
        return lexeme, sign * float(match.group(1)), unit

    def _parse_revision(self) -> dict:
        policy_tok = self._expect("WORD", what="a revision policy")
        policy = policy_tok.text
        if policy in ("first_print", "final"):
            return {"policy": policy, "at": None}
        if policy != "latest_before":
            allowed = ", ".join(REVISIONS)
            self._error(f"unknown revision {policy!r}; expected {allowed}", policy_tok)
        self._expect_punct("(")
        ts_tok = self._expect("TIMESTAMP", what="a timestamp")
        self._expect_punct(")")
        try:
            naive, offset = split_timestamp(ts_tok.text)
        except TemporalError as exc:
            self._error(str(exc), ts_tok)
        if offset is None:
            self._error("latest_before timestamp needs a UTC offset or Z", ts_tok)
        try:
            at = absolute_to_utc(naive, offset)
        except TemporalError as exc:
            self._error(str(exc), ts_tok)
        return {"policy": "latest_before", "at": at}

    def _parse_void(self) -> dict:
        if self.peek().kind == "WORD" and self.peek().text == "none":
            nxt = self.toks[self.i + 1]
            if nxt.kind != "OP":
                self._advance()
                return {"conds": ()}
        conds = [self._void_one()]
        while self.peek().kind == "PUNCT" and self.peek().text == ",":
            self._advance()
            conds.append(self._void_one())
        canon = tuple(sorted({item["canon"] for item in conds}))
        return {"conds": canon}

    def _void_one(self) -> dict:
        cmp = self._parse_cmp()
        canon = canonical_cmp(cmp["ref"], cmp["op"], cmp["threshold"], cmp["unit"])
        return {"canon": canon}

    def _parse_dispute(self) -> dict:
        path = self._expect("WORD", what="a dispute path").text
        return {"path": path}

    def _check_predicate(self, alias: str, predicate: dict) -> None:
        ref = predicate["ref"]
        prefix = alias + "."
        if not ref.startswith(prefix) or _SIMPLE.fullmatch(ref[len(prefix) :]) is None:
            self._error(
                f"predicate must look like {alias}.<field> <op> <number>, got {ref!r}"
            )

    def peek(self) -> _Tok:
        return self.toks[self.i]

    def _advance(self) -> _Tok:
        tok = self.toks[self.i]
        if tok.kind != "EOF":
            self.i += 1
        return tok

    def _expect(self, kind: str, what: str) -> _Tok:
        tok = self.peek()
        if tok.kind != kind:
            got = "end of file" if tok.kind == "EOF" else f"{tok.text!r}"
            self._error(f"expected {what}, got {got}", tok)
        return self._advance()

    def _expect_word(self, text: str) -> _Tok:
        tok = self.peek()
        if tok.kind != "WORD" or tok.text != text:
            got = "end of file" if tok.kind == "EOF" else f"{tok.text!r}"
            self._error(f"expected '{text}', got {got}", tok)
        return self._advance()

    def _expect_punct(self, text: str) -> _Tok:
        tok = self.peek()
        if tok.kind != "PUNCT" or tok.text != text:
            got = "end of file" if tok.kind == "EOF" else f"{tok.text!r}"
            self._error(f"expected '{text}', got {got}", tok)
        return self._advance()

    def _error(self, message: str, tok: _Tok | None = None) -> NoReturn:
        tok = tok or self.peek()
        source = self.lines[tok.line - 1] if 1 <= tok.line <= len(self.lines) else None
        raise RDSLError(
            message,
            path=self.path,
            line=tok.line,
            column=tok.col,
            source_line=source,
        )


def _lex(text: str, path: str | None, lines: list[str]) -> list[_Tok]:
    tokens: list[_Tok] = []
    i = 0
    line = 1
    line_start = 0
    n = len(text)

    def emit(kind: str, lexeme: str, at: int, at_line: int, at_start: int) -> None:
        tokens.append(_Tok(kind, lexeme, at_line, at - at_start + 1))

    def fail(message: str, at: int, at_line: int, at_start: int) -> None:
        source = lines[at_line - 1] if 1 <= at_line <= len(lines) else None
        raise RDSLError(
            message,
            path=path,
            line=at_line,
            column=at - at_start + 1,
            source_line=source,
        )

    while i < n:
        ch = text[i]
        if ch in " \t":
            i += 1
            continue
        if ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 2
            else:
                i += 1
            line += 1
            line_start = i
            continue
        if text.startswith("//", i):
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if text.startswith(("<=", ">=", "=="), i):
            emit("OP", text[i : i + 2], i, line, line_start)
            i += 2
            continue
        if ch in "<>":
            emit("OP", ch, i, line, line_start)
            i += 1
            continue
        if ch in "{}[](),-":
            emit("PUNCT", ch, i, line, line_start)
            i += 1
            continue
        matched = _TS.match(text, i)
        if matched:
            emit("TIMESTAMP", matched.group(0), i, line, line_start)
            i = matched.end()
            continue
        matched = _NUM.match(text, i)
        if matched:
            emit("NUMBER", matched.group(0), i, line, line_start)
            i = matched.end()
            continue
        matched = _WORD.match(text, i)
        if matched:
            emit("WORD", matched.group(0), i, line, line_start)
            i = matched.end()
            continue
        fail(f"unexpected character {ch!r}", i, line, line_start)
    tokens.append(_Tok("EOF", "", line, max(1, i - line_start + 1)))
    return tokens
