import pytest

import lang
from lang import LangError, run


# ---------------------------------------------------------------------------
# Basics, literals and program values
# ---------------------------------------------------------------------------


def test_empty_programs():
    assert run("") is None
    assert run("   \n\n  ") is None
    assert run("# only a comment") is None
    assert run(";;;\n;;") is None


def test_literals():
    assert run("123") == 123
    assert run("0") == 0
    assert run('"hello"') == "hello"
    assert run("true") is True
    assert run("false") is False
    assert run("nil") is None


def test_big_integers():
    assert run("2 ** 100") == 2 ** 100
    assert run("-98765432109876543210") == -98765432109876543210


def test_string_escapes():
    assert run(r'"a\"b"') == 'a"b'
    assert run(r'"a\\b"') == "a\\b"
    assert run(r'"a\nb"') == "a\nb"


def test_comments_and_newlines():
    assert run("1 # comment\n2") == 2
    assert run("1\n\n# hi\n\n2") == 2
    assert run("let x = 1; x + 1") == 2


def test_program_value_is_last_statement():
    assert run("1; 2; 3") == 3
    assert run("let x = 1") is None
    assert run("1\nlet x = 2") is None
    assert run("if true { 1 }") is None
    assert run("while false { 1 }") is None


# ---------------------------------------------------------------------------
# Arithmetic and operators
# ---------------------------------------------------------------------------


def test_arithmetic():
    assert run("1 + 2 * 3") == 7
    assert run("(1 + 2) * 3") == 9
    assert run("10 - 3 - 2") == 5
    assert run("20 / 3") == 6
    assert run("20 % 3") == 2
    assert run("-7 / 2") == -4
    assert run("-7 % 2") == 1
    assert run("7 / -2") == -4


def test_string_concat_and_compare():
    assert run('"a" + "b"') == "ab"
    assert run('"abc" < "abd"') is True
    assert run('"b" >= "a"') is True
    assert run('"" < "a"') is True


def test_unary_and_power_precedence():
    assert run("-2 ** 2") == -4
    assert run("2 ** 3 ** 2") == 512
    assert run("(-2) ** 2") == 4
    assert run("-5") == -5
    assert run("--5") == 5
    assert run("2 ** 0") == 1
    assert run("0 ** 0") == 1


def test_not_and_truthiness():
    assert run("not false") is True
    assert run("not nil") is True
    assert run("not true") is False
    # only false and nil are falsy
    assert run("not 0") is False
    assert run('not ""') is False
    assert run("not (1 == 2)") is True


def test_booleans_short_circuit_and_return_operand():
    assert run("false and 5") is False
    assert run("true and 5") == 5
    assert run("nil or 5") == 5
    assert run("true or 5") is True
    assert run("0 or 5") == 0  # 0 is truthy
    assert run('"x" or "y"') == "x"
    # Short-circuiting must not evaluate the right hand side.
    assert run("false and undefined_name") is False
    assert run("true or undefined_name") is True


def test_equality():
    assert run("1 == 1") is True
    assert run("1 != 2") is True
    assert run('"a" == "a"') is True
    assert run("true == true") is True
    assert run("nil == nil") is True
    # Different types are unequal, not an error.
    assert run("1 == true") is False
    assert run('1 == "1"') is False
    assert run("nil == false") is False
    assert run("1 != true") is True


def test_function_identity_equality():
    assert run("let f = fn() { }\nf == f") is True
    assert run("fn() { } == fn() { }") is False
    assert run("len == len") is True


# ---------------------------------------------------------------------------
# Statements, scopes and control flow
# ---------------------------------------------------------------------------


def test_let_and_assignment():
    assert run("let x = 1\nx = 2\nx") == 2
    assert run("let x = 1\nlet y = x + 2\ny") == 3


def test_block_scoping():
    assert run("let x = 1\n{ let x = 2\nx = 3 }\nx") == 1
    assert run("let x = 1\n{ x = 9 }\nx") == 9


def test_if_else_and_else_if():
    assert run("if 1 == 1 { 10 } else { 20 }") is None
    assert run("let x = 0\nif true { x = 1 } else { x = 2 }\nx") == 1
    assert run("let x = 0\nif false { x = 1 } else { x = 2 }\nx") == 2
    assert (
        run(
            "let x = 0\n"
            "if false { x = 1 } else if true { x = 2 } else { x = 3 }\n"
            "x"
        )
        == 2
    )
    assert (
        run(
            "let x = 0\n"
            "if false { x = 1 } else if false { x = 2 } else { x = 3 }\n"
            "x"
        )
        == 3
    )


def test_else_on_next_line():
    assert run("let x = 0\nif false { x = 1 }\nelse { x = 2 }\nx") == 2


def test_if_truthiness():
    assert run("let x = 0\nif 0 { x = 1 }\nx") == 1  # 0 truthy
    assert run("let x = 0\nif nil { x = 1 }\nx") == 0
    assert run("let x = 0\nif false { x = 1 }\nx") == 0


