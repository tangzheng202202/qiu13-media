"""Tests for the tiny language interpreter in ``lang.py`` (see SPEC.md)."""

import pytest

import lang
from lang import LangError, run


# --------------------------------------------------------------------------
# Basics / lexical
# --------------------------------------------------------------------------


def test_integer_literal():
    assert run("42") == 42


def test_big_integers():
    assert run("12345678901234567890 * 10") == 123456789012345678900
    assert run("2 ** 100") == 2 ** 100


def test_numeric_strings_are_not_converted():
    assert run('"42"') == "42"


def test_string_escapes():
    assert run(r'"a\"b"') == 'a"b'
    assert run(r'"a\\b"') == "a\\b"
    assert run(r'"a\nb"') == "a\nb"
    assert run(r'"\n"') == "\n"


def test_booleans_and_nil():
    assert run("true") is True
    assert run("false") is False
    assert run("nil") is None
    assert type(run("true")) is bool


def test_comments():
    assert run("1 + 2 # this is ignored") == 3
    assert run("# only a comment\n") is None
    assert run("let x = 1 # trailing\nx") == 1


def test_whitespace_and_blank_lines():
    assert run("  1  +  2  ") == 3
    assert run("\n\n1\n\n\n2\n\n") == 2
    assert run("") is None
    assert run("\n\n") is None


def test_semicolon_separators():
    assert run("1; 2; 3") == 3
    assert run("let x = 1; let y = 2; x + y") == 3


def test_multiline_expression_in_parens():
    assert run("let x = (1 +\n          2)\nx") == 3


# --------------------------------------------------------------------------
# Precedence and operators
# --------------------------------------------------------------------------


def test_arithmetic_precedence():
    assert run("1 + 2 * 3") == 7
    assert run("(1 + 2) * 3") == 9
    assert run("10 - 2 - 3") == 5
    assert run("100 / 5 / 2") == 10


def test_floor_division_and_modulo():
    assert run("7 / 2") == 3
    assert run("-7 / 2") == -4
    assert run("7 % 3") == 1
    assert run("-7 % 3") == 2


def test_power_right_associative():
    assert run("2 ** 3 ** 2") == 512


def test_power_binds_tighter_than_unary_minus():
    assert run("-2 ** 2") == -4
    assert run("-2 ** 3") == -8
    assert run("(-2) ** 3") == -8


def test_unary_minus_nesting():
    assert run("- -5") == 5
    assert run("--5") == 5


def test_not_operator():
    assert run("not 1") is False
    assert run("not 0") is False  # 0 is truthy
    assert run("not nil") is True
    assert run("not false") is True
    assert run("not not 1") is True


def test_logical_short_circuit_and_values():
    assert run("1 or 2") == 1
    assert run("nil or 2") == 2
    assert run("false or 3") == 3
    assert run("0 and 5") == 5  # 0 is truthy
    assert run("false and 5") is False
    assert run("nil and 5") is None
    assert run("1 and 2") == 2


def test_comparisons():
    assert run("1 < 2") is True
    assert run("2 <= 2") is True
    assert run("3 > 4") is False
    assert run("4 >= 4") is True
    assert run('"abc" < "abd"') is True
    assert run('"b" >= "a"') is True
    assert run('"abc" == "abc"') is True


def test_equality_across_types_is_false():
    assert run('1 == "1"') is False
    assert run("true == 1") is False
    assert run("nil == false") is False
    assert run("nil == nil") is True
    assert run("1 != 2") is True
    assert run('"a" != "a"') is False


def test_string_concatenation():
    assert run('"a" + "b"') == "ab"
    assert run('"a" + "b" + "c"') == "abc"


def test_grouping():
    assert run("((((1))))") == 1
    assert run("1 + (2 + (3 + 4))") == 10


# --------------------------------------------------------------------------
# Variables, scopes, assignment
# --------------------------------------------------------------------------


def test_let_and_read():
    assert run("let x = 10\nx") == 10


def test_assignment():
    assert run("let x = 1\nx = 5\nx") == 5
    assert run("let x = 1\nx = x + 4\nx") == 5


def test_redeclare_in_same_scope_is_error():
    with pytest.raises(LangError):
        run("let x = 1\nlet x = 2")


def test_shadowing_in_nested_block():
    assert run("let x = 1\n{ let x = 2 }\nx") == 1
    assert run("let x = 1\nif true { let x = 2 }\nx") == 1


def test_assignment_from_inner_scope_updates_outer():
    assert run("let x = 1\n{ x = 2 }\nx") == 2


def test_assign_to_undefined_variable_is_error():
    with pytest.raises(LangError):
        run("y = 1")


