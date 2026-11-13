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
