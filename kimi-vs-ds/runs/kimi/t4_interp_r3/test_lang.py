import pytest

import lang
from lang import LangError, run


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", None),
        ("; \n # nothing else\n", None),
        ("123", 123),
        ('"hello"', "hello"),
        ('"\\\" \\\\ \\n"', '" \\ \n'),
        ("true", True),
        ("false", False),
        ("nil", None),
        ("9999999999999999999999999999999999999999", 10**40 - 1),
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("10 - 3 - 2", 5),
        ("2 ** 3 ** 2", 512),
        ("-2 ** 2", -4),
        ("(-2) ** 2", 4),
        ("2 * 3 ** 2", 18),
        ("-7 / 2", -4),
        ("-7 % 2", 1),
        ('"ab" + "cd"', "abcd"),
        ('"a" < "b"', True),
        ("3 >= 3", True),
        ("1 == true", False),
        ("nil == nil", True),
        ("nil != false", True),
        ("not nil", True),
        ("not 0", False),
        ("false or 0", 0),
        ("nil or \"fallback\"", "fallback"),
        ("0 and 4", 4),
        ("nil and 4", None),
        ("1; 2; 3", 3),
        ("1; let x = 2", None),
        ("if true { 1; }", None),
        ("while false { 1; }", None),
    ],
)
def test_values_and_precedence(source, expected):
    result = run(source)
    assert result == expected
    assert type(result) is type(expected)


def test_comments_blank_lines_crlf_and_expression_continuations():
    assert run("# heading\r\n\r\nlet x = 1 +\r\n  2; # sum\r\nx") == 3
    assert run("let f = fn(\n a,\n b\n) { return a + b; }; f(\n2, 3\n)") == 5


def test_short_circuit_does_not_evaluate_other_operand():
    assert run("false and missing") is False
    assert run("true or missing") is True
    assert run('nil or print("yes")') is None
    assert lang.OUTPUT == ["yes"]


def test_truthiness_is_not_python_truthiness():
    source = """
    let a = 0;
    let b = "";
    if 0 { a = 1; } else { a = 2; }
    if "" { b = "yes"; } else { b = "no"; }
    a + len(b)
    """
    assert run(source) == 4


def test_if_else_and_else_if():
    source = """
    let classify = fn(n) {
      if n < 0 { return "negative"; }
      else if n == 0 { return "zero"; }
      else { return "positive"; }
    };
    classify(-10) + ":" + classify(0) + ":" + classify(8)
    """
    assert run(source) == "negative:zero:positive"


def test_scopes_assignment_and_shadowing():
    source = """
    let x = 1;
    let y = 0;
    if true {
      let x = 10;
      x = x + 1;
      y = x;
    }
    x + y
    """
    assert run(source) == 12
    assert run("let x = 1; if true { let x = 2; }; x") == 1


def test_while_break_continue_and_fresh_block_scope():
    source = """
    let i = 0;
    let sum = 0;
    while i < 10 {
      i = i + 1;
      let local = i;
      if local == 3 { continue; }
      if local == 8 { break; }
      sum = sum + local;
    }
    sum
    """
    assert run(source) == 25


def test_closures_capture_lexical_environment_and_mutate_nearest_binding():
    source = """
    let make = fn(start) {
      let n = start;
      return fn(step) { n = n + step; return n; };
    };
    let counter = make(10);
    counter(2);
    counter(3)
    """
    assert run(source) == 15


def test_let_bound_recursion_and_bare_return():
    assert run(
        "let fact = fn(n) { if n <= 1 { return 1; }; "
        "return n * fact(n - 1); }; fact(10)"
    ) == 3628800
    assert run("let f = fn() { return; }; f()") is None
    assert run("let f = fn() { return\n }; f()") is None
    assert run("let f = fn() { 123; }; f()") is None


def test_function_identity_equality():
    assert run("let f = fn() {}; let g = f; f == g") is True
    assert run("fn() {} == fn() {}") is False
    assert run("let f = fn() {}; f == nil") is False


def test_builtins_and_output():
    assert run('len("") + len("abc")') == 3
    assert run('str(123) + str(true) + str(false) + str(nil) + "x"') == "123truefalsenilx"
    assert run('print("a\\n"); print(false); print(42)') is None
    assert lang.OUTPUT == ["a\n", "false", "42"]
    assert run('print("new")') is None
    assert lang.OUTPUT == ["new"]


def test_output_list_is_cleared_in_place_even_after_an_error():
    output_reference = lang.OUTPUT
    run('print("old")')
    with pytest.raises(LangError):
        run("let =")
    assert lang.OUTPUT is output_reference
    assert output_reference == []


@pytest.mark.parametrize(
    "source",
    [
        "let x = 1; let x = 2",
        "missing",
        "x = 1",
        "1 + true",
        '"x" + 1',
        "1 < \"2\"",
        "true < false",
        "-nil",
        "1 / 0",
        "1 % 0",
        "2 ** -1",
        "true ** 2",
        "1(2)",
        "len()",
        "len(\"a\", \"b\")",
        "len(1)",
        "let f = fn(a) {}; f()",
        "let f = fn() {}; f(1)",
        "return 1",
        "break",
        "continue",
        "while true { fn() { break; }; }",
        "let = 1",
        "let x 1",
        "1 2",
        "(1 + 2",
        "1 +",
        "1 == 1 == true",
        "1 < 2 < 3",
        "fn(a, a) {}",
        "fn(a,) {}",
        "f(1,)",
        '"unterminated',
        '"bad\\t"',
        '"bad\\q"',
        "@",
        "'single quotes'",
    ],
)
def test_errors_are_lang_errors(source):
    with pytest.raises(LangError):
        run(source)


def test_deep_recursion_never_leaks_recursion_error():
    source = """
    let descend = fn(n) {
      if n == 0 { return 0; }
      return 1 + descend(n - 1);
    };
    descend(10000)
    """
    try:
        result = run(source)
    except LangError:
        pass
    else:
        assert result == 10000
    assert run("40 + 2") == 42
