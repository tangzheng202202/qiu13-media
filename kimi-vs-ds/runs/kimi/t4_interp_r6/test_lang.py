import pytest

import lang
from lang import LangError, run


def test_literals_comments_and_separators():
    assert run("") is None
    assert run(" # only a comment\n;\n") is None
    assert run('123; "a\\n\\\"b\\\\c"; true; false; nil') is None
    assert run('1 # comment\n;"x" # another') == "x"
    assert run("1\r\n2\r3") == 3


def test_arithmetic_precedence_and_integer_semantics():
    assert run("1 + 2 * 3") == 7
    assert run("(1 + 2) * 3") == 9
    assert run("10 - 3 - 2") == 5
    assert run("-5 / 2") == -3
    assert run("-5 % 2") == 1
    assert run("5 / -2") == -3
    assert run("5 % -2") == -1
    assert run("2 ** 3 ** 2") == 512
    assert run("-2 ** 2") == -4
    assert run("(-2) ** 2") == 4
    assert run("2 ** 3 * 2") == 16
    assert run("999999999999999999999999999999 + 1") == 10**30


def test_strings_and_comparisons():
    assert run('"ab" + "cd"') == "abcd"
    assert run('"abc" < "abd"') is True
    assert run('"z" >= "z"') is True
    assert run("2 <= 2") is True
    assert run("3 > 2") is True
    assert run("1 == 1") is True
    assert run("1 != 2") is True


def test_equality_is_type_strict_and_functions_use_identity():
    assert run("1 == true") is False
    assert run("0 == false") is False
    assert run("nil == false") is False
    assert run('1 == "1"') is False
    assert run("nil == nil") is True
    assert run("let f = fn() {}; f == f") is True
    assert run("fn() {} == fn() {}") is False
    assert run("len == len") is True
    assert run("len == str") is False


def test_truthiness_and_short_circuit_values():
    assert run("not false") is True
    assert run("not nil") is True
    assert run("not 0") is False
    assert run('not ""') is False
    assert run("false and missing") is False
    assert run("nil and missing") is None
    assert run("true or missing") is True
    assert run("0 or missing") == 0
    assert run("nil or 7") == 7
    assert run("0 and 8") == 8
    assert run('"" and "yes"') == "yes"


def test_let_assignment_and_block_scopes():
    source = """
        let x = 1
        let y = 10
        {
            let x = 2
            x = x + 3
            y = x
        }
        x + y
    """
    assert run(source) == 6
    assert run("let x = 1; { x = 4; }; x") == 4


def test_if_else_and_else_if():
    source = """
        let x = 2
        let result = 0
        if false { result = 1 }
        else if x == 2 { result = 2 }
        else { result = 3 }
        result
    """
    assert run(source) == 2
    assert run("if false { 1 }") is None
    assert run("1; if true { 2 }") is None
    assert run("if nil { missing } else { 4 }; 9") == 9


def test_while_break_and_continue():
    source = """
        let i = 0
        let sum = 0
        while i < 10 {
            i = i + 1
            if i == 3 { continue }
            if i == 6 { break }
            sum = sum + i
        }
        sum
    """
    assert run(source) == 12  # 1 + 2 + 4 + 5
    assert run("1; while false { 2 }") is None


def test_loop_body_has_a_fresh_block_scope():
    source = """
        let i = 0
        let f = nil
        while i < 2 {
            let x = i
            if i == 1 { f = fn() { return x } }
            i = i + 1
        }
        f()
    """
    assert run(source) == 1


def test_functions_return_closures_and_recursion():
    assert run("let add = fn(a, b) { return a + b }; add(3, 4)") == 7
    assert run("fn() { return 9 }()") == 9
    assert run("fn() { 9 }()") is None
    assert run("fn() { return }()") is None
    source = """
        let make = fn(x) { return fn(y) { return x + y } }
        let add5 = make(5)
        add5(8)
    """
    assert run(source) == 13
    factorial = """
        let fact = fn(n) {
            if n <= 1 { return 1 }
            return n * fact(n - 1)
        }
        fact(10)
    """
    assert run(factorial) == 3628800


def test_return_propagates_through_nested_control_flow():
    source = """
        let f = fn() {
            while true {
                if true { return 42 }
            }
            return 0
        }
        f()
    """
    assert run(source) == 42


def test_builtins_and_output():
    assert run('len("a\\nb")') == 3
    assert run("str(123)") == "123"
    assert run("str(-20)") == "-20"
    assert run("str(true) + str(false) + str(nil)") == "truefalsenil"
    assert run('str("unchanged")') == "unchanged"
    assert run('print("hello")') is None
    assert lang.OUTPUT == ["hello"]
    assert run('print(1); print(true); print(nil); print("x"); 5') == 5
    assert lang.OUTPUT == ["1", "true", "nil", "x"]


def test_output_is_cleared_in_place_at_start_of_every_run():
    output_reference = lang.OUTPUT
    run('print("old")')
    assert output_reference == ["old"]
    run("1")
    assert output_reference == []
    with pytest.raises(LangError):
        run('print("partial"); 1 / 0')
    assert output_reference == ["partial"]
    with pytest.raises(LangError):
        run(")")
    assert output_reference == []


def test_multiline_constructs_and_continuations():
    source = """
        let f = fn(
            a,
            b
        ) {
            return a +
                b
        }
        f(
            20,
            22
        )
    """
    assert run(source) == 42


def test_very_large_integer_decimal_conversion():
    digits = "9" * 4400
    assert run(f"str({digits})") == digits


@pytest.mark.parametrize(
    "source",
    [
        "1 +",
        "let = 1",
        "let x 1",
        "x",
        "x = 1",
        "let x = 1; let x = 2",
        "{ let x = 1; let x = 2 }",
        "1 / 0",
        "1 % 0",
        "2 ** -1",
        "1 + 'x'",
        '1 + "x"',
        '"x" - "y"',
        "true * 2",
        "-false",
        '1 < "2"',
        "true < false",
        "1 == 1 == 1",
        "1 < 2 < 3",
        "1 != 2 != 3",
        "1()",
        "len()",
        'len("a", "b")',
        "len(1)",
        "str(fn() {})",
        "print()",
        "let f = fn(a) {}; f()",
        "let f = fn(a) {}; f(1, 2)",
        "let f = fn(a, a) {}",
        "return 1",
        "break",
        "continue",
        "while true { fn() { break } }",
        '"unterminated',
        '"bad\\t"',
        "@",
        "(1",
        "if true { 1",
        "f(1,)",
        "fn(a,) {}",
        "1 2",
        "}",
    ],
)
def test_syntax_and_runtime_errors_are_lang_errors(source):
    with pytest.raises(LangError):
        run(source)


def test_invalid_control_flow_is_an_error_even_in_dead_code():
    for source in ("if false { return 1 }", "if false { break }", "if false { continue }"):
        with pytest.raises(LangError):
            run(source)


def test_deep_recursion_is_controlled():
    source = """
        let f = fn(n) {
            if n == 0 { return 0 }
            return f(n - 1) + 1
        }
        f(10000)
    """
    with pytest.raises(LangError):
        run(source)
