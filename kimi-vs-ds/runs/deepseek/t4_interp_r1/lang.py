"""A tiny dynamically typed language, as described in SPEC.md.

Public API:
    run(src: str) -> value      evaluate a program, returning the value of the
                                last expression statement (or None)
    LangError                   raised for every language level error
    OUTPUT                      list of strings produced by `print`
"""

import sys

__all__ = ["run", "LangError", "OUTPUT"]

# Deep recursion in the interpreted language maps onto deep recursion in
# Python.  Raise the interpreter limit so that moderately deep programs work;
# anything beyond that is reported as a LangError (see ``run``).
if sys.version_info >= (3, 11):  # frames are heap allocated, so this is safe
    _RECURSION_LIMIT = 300000
else:  # pragma: no cover - older Pythons burn C stack per frame
    _RECURSION_LIMIT = 8000
if sys.getrecursionlimit() < _RECURSION_LIMIT:
    sys.setrecursionlimit(_RECURSION_LIMIT)

# Strings produced by the `print` builtin.  Cleared (in place) at the start of
# every call to ``run``.
OUTPUT = []


class LangError(Exception):
    """Every error raised by the interpreter (syntax, runtime, typing, ...)."""


# --------------------------------------------------------------------------
# Lexer
# --------------------------------------------------------------------------

_KEYWORDS = frozenset(
    {
        "let",
        "if",
        "else",
        "while",
        "return",
        "break",
        "continue",
        "fn",
        "true",
        "false",
        "nil",
        "and",
        "or",
        "not",
    }
)

_TWO_CHAR_OPS = ("**", "==", "!=", "<=", ">=")
_ONE_CHAR_OPS = frozenset("+-*/%()<>{},;=")

_WHITESPACE = " \t\r\f\v"


class Token:
    __slots__ = ("kind", "value", "line")

    def __init__(self, kind, value, line):
        self.kind = kind
        self.value = value
        self.line = line

    def __repr__(self):  # pragma: no cover - debugging helper
        return "Token(%r, %r, line=%d)" % (self.kind, self.value, self.line)


def _is_ident_start(ch):
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"


def _is_ident_char(ch):
    return _is_ident_start(ch) or ("0" <= ch <= "9")


def _is_digit(ch):
    return "0" <= ch <= "9"


def tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    line = 1
    while i < n:
        ch = src[i]
        if ch in _WHITESPACE:
            i += 1
        elif ch == "\n":
            tokens.append(Token("NEWLINE", None, line))
            line += 1
            i += 1
        elif ch == "#":
            while i < n and src[i] != "\n":
                i += 1
        elif _is_digit(ch):
            j = i
            while j < n and _is_digit(src[j]):
                j += 1
            tokens.append(Token("INT", int(src[i:j]), line))
            i = j
        elif _is_ident_start(ch):
            j = i
            while j < n and _is_ident_char(src[j]):
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                tokens.append(Token("KW", word, line))
            else:
                tokens.append(Token("IDENT", word, line))
            i = j
        elif ch == '"':
            i += 1
            buf = []
            while True:
                if i >= n or src[i] == "\n":
                    raise LangError("unterminated string literal (line %d)" % line)
                c = src[i]
                if c == '"':
                    i += 1
                    break
                if c == "\\":
                    i += 1
                    if i >= n or src[i] == "\n":
                        raise LangError(
                            "unterminated string literal (line %d)" % line
                        )
                    esc = src[i]
                    if esc == '"':
                        buf.append('"')
                    elif esc == "\\":
                        buf.append("\\")
                    elif esc == "n":
                        buf.append("\n")
                    else:
                        raise LangError(
                            "invalid escape sequence '\\%s' (line %d)" % (esc, line)
                        )
                    i += 1
                else:
                    buf.append(c)
                    i += 1
            tokens.append(Token("STR", "".join(buf), line))
        else:
            two = src[i : i + 2]
            if two in _TWO_CHAR_OPS:
                tokens.append(Token(two, two, line))
                i += 2
            elif ch in _ONE_CHAR_OPS:
                tokens.append(Token(ch, ch, line))
                i += 1
            else:
                raise LangError("unexpected character %r (line %d)" % (ch, line))
    tokens.append(Token("EOF", None, line))
    return tokens


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
#
# AST nodes are plain tuples whose first item is a tag string.
#
# Expressions:
#   ('int', value) ('str', value) ('bool', value) ('nil',) ('var', name)
#   ('unary', op, operand)
#   ('binop', op, left, right)          == != < <= > >= + - * / % **
#   ('and', left, right) ('or', left, right)
#   ('call', callee, [args])
#   ('fn', [params], [body stmts])
#
# Statements:
#   ('let', name, expr) ('assign', name, expr) ('expr', expr)
#   ('if', cond, [then stmts], [else stmts] | None)
#   ('while', cond, [body stmts])
#   ('return', expr | None) ('break',) ('continue',) ('block', [stmts])


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.fn_depth = 0
        self.loop_depth = 0
        self.nest = 0

    # -- token helpers ----------------------------------------------------
    def cur(self):
        return self.tokens[self.pos]

    def peek(self, offset=1):
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def error(self, msg):
        tok = self.cur()
        if tok.kind == "EOF":
            where = "end of input"
        else:
            where = repr(tok.value if tok.value is not None else tok.kind)
        raise LangError("%s (line %d, at %s)" % (msg, tok.line, where))

    def is_kw(self, name):
        tok = self.cur()
        return tok.kind == "KW" and tok.value == name

    def is_op(self, op):
        return self.cur().kind == op

    def expect_op(self, op):
        if not self.is_op(op):
            self.error("expected %r" % op)
        return self.advance()

    def expect_ident(self):
        tok = self.cur()
        if tok.kind != "IDENT":
            self.error("expected an identifier")
        self.advance()
        return tok.value

    def skip_newlines(self):
        while self.cur().kind == "NEWLINE":
            self.pos += 1

    def skip_separators(self):
        while self.cur().kind in ("NEWLINE", ";"):
            self.pos += 1

    # Guards against pathological nesting (and unbounded Python recursion).
    def enter(self):
        self.nest += 1
        if self.nest > 2000:
            self.error("code is nested too deeply")

    def leave(self):
        self.nest -= 1

    # -- statements -------------------------------------------------------
    def parse_program(self):
        stmts = []
        while True:
            self.skip_separators()
            if self.cur().kind == "EOF":
                break
            if self.cur().kind == "}":
                self.error("unexpected '}'")
            stmt = self.parse_statement()
            stmts.append(stmt)
            self.check_separator_after(stmt)
        return stmts

    def check_separator_after(self, stmt):
        # Statements that end with a closing brace read naturally without a
        # separator, so they are tolerated (e.g. `if a { 1 } return 2`).
        if stmt[0] in ("if", "while", "block"):
            return
        self.require_separator()

    def require_separator(self):
        if self.cur().kind not in ("NEWLINE", ";", "}", "EOF"):
            self.error("expected ';' or a newline between statements")

    def parse_block_body(self):
        self.expect_op("{")
        stmts = []
        self.enter()
        try:
            while True:
                self.skip_separators()
                if self.cur().kind == "}":
                    break
                if self.cur().kind == "EOF":
                    self.error("unexpected end of input, expected '}'")
                stmt = self.parse_statement()
                stmts.append(stmt)
                self.check_separator_after(stmt)
        finally:
            self.leave()
        self.advance()  # consume '}'
        return stmts

    def parse_statement(self):
        tok = self.cur()
        if tok.kind == "KW":
            kw = tok.value
            if kw == "let":
                return self.parse_let()
            if kw == "if":
                return self.parse_if()
            if kw == "while":
                return self.parse_while()
            if kw == "return":
                return self.parse_return()
            if kw == "break":
                if self.loop_depth <= 0:
                    self.error("'break' outside of a loop")
                self.advance()
                return ("break",)
            if kw == "continue":
                if self.loop_depth <= 0:
                    self.error("'continue' outside of a loop")
                self.advance()
                return ("continue",)
            if kw == "else":
                self.error("unexpected 'else'")
            # true / false / nil / not / fn begin an expression statement
            return ("expr", self.parse_expr())
        if tok.kind == "{":
            return ("block", self.parse_block_body())
        if tok.kind == "IDENT" and self.peek().kind == "=":
            name = self.advance().value
            self.advance()  # '='
            self.skip_newlines()
            return ("assign", name, self.parse_expr())
        return ("expr", self.parse_expr())

    def parse_let(self):
        self.advance()  # 'let'
        name = self.expect_ident()
        self.expect_op("=")
        self.skip_newlines()
        expr = self.parse_expr()
        return ("let", name, expr)

    def parse_if(self):
        self.enter()
        try:
            return self._parse_if()
        finally:
            self.leave()

    def _parse_if(self):
        self.advance()  # 'if'
        cond = self.parse_expr()
        self.skip_newlines()
        then_body = self.parse_block_body()
        else_body = None
        saved = self.pos
        self.skip_newlines()
        if self.is_kw("else"):
            self.advance()
            self.skip_newlines()
            if self.is_kw("if"):
                else_body = [self.parse_if()]
            else:
                else_body = self.parse_block_body()
        else:
            self.pos = saved
        return ("if", cond, then_body, else_body)

    def parse_while(self):
        self.advance()  # 'while'
        cond = self.parse_expr()
        self.skip_newlines()
        self.loop_depth += 1
        try:
            body = self.parse_block_body()
        finally:
            self.loop_depth -= 1
        return ("while", cond, body)

    def parse_return(self):
        self.advance()  # 'return'
        if self.fn_depth <= 0:
            self.error("'return' outside of a function")
        if self.cur().kind in ("NEWLINE", ";", "}", "EOF"):
            return ("return", None)
        return ("return", self.parse_expr())

    def parse_fn(self):
        self.advance()  # 'fn'
        self.expect_op("(")
        self.skip_newlines()
        params = []
        if not self.is_op(")"):
            while True:
                name = self.expect_ident()
                if name in params:
                    self.error("duplicate parameter %r" % name)
                params.append(name)
                self.skip_newlines()
                if self.is_op(","):
                    self.advance()
                    self.skip_newlines()
                    continue
                break
        self.expect_op(")")
        self.skip_newlines()
        if not self.is_op("{"):
            self.error("expected '{' to begin the function body")
        saved_loop = self.loop_depth
        self.fn_depth += 1
        self.loop_depth = 0
        try:
            body = self.parse_block_body()
        finally:
            self.fn_depth -= 1
            self.loop_depth = saved_loop
        return ("fn", params, body)

    # -- expressions ------------------------------------------------------
    def parse_expr(self):
        self.enter()
        try:
            return self.parse_or()
        finally:
            self.leave()

    def parse_or(self):
        left = self.parse_and()
        while self.is_kw("or"):
            self.advance()
            self.skip_newlines()
            right = self.parse_and()
            left = ("or", left, right)
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.is_kw("and"):
            self.advance()
            self.skip_newlines()
            right = self.parse_equality()
            left = ("and", left, right)
        return left

    def parse_equality(self):
        left = self.parse_comparison()
        if self.cur().kind in ("==", "!="):
            op = self.advance().kind
            self.skip_newlines()
            right = self.parse_comparison()
            if self.cur().kind in ("==", "!="):
                self.error("chained equality comparisons are not allowed")
            return ("binop", op, left, right)
        return left

    _RELATIONAL = ("<", "<=", ">", ">=")

    def parse_comparison(self):
        left = self.parse_additive()
        if self.cur().kind in self._RELATIONAL:
            op = self.advance().kind
            self.skip_newlines()
            right = self.parse_additive()
            if self.cur().kind in self._RELATIONAL:
                self.error("chained comparisons are not allowed")
            return ("binop", op, left, right)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.cur().kind in ("+", "-"):
            op = self.advance().kind
            self.skip_newlines()
            right = self.parse_multiplicative()
            left = ("binop", op, left, right)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.cur().kind in ("*", "/", "%"):
            op = self.advance().kind
            self.skip_newlines()
            right = self.parse_unary()
            left = ("binop", op, left, right)
        return left

    def parse_unary(self):
        self.enter()
        try:
            if self.is_op("-"):
                self.advance()
                self.skip_newlines()
                return ("unary", "-", self.parse_unary())
            if self.is_kw("not"):
                self.advance()
                self.skip_newlines()
                return ("unary", "not", self.parse_unary())
            return self.parse_power()
        finally:
            self.leave()

    def parse_power(self):
        base = self.parse_postfix()
        if self.is_op("**"):
            self.advance()
            self.skip_newlines()
            # Right associative; the exponent may start with a unary operator.
            exponent = self.parse_unary()
            return ("binop", "**", base, exponent)
        return base

    def parse_postfix(self):
        expr = self.parse_primary()
        while self.is_op("("):
            self.advance()
            self.skip_newlines()
            args = []
            if not self.is_op(")"):
                while True:
                    args.append(self.parse_expr())
                    self.skip_newlines()
                    if self.is_op(","):
                        self.advance()
                        self.skip_newlines()
                        continue
                    break
            self.expect_op(")")
            expr = ("call", expr, args)
        return expr

    def parse_primary(self):
        tok = self.cur()
        if tok.kind == "INT":
            self.advance()
            return ("int", tok.value)
        if tok.kind == "STR":
            self.advance()
            return ("str", tok.value)
        if tok.kind == "IDENT":
            self.advance()
            return ("var", tok.value)
        if tok.kind == "KW":
            kw = tok.value
            if kw == "true":
                self.advance()
                return ("bool", True)
            if kw == "false":
                self.advance()
                return ("bool", False)
            if kw == "nil":
                self.advance()
                return ("nil",)
            if kw == "fn":
                return self.parse_fn()
            self.error("unexpected keyword %r in expression" % kw)
        if tok.kind == "(":
            self.advance()
            self.skip_newlines()
            expr = self.parse_expr()
            self.skip_newlines()
            self.expect_op(")")
            return expr
        self.error("unexpected token")


