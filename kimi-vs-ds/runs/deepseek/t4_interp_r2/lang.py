"""A tiny expression language interpreter.

Public API:
    run(src: str) -> value
    LangError
    OUTPUT
"""

import sys

__all__ = ["run", "LangError", "OUTPUT"]

# Make room for reasonably deep user recursion.  We also impose our own
# language-level depth limit so that *pathological* recursion raises a
# LangError instead of blowing up the Python interpreter.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 100000))

# Python >= 3.11 caps the number of digits used when converting between
# ints and strings by default.  The language promises arbitrary size ints.
try:  # pragma: no cover - depends on Python version
    sys.set_int_max_str_digits(0)
except (AttributeError, ValueError):  # pragma: no cover
    pass

# List of strings produced by the `print` builtin during the most recent run.
OUTPUT = []


class LangError(Exception):
    """Any error produced while lexing, parsing or running a program."""


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

KEYWORDS = {
    "true",
    "false",
    "nil",
    "let",
    "if",
    "else",
    "while",
    "return",
    "break",
    "continue",
    "and",
    "or",
    "not",
    "fn",
}

TWO_CHAR_OPS = {"==", "!=", "<=", ">=", "**"}
ONE_CHAR_OPS = set("+-*/%<>(){}[],;=")


class Token:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Token(%r, %r, %d:%d)" % (self.kind, self.value, self.line, self.col)


def _error(msg, line=None, col=None):
    if line is not None:
        raise LangError("%s (line %d, column %d)" % (msg, line, col))
    raise LangError(msg)


def tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    line = 1
    col = 1
    while i < n:
        c = src[i]
        if c in " \t\r":
            i += 1
            col += 1
        elif c == "\n":
            tokens.append(Token("newline", "\n", line, col))
            i += 1
            line += 1
            col = 1
        elif c == "#":
            while i < n and src[i] != "\n":
                i += 1
                col += 1
        elif '0' <= c <= '9':
            start = i
            start_col = col
            while i < n and '0' <= src[i] <= '9':
                i += 1
                col += 1
            tokens.append(Token("int", int(src[start:i]), line, start_col))
        elif c == '"':
            start_col = col
            i += 1
            col += 1
            chars = []
            while True:
                if i >= n:
                    _error("Unterminated string literal", line, start_col)
                ch = src[i]
                if ch == '"':
                    i += 1
                    col += 1
                    break
                if ch == "\n":
                    _error("Unterminated string literal", line, start_col)
                if ch == "\\":
                    if i + 1 >= n:
                        _error("Unterminated string literal", line, start_col)
                    esc = src[i + 1]
                    if esc == '"':
                        chars.append('"')
                    elif esc == "\\":
                        chars.append("\\")
                    elif esc == "n":
                        chars.append("\n")
                    else:
                        _error("Invalid escape sequence '\\%s'" % esc, line, col)
                    i += 2
                    col += 2
                    continue
                chars.append(ch)
                i += 1
                col += 1
            tokens.append(Token("str", "".join(chars), line, start_col))
        elif ('a' <= c <= 'z') or ('A' <= c <= 'Z') or c == "_":
            start = i
            start_col = col
            while i < n and (
                ('a' <= src[i] <= 'z')
                or ('A' <= src[i] <= 'Z')
                or ('0' <= src[i] <= '9')
                or src[i] == "_"
            ):
                i += 1
                col += 1
            word = src[start:i]
            if word in KEYWORDS:
                tokens.append(Token("kw", word, line, start_col))
            else:
                tokens.append(Token("ident", word, line, start_col))
        elif src[i : i + 2] in TWO_CHAR_OPS:
            tokens.append(Token("op", src[i : i + 2], line, col))
            i += 2
            col += 2
        elif c in ONE_CHAR_OPS:
            tokens.append(Token("op", c, line, col))
            i += 1
            col += 1
        else:
            _error("Unexpected character %r" % c, line, col)
    tokens.append(Token("eof", None, line, col))
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
#
# AST nodes are plain tuples:
#   expressions: ('int', v) ('str', v) ('bool', v) ('nil',)
#                ('var', name) ('bin', op, l, r) ('unary', op, e)
#                ('and', l, r) ('or', l, r) ('call', fn, [args])
#                ('fn', [params], [body stmts])
#   statements:  ('expr', e) ('let', name, e) ('assign', name, e)
#                ('if', cond, [then], [else] | None) ('while', cond, [body])
#                ('return', e | None) ('break',) ('continue',)
#                ('block', [stmts])


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.func_depth = 0
        self.loop_depth = 0

    # -- token utilities ---------------------------------------------------
    def peek(self, k=0):
        idx = self.pos + k
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def check(self, kind, value=None, k=0):
        t = self.peek(k)
        if t.kind != kind:
            return False
        return value is None or t.value == value

    def advance(self):
        t = self.peek()
        if t.kind != "eof":
            self.pos += 1
        return t

    def match(self, kind, value=None):
        if self.check(kind, value):
            self.advance()
            return True
        return False

    def expect(self, kind, value=None):
        if not self.check(kind, value):
            t = self.peek()
            _error(
                "Expected %s but found %r"
                % (value if value is not None else kind, t.value),
                t.line,
                t.col,
            )
        return self.advance()

    def skip_newlines(self):
        while self.check("newline"):
            self.advance()

    def skip_separators(self):
        while self.check("newline") or self.check("op", ";"):
            self.advance()

    def at_statement_end(self):
        return (
            self.check("newline")
            or self.check("op", ";")
            or self.check("op", "}")
            or self.check("eof")
        )

    # -- program / blocks --------------------------------------------------
    def parse_program(self):
        stmts = self.parse_statement_list(until_eof=True)
        self.expect("eof")
        return stmts

    def parse_statement_list(self, until_eof=False):
        stmts = []
        while True:
            self.skip_separators()
            if until_eof:
                if self.check("eof"):
                    break
            else:
                if self.check("op", "}"):
                    break
                if self.check("eof"):
                    _error(
                        "Unexpected end of input; expected '}'",
                        self.peek().line,
                        self.peek().col,
                    )
            stmt = self.parse_statement()
            stmts.append(stmt)
            # Statements that end in a closing brace may be followed
            # immediately by another statement (e.g. an `if` block followed
            # by `return` on the same line).
            if stmt[0] in ("if", "while", "block"):
                continue
            if not self.at_statement_end():
                t = self.peek()
                _error(
                    "Expected ';' or newline between statements but found %r"
                    % (t.value,),
                    t.line,
                    t.col,
                )
        return stmts

    # -- statements --------------------------------------------------------
    def parse_statement(self):
        t = self.peek()
        if t.kind == "kw":
            if t.value == "let":
                return self.parse_let()
            if t.value == "if":
                return self.parse_if()
            if t.value == "while":
                return self.parse_while()
            if t.value == "return":
                return self.parse_return()
            if t.value == "break":
                self.advance()
                if self.loop_depth == 0:
                    _error("'break' outside of a loop", t.line, t.col)
                return ("break",)
            if t.value == "continue":
                self.advance()
                if self.loop_depth == 0:
                    _error("'continue' outside of a loop", t.line, t.col)
                return ("continue",)
        if self.check("op", "{"):
            self.advance()
            body = self.parse_statement_list()
            self.expect("op", "}")
            return ("block", body)
        if t.kind == "ident" and self.check("op", "=", k=1):
            self.advance()  # name
            self.advance()  # '='
            expr = self.parse_expression()
            return ("assign", t.value, expr)
        expr = self.parse_expression()
        return ("expr", expr)

    def parse_let(self):
        self.advance()  # 'let'
        name_tok = self.expect("ident")
        self.expect("op", "=")
        expr = self.parse_expression()
        return ("let", name_tok.value, expr)

    def parse_return(self):
        t = self.advance()  # 'return'
        if self.func_depth == 0:
            _error("'return' outside of a function", t.line, t.col)
        if self.at_statement_end():
            return ("return", None)
        expr = self.parse_expression()
        return ("return", expr)

    def parse_if(self):
        self.advance()  # 'if'
        cond = self.parse_expression()
        self.expect("op", "{")
        then_body = self.parse_statement_list()
        self.expect("op", "}")

        # Look past newlines for an `else`, but do not consume them if the
        # statement is actually followed by an unrelated statement.
        save = self.pos
        self.skip_newlines()
        else_body = None
        if self.check("kw", "else"):
            self.advance()
            self.skip_newlines()
            if self.check("kw", "if"):
                else_body = [self.parse_if()]
            elif self.check("op", "{"):
                self.advance()
                else_body = self.parse_statement_list()
                self.expect("op", "}")
            else:
                t = self.peek()
                _error("Expected '{' or 'if' after 'else'", t.line, t.col)
        else:
            self.pos = save
        return ("if", cond, then_body, else_body)

    def parse_while(self):
        self.advance()  # 'while'
        cond = self.parse_expression()
        self.expect("op", "{")
        self.loop_depth += 1
        try:
            body = self.parse_statement_list()
        finally:
            self.loop_depth -= 1
        self.expect("op", "}")
        return ("while", cond, body)

    # -- expressions -------------------------------------------------------
    def parse_expression(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.check("kw", "or"):
            self.advance()
            right = self.parse_and()
            left = ("or", left, right)
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.check("kw", "and"):
            self.advance()
            right = self.parse_equality()
            left = ("and", left, right)
        return left

    def parse_equality(self):
        left = self.parse_comparison()
        if self.check("op", "==") or self.check("op", "!="):
            op = self.advance().value
            right = self.parse_comparison()
            if self.check("op", "==") or self.check("op", "!="):
                t = self.peek()
                _error("Chained equality comparisons are not allowed", t.line, t.col)
            left = ("bin", op, left, right)
        return left

    def parse_comparison(self):
        left = self.parse_additive()
        if (
            self.check("op", "<")
            or self.check("op", "<=")
            or self.check("op", ">")
            or self.check("op", ">=")
        ):
            op = self.advance().value
            right = self.parse_additive()
            if (
                self.check("op", "<")
                or self.check("op", "<=")
                or self.check("op", ">")
                or self.check("op", ">=")
            ):
                t = self.peek()
                _error("Chained comparisons are not allowed", t.line, t.col)
            left = ("bin", op, left, right)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.check("op", "+") or self.check("op", "-"):
            op = self.advance().value
            right = self.parse_multiplicative()
            left = ("bin", op, left, right)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while (
            self.check("op", "*")
            or self.check("op", "/")
            or self.check("op", "%")
        ):
            op = self.advance().value
            right = self.parse_unary()
            left = ("bin", op, left, right)
        return left

    def parse_unary(self):
        if self.check("kw", "not"):
            self.advance()
            return ("unary", "not", self.parse_unary())
        if self.check("op", "-"):
            self.advance()
            return ("unary", "-", self.parse_unary())
        return self.parse_power()

    def parse_power(self):
        left = self.parse_postfix()
        if self.check("op", "**"):
            self.advance()
            right = self.parse_unary()
            return ("bin", "**", left, right)
        return left

    def parse_postfix(self):
        expr = self.parse_primary()
        while self.check("op", "("):
            self.advance()
            args = []
            self.skip_newlines()
            if not self.check("op", ")"):
                while True:
                    args.append(self.parse_expression())
                    self.skip_newlines()
                    if self.match("op", ","):
                        self.skip_newlines()
                        continue
                    break
            self.expect("op", ")")
            expr = ("call", expr, args)
        return expr

    def parse_primary(self):
        t = self.peek()
        if t.kind == "int":
            self.advance()
            return ("int", t.value)
        if t.kind == "str":
            self.advance()
            return ("str", t.value)
        if t.kind == "kw":
            if t.value == "true":
                self.advance()
                return ("bool", True)
            if t.value == "false":
                self.advance()
                return ("bool", False)
            if t.value == "nil":
                self.advance()
                return ("nil",)
            if t.value == "fn":
                return self.parse_fn()
        if t.kind == "ident":
            self.advance()
            return ("var", t.value)
        if self.check("op", "("):
            self.advance()
            self.skip_newlines()
            expr = self.parse_expression()
            self.skip_newlines()
            self.expect("op", ")")
            return expr
        _error("Unexpected token %r" % (t.value,), t.line, t.col)

    def parse_fn(self):
        self.advance()  # 'fn'
        self.expect("op", "(")
        params = []
        self.skip_newlines()
        if not self.check("op", ")"):
            while True:
                p = self.expect("ident")
                if p.value in params:
                    _error(
                        "Duplicate parameter name %r" % p.value, p.line, p.col
                    )
                params.append(p.value)
                self.skip_newlines()
                if self.match("op", ","):
                    self.skip_newlines()
                    continue
                break
        self.expect("op", ")")
        self.skip_newlines()
        self.expect("op", "{")
        saved_loop = self.loop_depth
        self.loop_depth = 0
        self.func_depth += 1
        try:
            body = self.parse_statement_list()
        finally:
            self.func_depth -= 1
            self.loop_depth = saved_loop
        self.expect("op", "}")
        return ("fn", params, body)


# ---------------------------------------------------------------------------
# Runtime values and environment
# ---------------------------------------------------------------------------


class Env:
    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def declare(self, name, value):
        if name in self.vars:
            raise LangError("Variable %r already declared in this scope" % name)
        self.vars[name] = value

    def get(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise LangError("Undefined variable %r" % name)

    def set(self, name, value):
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return
            env = env.parent
        raise LangError("Assignment to undefined variable %r" % name)


class Function:
    __slots__ = ("params", "body", "closure")

    def __init__(self, params, body, closure):
        self.params = params
        self.body = body
        self.closure = closure


class Builtin:
    __slots__ = ("name", "arity", "fn")

    def __init__(self, name, arity, fn):
        self.name = name
        self.arity = arity
        self.fn = fn


class ReturnSignal(Exception):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------

MAX_CALL_DEPTH = 3000


def is_truthy(v):
    return not (v is False or v is None)


def value_type(v):
    if v is None:
        return "nil"
    if type(v) is bool:
        return "bool"
    if type(v) is int:
        return "int"
    if type(v) is str:
        return "string"
    if isinstance(v, (Function, Builtin)):
        return "function"
    return "unknown"


def to_string(v):
    t = value_type(v)
    if t == "int":
        return str(v)
    if t == "bool":
        return "true" if v else "false"
    if t == "nil":
        return "nil"
    if t == "string":
        return v
    raise LangError("Cannot convert value of type %s to string" % t)


def check_int(v, what="operand"):
    if type(v) is not int:
        raise LangError("Expected int for %s, got %s" % (what, value_type(v)))
    return v


def lang_equal(a, b):
    ta = value_type(a)
    tb = value_type(b)
    if ta != tb:
        return False
    if ta == "nil":
        return True
    if ta == "function":
        return a is b
    return a == b


def lang_compare(op, a, b):
    ta = value_type(a)
    tb = value_type(b)
    if ta != tb or ta not in ("int", "string"):
        raise LangError(
            "Cannot compare %s and %s with %r" % (ta, tb, op)
        )
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def make_builtins():
    env = Env()

    def b_len(args):
        s = args[0]
        if type(s) is not str:
            raise LangError("len() expects a string, got %s" % value_type(s))
        return len(s)

    def b_str(args):
        return to_string(args[0])

    def b_print(args):
        OUTPUT.append(to_string(args[0]))
        return None

    env.declare("len", Builtin("len", 1, b_len))
    env.declare("str", Builtin("str", 1, b_str))
    env.declare("print", Builtin("print", 1, b_print))
    return env


class Interpreter:
    def __init__(self):
        self.depth = 0

    # -- expressions -------------------------------------------------------
    def eval_expr(self, node, env):
        tag = node[0]
        if tag == "int" or tag == "str" or tag == "bool":
            return node[1]
        if tag == "nil":
            return None
        if tag == "var":
            return env.get(node[1])
        if tag == "unary":
            op = node[1]
            val = self.eval_expr(node[2], env)
            if op == "not":
                return not is_truthy(val)
            # unary minus
            check_int(val, "unary '-'")
            return -val
        if tag == "and":
            left = self.eval_expr(node[1], env)
            if not is_truthy(left):
                return left
            return self.eval_expr(node[2], env)
        if tag == "or":
            left = self.eval_expr(node[1], env)
            if is_truthy(left):
                return left
            return self.eval_expr(node[2], env)
        if tag == "bin":
            return self.eval_bin(node[1], node[2], node[3], env)
        if tag == "call":
            fn = self.eval_expr(node[1], env)
            args = [self.eval_expr(a, env) for a in node[2]]
            return self.call(fn, args)
        if tag == "fn":
            return Function(node[1], node[2], env)
        raise LangError("Internal error: unknown expression node %r" % (tag,))

    def eval_bin(self, op, left_node, right_node, env):
        if op == "==":
            return lang_equal(
                self.eval_expr(left_node, env), self.eval_expr(right_node, env)
            )
        if op == "!=":
            return not lang_equal(
                self.eval_expr(left_node, env), self.eval_expr(right_node, env)
            )
        if op in ("<", "<=", ">", ">="):
            return lang_compare(
                op, self.eval_expr(left_node, env), self.eval_expr(right_node, env)
            )

        a = self.eval_expr(left_node, env)
        b = self.eval_expr(right_node, env)

        if op == "+":
            if type(a) is int and type(b) is int:
                return a + b
            if type(a) is str and type(b) is str:
                return a + b
            raise LangError(
                "Cannot add %s and %s" % (value_type(a), value_type(b))
            )
        if op == "-":
            check_int(a, "'-'")
            check_int(b, "'-'")
            return a - b
        if op == "*":
            check_int(a, "'*'")
            check_int(b, "'*'")
            return a * b
        if op == "/":
            check_int(a, "'/'")
            check_int(b, "'/'")
            if b == 0:
                raise LangError("Division by zero")
            return a // b
        if op == "%":
            check_int(a, "'%'")
            check_int(b, "'%'")
            if b == 0:
                raise LangError("Division by zero")
            return a % b
        if op == "**":
            check_int(a, "'**'")
            check_int(b, "'**'")
            if b < 0:
                raise LangError("Negative exponent")
            return a ** b
        raise LangError("Internal error: unknown operator %r" % (op,))

    # -- calls -------------------------------------------------------------
    def call(self, fn, args):
        if isinstance(fn, Builtin):
            if len(args) != fn.arity:
                raise LangError(
                    "%s() takes %d argument(s), got %d"
                    % (fn.name, fn.arity, len(args))
                )
            return fn.fn(args)
        if isinstance(fn, Function):
            if len(args) != len(fn.params):
                raise LangError(
                    "Function takes %d argument(s), got %d"
                    % (len(fn.params), len(args))
                )
            if self.depth >= MAX_CALL_DEPTH:
                raise LangError("Maximum recursion depth exceeded")
            call_env = Env(fn.closure)
            for name, value in zip(fn.params, args):
                call_env.declare(name, value)
            self.depth += 1
            try:
                try:
                    # The body's braces form a block, i.e. a fresh scope
                    # nested inside the parameter scope.
                    self.exec_stmts(fn.body, Env(call_env))
                except ReturnSignal as ret:
                    return ret.value
                return None
            finally:
                self.depth -= 1
        raise LangError("Cannot call a value of type %s" % value_type(fn))

    # -- statements --------------------------------------------------------
    def exec_stmts(self, stmts, env):
        result = None
        for stmt in stmts:
            result = self.exec_stmt(stmt, env)
        return result

    def exec_stmt(self, stmt, env):
        tag = stmt[0]
        if tag == "expr":
            return self.eval_expr(stmt[1], env)
        if tag == "let":
            value = self.eval_expr(stmt[2], env)
            env.declare(stmt[1], value)
            return None
        if tag == "assign":
            value = self.eval_expr(stmt[2], env)
            env.set(stmt[1], value)
            return None
        if tag == "block":
            self.exec_stmts(stmt[1], Env(env))
            return None
        if tag == "if":
            if is_truthy(self.eval_expr(stmt[1], env)):
                self.exec_stmts(stmt[2], Env(env))
            elif stmt[3] is not None:
                self.exec_stmts(stmt[3], Env(env))
            return None
        if tag == "while":
            while is_truthy(self.eval_expr(stmt[1], env)):
                try:
                    self.exec_stmts(stmt[2], Env(env))
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
            return None
        if tag == "return":
            value = None if stmt[1] is None else self.eval_expr(stmt[1], env)
            raise ReturnSignal(value)
        if tag == "break":
            raise BreakSignal()
        if tag == "continue":
            raise ContinueSignal()
        raise LangError("Internal error: unknown statement node %r" % (tag,))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(src):
    OUTPUT.clear()
    if not isinstance(src, str):
        raise LangError("Source must be a string")
    try:
        tokens = tokenize(src)
        parser = Parser(tokens)
        stmts = parser.parse_program()
        interp = Interpreter()
        env = Env(make_builtins())
        return interp.exec_stmts(stmts, env)
    except LangError:
        raise
    except RecursionError:
        raise LangError("Maximum recursion depth exceeded")
    except (BreakSignal, ContinueSignal):
        raise LangError("'break' or 'continue' used outside of a loop")
    except ReturnSignal:
        raise LangError("'return' used outside of a function")
    except Exception as exc:  # never leak internal exception types
        raise LangError(str(exc))