def test_block_scope_variables_do_not_escape():
    with pytest.raises(LangError):
        run("if true { let y = 2 }\ny")


def test_program_value_is_none_for_non_expressions():
    assert run("let x = 1") is None
    assert run("if true { 1 }") is None
    assert run("if true { 1 } else { 2 }") is None
    assert run("while false { 1 }") is None


# --------------------------------------------------------------------------
# Control flow
# --------------------------------------------------------------------------


def test_if_else():
    prog = """
    let r = "?"
    if 1 < 2 { r = "then" } else { r = "else" }
    r
    """
    assert run(prog) == "then"

    prog = """
    let r = "?"
    if 1 > 2 { r = "then" } else { r = "else" }
    r
    """
    assert run(prog) == "else"


def test_else_if_chain():
    prog = """
    let r = "?"
    let x = 3
    if x == 1 { r = "a" } else if x == 3 { r = "c" } else { r = "d" }
    r
    """
    assert run(prog) == "c"

    prog = """
    let r = "?"
    let x = 9
    if x == 1 { r = "a" } else if x == 3 { r = "c" } else { r = "d" }
    r
    """
    assert run(prog) == "d"


def test_else_if_without_final_else():
    prog = """
    let r = "no"
    let x = 9
    if x == 1 { r = "a" } else if x == 3 { r = "c" }
    r
    """
    assert run(prog) == "no"


def test_truthiness():
    prog = """
    let r = "no"
    if 0 { r = "yes" }
    r
    """
    assert run(prog) == "yes"

    prog = """
    let r = "no"
    if "" { r = "yes" }
    r
    """
    assert run(prog) == "yes"

    prog = """
    let r = "no"
    if nil { r = "yes" } else { r = "no2" }
    r
    """
    assert run(prog) == "no2"

    prog = """
    let r = "no"
    if false { r = "yes" } else { r = "no2" }
    r
    """
    assert run(prog) == "no2"


def test_while_loop():
    prog = """
    let i = 0
    let total = 0
    while i < 5 {
        i = i + 1
        total = total + i
    }
    total
    """
    assert run(prog) == 15


def test_break():
    prog = """
    let i = 0
    while true {
        i = i + 1
        if i == 4 { break }
    }
    i
    """
    assert run(prog) == 4


def test_continue():
    prog = """
    let i = 0
    let total = 0
    while i < 6 {
        i = i + 1
        if i % 2 == 0 { continue }
        total = total + i
    }
    total
    """
    assert run(prog) == 9  # 1 + 3 + 5


def test_nested_loops_break_only_inner():
    prog = """
    let outer = 0
    let count = 0
    while outer < 3 {
        outer = outer + 1
        let inner = 0
        while true {
            inner = inner + 1
            if inner == 2 { break }
        }
        count = count + inner
    }
    count
    """
    assert run(prog) == 6


def test_break_outside_loop_is_error():
    with pytest.raises(LangError):
        run("break")
    with pytest.raises(LangError):
        run("if true { break }")


def test_continue_outside_loop_is_error():
    with pytest.raises(LangError):
        run("continue")


def test_break_inside_function_inside_loop_is_error():
    with pytest.raises(LangError):
        run("while false { fn() { break } }")


def test_return_outside_function_is_error():
    with pytest.raises(LangError):
        run("return 1")
    with pytest.raises(LangError):
        run("return")


# --------------------------------------------------------------------------
# Functions, closures, recursion
# --------------------------------------------------------------------------


def test_function_call():
    assert run("let double = fn(x) { return x * 2 }\ndouble(21)") == 42


def test_bare_return_yields_nil():
    assert run("let f = fn() { return }\nf()") is None


def test_function_without_return_yields_nil():
    assert run("let f = fn() { let y = 2\ny }\nf()") is None


def test_return_stops_execution():
    prog = """
    let f = fn() {
        return 1
        2
    }
    f()
    """
    assert run(prog) == 1


def test_early_return_in_loop():
    prog = """
    let find = fn(target) {
        let i = 0
        while true {
            if i == target { return i * 10 }
            i = i + 1
        }
    }
    find(3)
    """
    assert run(prog) == 30


def test_zero_parameter_function():
    assert run("let f = fn() { return 7 }\nf()") == 7


def test_arity_mismatch_is_error():
    with pytest.raises(LangError):
        run("let f = fn(a, b) { return a + b }\nf(1)")
    with pytest.raises(LangError):
        run("let f = fn(a, b) { return a + b }\nf(1, 2, 3)")
    with pytest.raises(LangError):
        run("let f = fn() { return 1 }\nf(1)")