# --------------------------------------------------------------------------
# Runtime values
# --------------------------------------------------------------------------


class Function:
    """A user defined function (closure)."""

    __slots__ = ("params", "body", "closure", "name")

    def __init__(self, params, body, closure, name=None):
        self.params = params
        self.body = body
        self.closure = closure
        self.name = name

    def __repr__(self):  # pragma: no cover - debugging helper
        return "<fn %s/%d>" % (self.name or "anonymous", len(self.params))


class Builtin:
    __slots__ = ("name", "arity", "func")

    def __init__(self, name, arity, func):
        self.name = name
        self.arity = arity
        self.func = func

    def __repr__(self):  # pragma: no cover - debugging helper
        return "<builtin %s>" % self.name


def type_name(value):
    if value is None:
        return "nil"
    t = type(value)
    if t is bool:
        return "bool"
    if t is int:
        return "int"
    if t is str:
        return "string"
    if isinstance(value, (Function, Builtin)):
        return "function"
    return "unknown"


def truthy(value):
    """Only `false` and `nil` are falsy."""
    return not (value is False or value is None)


def to_string(value):
    if value is None:
        return "nil"
    t = type(value)
    if t is bool:
        return "true" if value else "false"
    if t is int:
        return str(value)
    if t is str:
        return value
    raise LangError("cannot convert a %s to a string" % type_name(value))


