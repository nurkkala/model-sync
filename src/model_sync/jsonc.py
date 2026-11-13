"""Read JSON with comments, and edit one value in it while leaving the other text alone.

A consumer file such as opencode's carries the owner's comments. Loading it and dumping
it back would delete every one, so the parser here records where each value sits in the
text, and the two editing functions splice new text into those spans.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


class JsoncError(ValueError):
    pass


@dataclass
class Member:
    key_start: int
    node: Node


@dataclass
class Node:
    """A parsed value: `text[start:end]` is its source, `value` its Python form."""

    start: int
    end: int
    value: Any
    # Objects only.
    members: dict[str, Member] = field(default_factory=dict)
    is_object: bool = False
    last_end: int = -1  # end of the last member's value
    trailing_comma: bool = False

    def find(self, *path: str) -> Node | None:
        node = self
        for key in path:
            if not node.is_object or key not in node.members:
                return None
            node = node.members[key].node
        return node


_SCALAR = re.compile(r"[^\s,\]}/]+")
_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def fail(self, message: str) -> JsoncError:
        line = self.text.count("\n", 0, self.pos) + 1
        return JsoncError(f"line {line}: {message}")

    def skip(self) -> None:
        text = self.text
        while self.pos < len(text):
            if text[self.pos].isspace():
                self.pos += 1
            elif text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = len(text) if end < 0 else end
            elif text.startswith("/*", self.pos):
                end = text.find("*/", self.pos + 2)
                if end < 0:
                    raise self.fail("unterminated comment")
                self.pos = end + 2
            else:
                return

    def peek(self) -> str:
        self.skip()
        if self.pos >= len(self.text):
            raise self.fail("unexpected end of file")
        return self.text[self.pos]

    def string(self) -> str:
        match = _STRING.match(self.text, self.pos)
        if not match:
            raise self.fail("malformed string")
        self.pos = match.end()
        return json.loads(match.group())

    def value(self) -> Node:
        char = self.peek()
        start = self.pos
        if char == "{":
            return self.object()
        if char == "[":
            self.pos += 1
            items = []
            while self.peek() != "]":
                items.append(self.value().value)
                if self.peek() == ",":
                    self.pos += 1
                elif self.peek() != "]":
                    raise self.fail("expected ',' or ']'")
            self.pos += 1
            return Node(start, self.pos, items)
        if char == '"':
            text = self.string()
            return Node(start, self.pos, text)
        match = _SCALAR.match(self.text, self.pos)
        try:
            scalar = json.loads(match.group()) if match else None
        except json.JSONDecodeError:
            match = None
        if not match:
            raise self.fail("unexpected text")
        self.pos = match.end()
        return Node(start, self.pos, scalar)

    def object(self) -> Node:
        node = Node(self.pos, -1, {}, is_object=True)
        self.pos += 1
        while self.peek() != "}":
            if self.peek() != '"':
                raise self.fail("expected a key")
            key_start = self.pos
            key = self.string()
            if self.peek() != ":":
                raise self.fail("expected ':'")
            self.pos += 1
            child = self.value()
            node.members[key] = Member(key_start, child)
            node.value[key] = child.value
            node.last_end = child.end
            node.trailing_comma = False
            if self.peek() == ",":
                self.pos += 1
                node.trailing_comma = True
            elif self.peek() != "}":
                raise self.fail("expected ',' or '}'")
        self.pos += 1
        node.end = self.pos
        return node


def parse(text: str) -> Node:
    parser = _Parser(text)
    root = parser.value()
    parser.skip()
    if parser.pos != len(text):
        raise parser.fail("text after the end of the document")
    return root


def line_indent(text: str, pos: int) -> str:
    """The whitespace that opens the line holding `pos`."""
    line_start = text.rfind("\n", 0, pos) + 1
    return re.match(r"[ \t]*", text[line_start:]).group()


def replace_value(text: str, node: Node, rendered: str) -> str:
    return text[: node.start] + rendered + text[node.end :]


def insert_member(text: str, parent: Node, key: str, rendered: str) -> str:
    """Add `"key": rendered` as the last member of the object `parent`."""
    close = parent.end - 1
    parent_indent = line_indent(text, parent.start)
    indent = parent_indent + "  "
    if parent.members:
        first = next(iter(parent.members.values()))
        # A first member on the brace's own line says nothing about indentation.
        if "\n" in text[parent.start : first.key_start]:
            indent = line_indent(text, first.key_start)
    member = f"{indent}{json.dumps(key)}: {rendered}"
    if parent.trailing_comma:
        member += ","
    # Put the member on a line of its own above the closing brace, opening one when the
    # brace shares its line with other text.
    brace_line = text.rfind("\n", 0, close) + 1
    if text[brace_line:close].strip():
        tail = f"\n{member}\n{parent_indent}" + text[close:]
        head = text[:close].rstrip(" \t")
    else:
        tail = f"{member}\n" + text[brace_line:]
        head = text[:brace_line]
    if parent.members and not parent.trailing_comma:
        # The comma goes directly after the last value, ahead of any comment on its line.
        head = head[: parent.last_end] + "," + head[parent.last_end :]
    return head + tail


def _comma_after(text: str, pos: int) -> int | None:
    """Where the comma that follows `pos` sits, past whitespace and comments; None if none."""
    parser = _Parser(text)
    parser.pos = pos
    parser.skip()
    return parser.pos if text.startswith(",", parser.pos) else None


def remove_member(text: str, parent: Node, key: str) -> str:
    """Delete the member `key` of the object `parent`, with its comma.

    A member that has lines to itself takes those lines with it, along with a `//`
    comment that closes its last line. A comment on a line of its own is left alone.
    """
    keys = list(parent.members)
    member = parent.members[key]
    start, end = member.key_start, member.node.end
    cuts: list[tuple[int, int]] = []

    comma = _comma_after(text, end)
    if comma is not None:
        if text[end:comma].strip():
            cuts.append((comma, comma + 1))  # a comment sits between; keep it
        else:
            end = comma + 1
    elif keys.index(key) > 0:
        # The last member carried no comma, so the one before it gives its own up.
        before = parent.members[keys[keys.index(key) - 1]].node.end
        previous = _comma_after(text, before)
        if previous is not None:
            if text[previous + 1 : start].strip():
                cuts.append((previous, previous + 1))
            else:
                start = previous

    line_start = text.rfind("\n", 0, start) + 1
    rest = re.match(r"[ \t]*(//[^\n]*)?", text[end:])
    line_end = end + rest.end()
    alone_before = not text[line_start:start].strip()
    at_line_end = line_end == len(text) or text[line_end] == "\n"
    if alone_before and at_line_end:
        cuts.append((line_start, min(line_end + 1, len(text))))
    elif at_line_end and text[start] == ",":
        # The member closed a line it shared with the previous one's value.
        cuts.append((start, line_end))
    else:
        # Inline among its siblings: take the spaces that followed it as well.
        cuts.append((start, end + len(re.match(r"[ \t]*", text[end:]).group())))
        if text[start] == "," and text[cuts[-1][1] : cuts[-1][1] + 1] == "}":
            text = text[: cuts[-1][1]] + " " + text[cuts[-1][1] :]

    for cut_start, cut_end in sorted(cuts, reverse=True):
        text = text[:cut_start] + text[cut_end:]
    return text
