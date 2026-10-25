import pytest, lang
from lang import run, LangError
def E(src):
    with pytest.raises(LangError): run(src)
def test_arith(): assert run("1 + 2 * 3 - 4") == 3
def test_floor(): assert run("-7 / 2") == -4 and run("-7 % 3") == 2
def test_pow_assoc(): assert run("2 ** 3 ** 2") == 512
def test_pow_unary(): assert run("-2 ** 2") == -4
def test_pow_neg(): E("2 ** -1")
def test_div0(): E("1 / 0"); E("1 % 0")
def test_bigint(): assert run("2 ** 100") == 2**100
def test_strings(): assert run('"a\\"b" + "\\n"') == 'a"b\n' and run('len("héllo")') == 5
def test_str_cmp(): assert run('"abc" < "abd"') is True
def test_mixed_cmp(): E('1 < "a"')
def test_mixed_add(): E('1 + "a"')
def test_chain_eq(): E("1 == 1 == true")
def test_chain_lt(): E("1 < 2 < 3")
def test_eq_types(): assert run('1 == "1"') is False and run("nil == false") is False
def test_shortcircuit(): assert run("nil or 5") == 5 and run("0 and 7") == 7 and run("false and undefined_x") is False
def test_truthy(): assert run("if 0 { 1 } else { 2 }") is None and run("let r = 0\nif 0 { r = 1 } else { r = 2 }\nr") == 1
def test_not(): assert run("not nil") is True and run("not 0") is False
def test_let_scope():
    assert run("let x = 1\n{ let x = 2 }\nx") == 1
    assert run("let x = 1\n{ x = 2 }\nx") == 2
def test_redeclare(): E("let x = 1; let x = 2")
def test_assign_undeclared(): E("y = 3")
def test_undefined(): E("zz")
def test_while_break_continue():
    assert run("let i = 0; let s = 0\nwhile true { i = i + 1\n if i > 10 { break }\n if i % 2 == 0 { continue }\n s = s + i }\ns") == 25
def test_break_outside(): E("break"); E("continue")
def test_return_outside(): E("return 1")
def test_break_in_fn_in_loop(): E("while true { let f = fn() { break }\n f() }")
def test_closure_counter():
    assert run("let mk = fn() { let c = 0\n return fn() { c = c + 1\n return c } }\nlet a = mk(); let b = mk()\na(); a(); b()\na()") == 3
def test_recursion(): assert run("let fib = fn(n) { if n < 2 { return n }\n return fib(n-1) + fib(n-2) }\nfib(20)") == 6765
def test_bare_return(): assert run("let f = fn() { return }\nf()") is None
def test_fn_no_return(): assert run("let f = fn() { 1 }\nf()") is None
def test_arity(): E("let f = fn(a) { return a }\nf(1, 2)")
def test_call_nonfn(): E("let x = 1; x()")
def test_lexical_scope(): assert run("let x = 1\nlet f = fn() { return x }\nlet g = fn() { let x = 2\n return f() }\ng()") == 1
def test_else_if(): assert run("let x = 5; let r = 0\nif x < 3 { r = 1 } else if x < 6 { r = 2 } else { r = 3 }\nr") == 2
def test_print():
    run('print(1); print("a"); print(nil); print(true)'); assert lang.OUTPUT == ["1","a","nil","true"]
    run('print(2)'); assert lang.OUTPUT == ["2"]
def test_comments(): assert run("# hi\n1 + 1 # x\n\n") == 2
def test_syntax_errors():
    for s in ["1 +", "(1", "let = 3", "if { }", '"abc', "fn(a { }", "1 2"]: E(s)
def test_deep_recursion():
    try: r = run("let f = fn(n) { if n == 0 { return 0 }\n return 1 + f(n - 1) }\nf(10000)")
    except LangError: return
    assert r == 10000
def test_fn_identity(): assert run("let f = fn() { }\nlet g = f\nf == g") is True and run("fn() { } == fn() { }") is False
def test_str_builtin(): assert run('str(12) + str(false)') == "12false"
