"""A Lua tokenizer and a data-only Lua table reader.

Downloaded Blizzard files and SavedVariables are read as data here. They are
never executed, so a hostile file cannot run code on the developer machine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class LuaSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str  # name | string | number | op | eof
    value: str
    line: int


TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<longcomment>--\[(?P<lc>=*)\[.*?\](?P=lc)\])
  | (?P<comment>--[^\n]*)
  | (?P<longstring>\[(?P<ls>=*)\[.*?\](?P=ls)\])
  | (?P<string>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
  | (?P<number>0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\.\.|\.\.|==|~=|<=|>=|<<|>>|//|::|[-+*/%^\#<>=(){}\[\];:,.&|~])
    """,
    re.S | re.X,
)

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
           "\\": "\\", '"': '"', "'": "'", "\n": "\n"}
ESCAPE_RE = re.compile(r"\\(\d{1,3}|.)", re.S)


def _unescape(body: str) -> str:
    def repl(m: re.Match) -> str:
        g = m.group(1)
        if g.isdigit():
            return chr(int(g))
        return ESCAPES.get(g, g)
    return ESCAPE_RE.sub(repl, body)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    text = text.removeprefix("\ufeff")
    pos, line, end = 0, 1, len(text)
    if text.startswith("#!"):
        pos = text.find("\n")
        pos = end if pos < 0 else pos
    while pos < end:
        m = TOKEN_RE.match(text, pos)
        if m is None:
            raise LuaSyntaxError(f"line {line}: unexpected character {text[pos]!r}")
        kind = m.lastgroup
        raw = m.group(0)
        if kind in ("lc", "ls"):  # a nested named group can be lastgroup
            kind = "longcomment" if raw.startswith("--") else "longstring"
        if kind in ("name", "number", "op"):
            tokens.append(Token(kind, raw, line))
        elif kind == "string":
            tokens.append(Token("string", _unescape(raw[1:-1]), line))
        elif kind == "longstring":
            n = raw.index("[", 1) + 1
            tokens.append(Token("string", raw[n:-n], line))
        line += raw.count("\n")
        pos = m.end()
    tokens.append(Token("eof", "", line))
    return tokens


BINARY_OPS = {"+", "-", "*", "/", "%", "^", "..", "==", "~=", "<", ">", "<=", ">="}


class Ref(str):
    """An expression that is not plain data, for example Enum.Foo.Bar."""


class _Reader:
    def __init__(self, tokens: list[Token]):
        self.t = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.t[self.i]

    def take(self) -> Token:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def at(self, value: str) -> bool:
        tok = self.peek()
        return tok.kind == "op" and tok.value == value

    def accept(self, value: str) -> bool:
        if self.at(value):
            self.i += 1
            return True
        return False

    def expect(self, value: str) -> None:
        if not self.accept(value):
            tok = self.peek()
            raise LuaSyntaxError(f"line {tok.line}: expected {value!r}, found {tok.value!r}")

    def value(self):
        """Read one value. A computed expression becomes an opaque Ref."""
        first = self._atom()
        tok = self.peek()
        if tok.kind == "op" and tok.value in BINARY_OPS or tok.kind == "name" and tok.value in ("and", "or"):
            depth = 0
            while True:
                tok = self.peek()
                if tok.kind == "eof":
                    break
                if tok.kind == "op" and tok.value in "([{":
                    depth += 1
                elif tok.kind == "op" and tok.value in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and tok.kind == "op" and tok.value in ",;":
                    break
                self.take()
            return Ref("<expression>")
        return first

    def _atom(self):
        tok = self.peek()
        if tok.kind == "op" and tok.value == "{":
            return self.table()
        if tok.kind == "op" and tok.value == "-":
            self.take()
            return -self._number(self.take())
        if tok.kind == "string":
            self.take()
            return tok.value
        if tok.kind == "number":
            self.take()
            return self._number(tok)
        if tok.kind == "name":
            self.take()
            if tok.value == "true":
                return True
            if tok.value == "false":
                return False
            if tok.value == "nil":
                return None
            return self._reference(tok.value)
        raise LuaSyntaxError(f"line {tok.line}: unexpected {tok.value!r} in data")

    @staticmethod
    def _number(tok: Token):
        if tok.kind != "number":
            raise LuaSyntaxError(f"line {tok.line}: expected a number")
        if tok.value[:2].lower() == "0x":
            return int(tok.value, 16)
        num = float(tok.value)
        return int(num) if num.is_integer() and "." not in tok.value and "e" not in tok.value.lower() else num

    def _reference(self, name: str) -> Ref:
        parts = [name]
        while self.at(".") or self.at(":"):
            self.take()
            parts.append(self.take().value)
        if self.at("("):
            self._skip_balanced("(", ")")
        return Ref(".".join(parts))

    def _skip_balanced(self, opener: str, closer: str) -> None:
        depth = 0
        while True:
            tok = self.take()
            if tok.kind == "eof":
                raise LuaSyntaxError("unbalanced expression")
            if tok.kind == "op" and tok.value == opener:
                depth += 1
            elif tok.kind == "op" and tok.value == closer:
                depth -= 1
                if depth == 0:
                    return

    def table(self):
        self.expect("{")
        array: list = []
        keyed: dict = {}
        while not self.at("}"):
            tok = self.peek()
            if tok.kind == "op" and tok.value == "[":
                self.take()
                key = self.value()
                self.expect("]")
                self.expect("=")
                keyed[key] = self.value()
            elif tok.kind == "name" and self.t[self.i + 1].value == "=" \
                    and self.t[self.i + 1].kind == "op":
                self.i += 2
                keyed[tok.value] = self.value()
            else:
                array.append(self.value())
            if not (self.accept(",") or self.accept(";")):
                break
        self.expect("}")
        if keyed and array:
            for index, item in enumerate(array, 1):
                keyed.setdefault(index, item)
            return keyed
        return keyed if keyed else array


def parse_top_level_tables(text: str) -> dict:
    """Return every top-level `[local] NAME = <table or scalar>` assignment.

    Tokens that are not assignments are skipped. That covers trailing calls
    such as APIDocumentation:AddDocumentationTable(X).
    """
    reader = _Reader(tokenize(text))
    out: dict = {}
    while reader.peek().kind != "eof":
        tok = reader.peek()
        following = reader.t[reader.i + 1] if reader.i + 1 < len(reader.t) else tok
        if tok.kind == "name" and following.kind == "op" and following.value == "=":
            reader.i += 2
            out[tok.value] = reader.value()
        else:
            reader.take()
    return out


def parse_saved_variables(text: str) -> dict:
    """Parse a WoW SavedVariables file."""
    return parse_top_level_tables(text)