def test_calling_non_function_is_error():
    with pytest.raises(LangError):
        run("let x = 1\nx(2)")
    with pytest.raises(LangError):
        run('"abc"(1)')
    with pytest.raises(LangError):
        run("nil()")


def test_closure_captures_lexical_scope():
    prog = """
    let adder = fn(n) { return fn(x) { return x + n } }
    let add5 = adder(5)
    add5(3)
    """
    assert run(prog) == 8


def test_closure_counter_mutates_captured_variable():
    prog = """
    let make = fn() {
        let n = 0
        return fn() {
            n = n + 1
            return n
        }
    }
    let c = make()
    c()
    c()
    c()
    """
    assert run(prog) == 3


def test_two_closures_are_independent():
    prog = """
    let make = fn() {
        let n = 0
        return fn() {
            n = n + 1
            return n
        }
    }
    let a = make()
    let b = make()
    a()
    a()
    b()
    """
    assert run(prog) == 1


def test_let_bound_recursion():
    prog = """
    let fact = fn(n) {
        if n <= 1 { return 1 }
        return n * fact(n - 1)
    }
    fact(10)
    """
    assert run(prog) == 3628800


def test_recursive_fibonacci():
    prog = """
    let fib = fn(n) {
        if n < 2 { return n }
        return fib(n - 1) + fib(n - 2)
    }
    fib(15)
    """
    assert run(prog) == 610


def test_mutual_recursion():
    prog = """
    let is_even = fn(n) {
        if n == 0 { return true }
        return is_odd(n - 1)
    }
    let is_odd = fn(n) {
        if n == 0 { return false }
        return is_even(n - 1)
    }
    is_even(10)
    """
    assert run(prog) is True


def test_functions_compare_by_identity():
    assert run("let f = fn() { return 1 }\nlet g = f\nf == g") is True
    assert run("fn() { return 1 } == fn() { return 1 }") is False
    assert run("let f = fn() { return 1 }\nf != fn() { return 1 }") is True


def test_deep_recursion_does_not_crash():
    prog = """
    let down = fn(n) {
        if n == 0 { return 0 }
        return 1 + down(n - 1)
    }
    down(10000)
    """
    try:
        assert run(prog) == 10000
    except LangError:
        pass  # the spec allows reporting deep recursion as a LangError


def test_unbounded_recursion_raises_lang_error():
    with pytest.raises(LangError):
        run("let f = fn(n) { return f(n + 1) }\nf(0)")


# --------------------------------------------------------------------------
# Builtins
# --------------------------------------------------------------------------


def test_len():
    assert run('len("hello")') == 5
    assert run('len("")') == 0
    assert run('len("a\\nb")') == 3


def test_len_requires_string():
    with pytest.raises(LangError):
        run("len(1)")
    with pytest.raises(LangError):
        run("len(nil)")


def test_str():
    assert run("str(42)") == "42"
    assert run("str(-7)") == "-7"
    assert run("str(true)") == "true"
    assert run("str(false)") == "false"
    assert run("str(nil)") == "nil"
    assert run('str("abc")') == "abc"
    assert run('str(1 + 2)') == "3"


def test_print_appends_to_output():
    result = run('print(1)\nprint("hi")\nprint(true)')
    assert result is None  # print returns nil
    assert lang.OUTPUT == ["1", "hi", "true"]


def test_output_cleared_between_runs():
    run('print("first")')
    assert lang.OUTPUT == ["first"]
    run('print("second")')
    assert lang.OUTPUT == ["second"]
    run("1")
    assert lang.OUTPUT == []


def test_str_of_function_is_error():
    with pytest.raises(LangError):
        run("str(fn() { return 1 })")


# --------------------------------------------------------------------------
# Runtime errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src",
    [
        "1 / 0",
        "1 % 0",
        "let x = 5\nx / 0",
        '1 + "a"',
        '"a" + 1',
        "true + 1",
        "nil + 1",
        '"a" - "b"',
        "1 * true",
        "-true",
        "true ** 2",
        "2 ** -1",
        '"a" ** 2',
        '1 < "a"',
        "true < false",
        "1 <= nil",
        "undefined_variable",
        "len(1, 2)",
    ],
)
def test_runtime_errors(src):
    with pytest.raises(LangError):
        run(src)


@pytest.mark.parametrize(
    "src",
    [
        "1 == 2 == 3",
        "1 != 2 != 3",
        "1 < 2 < 3",
        "1 <= 2 >= 3",
    ],
)
def test_chained_comparisons_are_syntax_errors(src):
    with pytest.raises(LangError):
        run(src)