def values_equal(a, b):
    ta = type_name(a)
    tb = type_name(b)
    if ta != tb:
        return False
    if ta == "nil":
        return True
    if ta == "function":
        return a is b
    return a == b


# --------------------------------------------------------------------------
# Environments
# --------------------------------------------------------------------------


class Env:
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def get(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise LangError("undefined variable %r" % name)

    def declare(self, name, value):
        if name in self.vars:
            raise LangError("variable %r is already declared in this scope" % name)
        self.vars[name] = value

    def assign(self, name, value):
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise LangError("assignment to undefined variable %r" % name)


# --------------------------------------------------------------------------
# Control flow signals
# --------------------------------------------------------------------------


class _Signal(BaseException):
    pass


class _Return(_Signal):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class _Break(_Signal):
    pass


class _Continue(_Signal):
    pass


# --------------------------------------------------------------------------
# Evaluator
# --------------------------------------------------------------------------

MAX_CALL_DEPTH = 12000


class Interpreter:
    def __init__(self):
        self.depth = 0

    # -- statements -------------------------------------------------------
    def exec_stmts(self, stmts, env):
        value = None
        for stmt in stmts:
            value = self.exec_stmt(stmt, env)
        return value

    def exec_stmt(self, stmt, env):
        tag = stmt[0]
        if tag == "expr":
            return self.eval(stmt[1], env)
        if tag == "let":
            _, name, expr = stmt
            value = self.eval(expr, env)
            if isinstance(value, Function) and value.name is None:
                value.name = name
            env.declare(name, value)
            return None
        if tag == "assign":
            _, name, expr = stmt
            value = self.eval(expr, env)
            env.assign(name, value)
            return None
        if tag == "if":
            _, cond, then_body, else_body = stmt
            if truthy(self.eval(cond, env)):
                self.exec_stmts(then_body, Env(env))
            elif else_body is not None:
                self.exec_stmts(else_body, Env(env))
            return None
        if tag == "while":
            _, cond, body = stmt
            while truthy(self.eval(cond, env)):
                try:
                    self.exec_stmts(body, Env(env))
                except _Continue:
                    continue
                except _Break:
                    break
            return None
        if tag == "block":
            self.exec_stmts(stmt[1], Env(env))
            return None
        if tag == "return":
            _, expr = stmt
            value = None if expr is None else self.eval(expr, env)
            raise _Return(value)
        if tag == "break":
            raise _Break()
        if tag == "continue":
            raise _Continue()
        raise LangError("internal error: unknown statement %r" % (tag,))

    # -- expressions ------------------------------------------------------
    def eval(self, expr, env):
        tag = expr[0]
        if tag == "int" or tag == "str":
            return expr[1]
        if tag == "bool":
            return expr[1]
        if tag == "nil":
            return None
        if tag == "var":
            return env.get(expr[1])
        if tag == "unary":
            return self.eval_unary(expr[1], expr[2], env)
        if tag == "binop":
            return self.eval_binop(expr[1], expr[2], expr[3], env)
        if tag == "and":
            left = self.eval(expr[1], env)
            if not truthy(left):
                return left
            return self.eval(expr[2], env)
        if tag == "or":
            left = self.eval(expr[1], env)
            if truthy(left):
                return left
            return self.eval(expr[2], env)
        if tag == "call":
            callee = self.eval(expr[1], env)
            args = [self.eval(a, env) for a in expr[2]]
            return self.call(callee, args)
        if tag == "fn":
            _, params, body = expr
            return Function(params, body, env)
        raise LangError("internal error: unknown expression %r" % (tag,))

    def eval_unary(self, op, operand_expr, env):
        value = self.eval(operand_expr, env)
        if op == "not":
            return not truthy(value)
        # op == '-'
        if type(value) is not int:
            raise LangError("unary '-' requires an int, got %s" % type_name(value))
        return -value

    def eval_binop(self, op, left_expr, right_expr, env):
        left = self.eval(left_expr, env)
        right = self.eval(right_expr, env)
        return self.binary(op, left, right)

    def binary(self, op, left, right):
        if op == "==":
            return values_equal(left, right)
        if op == "!=":
            return not values_equal(left, right)
        if op in ("<", "<=", ">", ">="):
            return self.compare(op, left, right)
        if op == "+":
            lt, rt = type(left), type(right)
            if lt is int and rt is int:
                return left + right
            if lt is str and rt is str:
                return left + right
            raise LangError(
                "cannot add %s and %s" % (type_name(left), type_name(right))
            )
        if op == "**":
            if type(left) is not int or type(right) is not int:
                raise LangError(
                    "'**' requires int operands, got %s and %s"
                    % (type_name(left), type_name(right))
                )
            if right < 0:
                raise LangError("negative exponent is not allowed")
            return left ** right
        # arithmetic: - * / %
        if type(left) is not int or type(right) is not int:
            raise LangError(
                "operator %r requires int operands, got %s and %s"
                % (op, type_name(left), type_name(right))
            )
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise LangError("division by zero")
            return left // right
        if op == "%":
            if right == 0:
                raise LangError("modulo by zero")
            return left % right
        raise LangError("internal error: unknown operator %r" % (op,))

    def compare(self, op, left, right):
        lt, rt = type(left), type(right)
        if lt is int and rt is int:
            pass
        elif lt is str and rt is str:
            pass
        else:
            raise LangError(
                "cannot compare %s and %s" % (type_name(left), type_name(right))
            )
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        return left >= right

    def call(self, callee, args):
        if isinstance(callee, Builtin):
            return self.call_builtin(callee, args)
        if isinstance(callee, Function):
            return self.call_function(callee, args)
        raise LangError("cannot call a %s value" % type_name(callee))

    def call_builtin(self, builtin, args):
        if len(args) != builtin.arity:
            raise LangError(
                "%s() takes %d argument(s), got %d"
                % (builtin.name, builtin.arity, len(args))
            )
        return builtin.func(args)

    def call_function(self, fn, args):
        if len(args) != len(fn.params):
            raise LangError(
                "function expects %d argument(s), got %d"
                % (len(fn.params), len(args))
            )
        self.depth += 1
        if self.depth > MAX_CALL_DEPTH:
            self.depth -= 1
            raise LangError("maximum recursion depth exceeded")
        try:
            env = Env(fn.closure)
            for name, value in zip(fn.params, args):
                env.vars[name] = value
            try:
                self.exec_stmts(fn.body, env)
            except _Return as ret:
                return ret.value
            return None
        finally:
            self.depth -= 1


# --------------------------------------------------------------------------
# Builtins
# --------------------------------------------------------------------------


def _builtin_len(args):
    value = args[0]
    if type(value) is not str:
        raise LangError("len() expects a string, got %s" % type_name(value))
    return len(value)


def _builtin_str(args):
    return to_string(args[0])


def _builtin_print(args):
    OUTPUT.append(to_string(args[0]))
    return None


def make_builtins_env():
    env = Env(None)
    env.vars["len"] = Builtin("len", 1, _builtin_len)
    env.vars["str"] = Builtin("str", 1, _builtin_str)
    env.vars["print"] = Builtin("print", 1, _builtin_print)
    return env


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _run(src):
    tokens = tokenize(src)
    parser = Parser(tokens)
    program = parser.parse_program()
    interpreter = Interpreter()
    env = Env(make_builtins_env())
    return interpreter.exec_stmts(program, env)


def run(src):
    """Evaluate ``src`` and return the value of its last expression."""
    if not isinstance(src, str):
        raise LangError("source code must be a string")
    OUTPUT.clear()
    try:
        return _run(src)
    except LangError:
        raise
    except RecursionError:
        raise LangError("maximum recursion depth exceeded") from None
    except _Signal:
        raise LangError("invalid control flow") from None
    except Exception as exc:  # never leak non-LangError exceptions
        raise LangError(str(exc) or exc.__class__.__name__) from None
