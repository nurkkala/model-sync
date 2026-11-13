from __future__ import annotations

import pytest

from model_sync import jsonc

TEXT = """{
  // leading comment
  "a": { "x": 1, "y": [1, 2,], }, /* block */
  "b": "has // no comment and a \\" quote",
  "c": null
}
"""


def test_parse_reads_comments_trailing_commas_and_strings():
    root = jsonc.parse(TEXT)
    assert root.value == {
        "a": {"x": 1, "y": [1, 2]},
        "b": 'has // no comment and a " quote',
        "c": None,
    }


def test_a_node_spans_exactly_its_own_source():
    root = jsonc.parse(TEXT)
    node = root.find("a", "y")
    assert TEXT[node.start : node.end] == "[1, 2,]"
    text = root.find("b")
    assert TEXT[text.start : text.end] == '"has // no comment and a \\" quote"'
    assert root.find("a", "missing") is None
    assert root.find("b", "deeper") is None


def test_replace_value_leaves_every_other_character_alone():
    root = jsonc.parse(TEXT)
    edited = jsonc.replace_value(TEXT, root.find("a"), '{ "z": 9 }')
    assert edited == TEXT.replace('{ "x": 1, "y": [1, 2,], }', '{ "z": 9 }')
    assert jsonc.parse(edited).value["a"] == {"z": 9}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # No trailing comma: the comma goes after the value, ahead of its line comment.
        (
            '{\n  "a": 1 // note\n}\n',
            '{\n  "a": 1, // note\n  "k": 2\n}\n',
        ),
        # A trailing comma is kept as the file's style.
        ('{\n    "a": 1,\n}\n', '{\n    "a": 1,\n    "k": 2,\n}\n'),
        # An empty object on one line opens up.
        ('{ "p": {} }', None),
        ("{}", '{\n  "k": 2\n}'),
        # The closing brace shares a line with the last member.
        ('{ "a": 1 }', '{ "a": 1,\n  "k": 2\n}'),
    ],
)
def test_insert_member(text, expected):
    edited = jsonc.insert_member(text, jsonc.parse(text), "k", "2")
    if expected is not None:
        assert edited == expected
    value = jsonc.parse(edited).value
    assert value["k"] == 2
    assert list(value)[-1] == "k"
    assert {key: item for key, item in value.items() if key != "k"} == jsonc.parse(
        text
    ).value


def test_insert_into_a_nested_object_uses_its_members_indent():
    text = '{\n  "p": {\n      "a": 1\n  }\n}\n'
    root = jsonc.parse(text)
    edited = jsonc.insert_member(text, root.find("p"), "k", "2")
    assert edited == '{\n  "p": {\n      "a": 1,\n      "k": 2\n  }\n}\n'


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{\n  "a": 1\n  "b": 2\n}', "line 3: expected ',' or '}'"),
        ('{\n "a": nope }', "line 2: unexpected text"),
        ('{ "a": 1 } x', "text after the end"),
        ("{ /* open", "unterminated comment"),
        ('{ "a": ', "unexpected end of file"),
    ],
)
def test_malformed_text_is_refused_with_its_line(text, message):
    with pytest.raises(jsonc.JsoncError, match=message.replace("'", ".")):
        jsonc.parse(text)


@pytest.mark.parametrize(
    ("source", "path", "expected"),
    [
        # A middle member on its own line goes with its line and its closing comment.
        (
            '{\n  "a": 1,\n  "b": 2, // about b\n  "c": 3\n}\n',
            ("b",),
            '{\n  "a": 1,\n  "c": 3\n}\n',
        ),
        # The last member has no comma, so the one before it gives its own up.
        ('{\n  "a": 1,\n  "b": 2\n}\n', ("b",), '{\n  "a": 1\n}\n'),
        # A trailing comma after the last member is the member's own.
        ('{\n  "a": 1,\n  "b": 2,\n}\n', ("b",), '{\n  "a": 1,\n}\n'),
        # A comment on a line of its own stays where it is.
        (
            '{\n  // about a\n  "a": 1,\n  // about b\n  "b": 2\n}\n',
            ("a",),
            '{\n  // about a\n  // about b\n  "b": 2\n}\n',
        ),
        # The comment that closes the previous member's line survives.
        (
            '{\n  "a": 1, // about a\n  "b": 2\n}\n',
            ("b",),
            '{\n  "a": 1 // about a\n}\n',
        ),
        # Inline: first, middle, last, and the one member there is.
        ('{ "a": 1, "b": 2, "c": 3 }', ("a",), '{ "b": 2, "c": 3 }'),
        ('{ "a": 1, "b": 2, "c": 3 }', ("b",), '{ "a": 1, "c": 3 }'),
        ('{ "a": 1, "b": 2, "c": 3 }', ("c",), '{ "a": 1, "b": 2 }'),
        ('{ "a": 1 }', ("a",), "{ }"),
        # Nested, and a value that spans lines.
        (
            '{\n  "x": { "keep": true, "model": "p/m" },\n  "y": {\n    "z": 1\n  }\n}\n',
            ("x", "model"),
            '{\n  "x": { "keep": true },\n  "y": {\n    "z": 1\n  }\n}\n',
        ),
        (
            '{\n  "x": 1,\n  "y": {\n    "z": 1\n  }\n}\n',
            ("y",),
            '{\n  "x": 1\n}\n',
        ),
    ],
)
def test_remove_member_takes_the_comma_and_leaves_valid_text(source, path, expected):
    root = jsonc.parse(source)
    parent = root.find(*path[:-1])
    result = jsonc.remove_member(source, parent, path[-1])
    assert result == expected
    jsonc.parse(result)