@pytest.mark.parametrize(
    "src",
    [
        "let x",
        "let x =",
        "let = 1",
        "let 5 = 3",
        "1 +",
        "if true {",
        "if true 1",
        "while true 1",
        "}",
        "(((1)",
        '"abc',
        r'"a\qb"',
        "1 @ 2",
        "1 2",
        "fn(a,) { return a }",
        "fn(a, a) { return a }",
        "else { 1 }",
        "let x = fn() { return 1 } + 1",
        "1 = 2",
        "fn f(x) { return x }",
        "x(",
        "if true { 1 } else",
        "while { 1 }",
        "let x = 1 let y = 2",
    ],
)
def test_syntax_errors(src):
    with pytest.raises(LangError):
        run(src)


def test_all_errors_are_lang_errors():
    bad_programs = [
        "1 / 0",
        '"unterminated',
        "@",
        "let x = 1\nlet x = 2",
        "nope",
        "1 + nil",
        "break",
        "while true { fn() { continue } }",
        "let f = fn(a) { return a }\nf()",
        "1 < 2 < 3",
        "2 ** -1",
        "len(3)",
        "1 2",
        "f = 3",
    ]
    for src in bad_programs:
        with pytest.raises(LangError):
            run(src)


# --------------------------------------------------------------------------
# Misc integration programs
# --------------------------------------------------------------------------


def test_fizzbuzz_style_program():
    prog = """
    let collect = fn(n) {
        let i = 1
        let out = ""
        while i <= n {
            if i % 15 == 0 { out = out + "FizzBuzz," }
            else if i % 3 == 0 { out = out + "Fizz," }
            else if i % 5 == 0 { out = out + "Buzz," }
            else { out = out + str(i) + "," }
            i = i + 1
        }
        return out
    }
    collect(15)
    """
    assert run(prog) == "1,2,Fizz,4,Buzz,Fizz,7,8,Fizz,Buzz,11,Fizz,13,14,FizzBuzz,"


def test_gcd_program():
    prog = """
    let gcd = fn(a, b) {
        while b != 0 {
            let t = b
            b = a % b
            a = t
        }
        return a
    }
    gcd(48, 18)
    """
    assert run(prog) == 6


def test_string_building_and_printing():
    prog = """
    let repeat = fn(s, n) {
        let out = ""
        let i = 0
        while i < n {
            out = out + s
            i = i + 1
        }
        return out
    }
    print(repeat("ab", 3))
    len(repeat("x", 4))
    """
    assert run(prog) == 4
    assert lang.OUTPUT == ["ababab"]


def test_variables_named_like_keyword_prefixes():
    assert run("let iffy = 1\nlet letters = 2\niffy + letters") == 3
    assert run("let _x = 5\n_x") == 5
    assert run("let x1 = 5\nx1") == 5


def test_short_circuit_avoids_division_by_zero():
    prog = """
    let x = 0
    let r = "safe"
    if x != 0 and 10 / x > 1 { r = "boom" }
    r
    """
    assert run(prog) == "safe"
    assert run("1 or 1 / 0") == 1
    assert run("nil and 1 / 0") is None


def test_closures_see_later_assignments():
    prog = """
    let x = 1
    let f = fn() { return x }
    x = 2
    f()
    """
    assert run(prog) == 2


def test_expression_statement_sequence_value():
    assert run("1; 2; 3") == 3
    assert run("let x = 1; x + 1; x + 2") == 3


def test_output_is_the_same_list_object():
    out = lang.OUTPUT
    run('print("a")\nprint("b")')
    assert out is lang.OUTPUT
    assert out == ["a", "b"]


def test_lang_error_is_an_exception():
    assert issubclass(LangError, Exception)


def test_nested_blocks_and_scopes():
    prog = """
    let x = 1
    {
        let y = 2
        {
            let z = 3
            x = x + y + z
        }
    }
    x
    """
    assert run(prog) == 6


def test_parameters_shadow_outer_bindings():
    prog = """
    let x = 100
    let f = fn(x) { return x + 1 }
    f(1)
    """
    assert run(prog) == 2


def test_function_returning_function_stored_and_called():
    prog = """
    let compose = fn(f, g) { return fn(x) { return f(g(x)) } }
    let inc = fn(x) { return x + 1 }
    let dbl = fn(x) { return x * 2 }
    let inc_then_dbl = compose(dbl, inc)
    inc_then_dbl(5)
    """
    assert run(prog) == 12


def test_while_with_local_declarations():
    prog = """
    let i = 0
    let total = 0
    while i < 4 {
        let square = i * i
        total = total + square
        i = i + 1
    }
    total
    """
    assert run(prog) == 14  # 0 + 1 + 4 + 9