def test_while_break_continue():
    assert run("let i = 0\nlet s = 0\nwhile i < 5 { i = i + 1\ns = s + i }\ns") == 15
    assert (
        run(
            "let i = 0\nlet s = 0\n"
            "while i < 10 { i = i + 1\nif i == 6 { break }\ns = s + i }\ns"
        )
        == 15
    )
    assert (
        run(
            "let i = 0\nlet s = 0\n"
            "while i < 5 { i = i + 1\nif i % 2 == 0 { continue }\ns = s + i }\ns"
        )
        == 9
    )


def test_statement_without_separator_after_brace():
    # A brace-terminated statement may be followed directly by another.
    assert run("if true { 1 } 2") == 2
    assert run("let f = fn(n) { if n <= 1 { return 1 } return n * f(n - 1) }\n"
               "f(4)") == 24


# ---------------------------------------------------------------------------
# Functions, closures and builtins
# ---------------------------------------------------------------------------


def test_functions_and_return():
    assert run("let double = fn(x) { return x * 2 }\ndouble(21)") == 42
    assert run("let f = fn() { return }\nf()") is None
    assert run("let f = fn() { 1 }\nf()") is None


def test_function_arguments():
    assert run("let add = fn(a, b) { return a + b }\nadd(2, 3)") == 5
    assert run("let id = fn(x) { return x }\nid(\"hi\")") == "hi"


def test_recursion():
    assert (
        run(
            "let fact = fn(n) { if n <= 1 { return 1 } return n * fact(n - 1) }\n"
            "fact(10)"
        )
        == 3628800
    )
    assert (
        run(
            "let fib = fn(n) {\n"
            "  if n < 2 { return n }\n"
            "  return fib(n - 1) + fib(n - 2)\n"
            "}\n"
            "fib(10)"
        )
        == 55
    )


def test_mutual_recursion():
    src = (
        "let is_even = fn(n) { if n == 0 { return true } return is_odd(n - 1) }\n"
        "let is_odd = fn(n) { if n == 0 { return false } return is_even(n - 1) }\n"
        "is_even(10)"
    )
    assert run(src) is True


def test_closures():
    src = (
        "let make_adder = fn(x) {\n"
        "  return fn(y) { return x + y }\n"
        "}\n"
        "let add5 = make_adder(5)\n"
        "add5(3)"
    )
    assert run(src) == 8

    # Each closure captures its own environment.
    src = (
        "let make = fn(x) { return fn() { return x } }\n"
        "let a = make(1)\n"
        "let b = make(2)\n"
        "a() + b()"
    )
    assert run(src) == 3


def test_closure_sees_later_assignment():
    src = (
        "let x = 1\n"
        "let f = fn() { return x }\n"
        "x = 2\n"
        "f()"
    )
    assert run(src) == 2


def test_len():
    assert run('len("")') == 0
    assert run('len("hello")') == 5
    assert run(r'len("a\nb")') == 3


def test_str():
    assert run("str(123)") == "123"
    assert run("str(-5)") == "-5"
    assert run("str(true)") == "true"
    assert run("str(false)") == "false"
    assert run("str(nil)") == "nil"
    assert run('str("abc")') == "abc"


def test_print_and_output():
    assert run('print("a")\nprint(1)\nprint(true)') is None
    assert lang.OUTPUT == ["a", "1", "true"]
    # OUTPUT is cleared at the start of each run.
    run('print("second")')
    assert lang.OUTPUT == ["second"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


ERROR_SOURCES = [
    # syntax
    "1 +",
    "let = 1",
    "let x 1",
    "if true {",
    "while true {",
    "(1 + 2",
    "1 = 2",
    "let x = 1 let y = 2",
    "else { 1 }",
    '"unterminated',
    '"bad\\qescape"',
    "1 == 2 == 3",
    "1 < 2 < 3",
    "1 == 2 != 3",
    # name errors
    "missing",
    "let x = 1\nx = y",
    "y = 1",
    "let x = 1\nlet x = 2",
    # type errors
    '1 + "a"',
    '"a" + 1',
    '1 - "a"',
    '-"a"',
    "1 < \"a\"",
    "true < false",
    "len(1)",
    "str(fn() { })",
    # division / exponent errors
    "1 / 0",
    "1 % 0",
    "2 ** -1",
    # call errors
    "let x = 1\nx()",
    "fn(a) { return a }()",
    "fn(a, b) { return a }(1)",
    "len()",
    "len(\"a\", \"b\")",
    # control-flow misuse
    "return 1",
    "return",
    "break",
    "continue",
    "while false { let f = fn() { break } }",
]


@pytest.mark.parametrize("src", ERROR_SOURCES)
def test_errors_raise_langerror(src):
    with pytest.raises(LangError):
        run(src)


def test_deep_recursion_does_not_crash():
    src = (
        "let f = fn(n) { if n == 0 { return 0 } return f(n - 1) }\n"
        "f(10000)"
    )
    try:
        result = run(src)
    except LangError:
        pass
    else:
        assert result == 0


def test_moderate_recursion_works():
    src = (
        "let f = fn(n) { if n == 0 { return 0 } return 1 + f(n - 1) }\n"
        "f(500)"
    )
    assert run(src) == 500


def test_non_function_call_error_is_langerror():
    with pytest.raises(LangError):
        run("nil()")
    with pytest.raises(LangError):
        run('"abc"(1)')
