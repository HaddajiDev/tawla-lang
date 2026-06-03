"""M32: JSON read (Json value + parseJson)."""

import pytest


def _main(body):
    return 'import "Json.twl"; class Main { void main() { ' + body + " } }"


def test_parse_int(run_twl):
    assert run_twl(_main('print(parseJson("42").asInt());')).stdout == "42\n"


def test_parse_float(run_twl):
    assert run_twl(_main('print(parseJson("3.5").asFloat());')).stdout == "3.5\n"


def test_parse_bool(run_twl):
    src = _main('if (parseJson("true").asBool()) { print(1); } else { print(0); }')
    assert run_twl(src).stdout == "1\n"


def test_parse_null(run_twl):
    src = _main('if (parseJson("null").isNull()) { print(1); }')
    assert run_twl(src).stdout == "1\n"


def test_parse_string(run_twl):
    assert run_twl(_main('print(parseJson("\\"hi\\"").asString());')).stdout == "hi\n"


def test_object_fields(run_twl):
    src = _main(
        'Json d = parseJson("{\\"name\\":\\"ada\\",\\"age\\":36}");'
        ' print(d.get("name").asString()); print(d.get("age").asInt());'
    )
    assert run_twl(src).stdout == "ada\n36\n"


def test_missing_key_is_null(run_twl):
    src = _main(
        'Json d = parseJson("{\\"a\\":1}");'
        ' if (d.get("b").isNull()) { print(1); }'
    )
    assert run_twl(src).stdout == "1\n"


def test_array_navigation(run_twl):
    src = _main(
        'Json d = parseJson("[10,20,30]");'
        ' print(d.size()); print(d.at(1).asInt());'
    )
    assert run_twl(src).stdout == "3\n20\n"


def test_array_of_objects(run_twl):
    src = _main(
        'Json d = parseJson("[{\\"n\\":1},{\\"n\\":2}]");'
        ' print(d.size()); print(d.at(0).get("n").asInt()); print(d.at(1).get("n").asInt());'
    )
    assert run_twl(src).stdout == "2\n1\n2\n"


def test_nested_and_whitespace(run_twl):
    src = _main(
        'Json d = parseJson("  { \\"u\\" : { \\"id\\" : 7 } }  ");'
        ' print(d.get("u").get("id").asInt());'
    )
    assert run_twl(src).stdout == "7\n"


def test_string_newline_escape(run_twl):
    src = r'import "Json.twl"; class Main { void main() { print(parseJson("\"line1\\nline2\"").asString().length); } }'
    assert run_twl(src).stdout == "11\n"


def test_malformed_aborts(run_twl):
    r = run_twl(_main('Json d = parseJson("{");'))
    assert r.returncode != 0
    assert "invalid JSON" in (r.stdout + r.stderr)


def test_empty_input_aborts(run_twl):
    r = run_twl(_main('Json d = parseJson("");'))
    assert r.returncode != 0
    assert "invalid JSON" in (r.stdout + r.stderr)
