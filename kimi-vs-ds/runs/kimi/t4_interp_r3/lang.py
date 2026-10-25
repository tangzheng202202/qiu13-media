"""A small tree-walking interpreter for the language described in SPEC.md."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Callable


class LangError(Exception):
    """A syntax or runtime error in the guest language."""


# print/1 deliberately appends to this list rather than writing to stdout.  Keep
# the list object stable so that ``from lang import OUTPUT`` works as expected.
OUTPUT: list[str] = []

# Python 3.11+ otherwise limits decimal conversion to a few thousand digits.
# The language puts no such limit on its integers.
if hasattr(sys, "set_int_max_str_digits"):
    try:
        sys.set_int_max_str_digits(0)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Lexer


@dataclass(slots=True)
class _Token:
    kind: str
    value: Any
    line: int
    column: int


_KEYWORDS = {
    "let": "LET",
    "if": "IF",
    "else": "ELSE",
    "while": "WHILE",
    "return": "RETURN",
    "break": "BREAK",
    "continue": "CONTINUE",
    "fn": "FN",
    "true": "TRUE",
    "false": "FALSE",
    "nil": "NIL",
    "and": "AND",
    "or": "OR",
    "not": "NOT",
}


class _Lexer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.length = len(source)
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: list[_Token] = []

    def error(self, message: str, line: int | None = None, column: int | None = None) -> None:
        line = self.line if line is None else line
        column = self.column if column is None else column
        raise LangError(f"{message} at line {line}, column {column}")

    def peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.source[index] if index < self.length else ""

    def advance(self) -> str:
        char = self.source[self.pos]
        self.pos += 1
        self.column += 1
        return char

    def add(self, kind: str, value: Any, line: int, column: int) -> None:
        self.tokens.append(_Token(kind, value, line, column))

    def scan(self) -> list[_Token]:
        while self.pos < self.length:
            char = self.peek()

            if char in " \t\f\v":
                self.advance()
                continue

            if char == "#":
                while self.pos < self.length and self.peek() not in "\r\n":
                    self.advance()
                continue

            if char in "\r\n":
                line, column = self.line, self.column
                if char == "\r":
                    self.advance()
                    if self.peek() == "\n":
                        self.advance()
                else:
                    self.advance()
                self.line += 1
                self.column = 1
                self.add("NEWLINE", None, line, column)
                continue

            line, column = self.line, self.column

            if "0" <= char <= "9":
                start = self.pos
                while "0" <= self.peek() <= "9":
                    self.advance()
                text = self.source[start:self.pos]
                self.add("INT", int(text), line, column)
                continue

            if ("A" <= char <= "Z") or ("a" <= char <= "z") or char == "_":
                start = self.pos
                while True:
                    current = self.peek()
                    if not (
                        ("A" <= current <= "Z")
                        or ("a" <= current <= "z")
                        or ("0" <= current <= "9")
                        or current == "_"
                    ):
                        break
                    self.advance()
                text = self.source[start:self.pos]
                self.add(_KEYWORDS.get(text, "IDENT"), text, line, column)
                continue

            if char == '"':
                self.add("STRING", self.scan_string(), line, column)
                continue

            two = char + self.peek(1)
            if two in {"==", "!=", "<=", ">=", "**"}:
                self.advance()
                self.advance()
                self.add(two, two, line, column)
                continue

            if char in "{}();,+-*/%=<>":
                self.advance()
                self.add(char, char, line, column)
                continue

            self.error(f"unexpected character {char!r}")

        self.tokens.append(_Token("EOF", None, self.line, self.column))
        return self.tokens

    def scan_string(self) -> str:
        start_line, start_column = self.line, self.column
        self.advance()  # opening quote
        chars: list[str] = []
        escapes = {'"': '"', "\\": "\\", "n": "\n"}

        while self.pos < self.length:
            char = self.advance()
            if char == '"':
                return "".join(chars)
            if char in "\r\n":
                self.error("unterminated string", start_line, start_column)
            if char == "\\":
                if self.pos >= self.length:
                    self.error("unterminated string", start_line, start_column)
                escape = self.advance()
                if escape not in escapes:
                    self.error(f"invalid escape \\{escape}")
                chars.append(escapes[escape])
            else:
                chars.append(char)

        self.error("unterminated string", start_line, start_column)
        raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# AST


@dataclass(slots=True)
class _Literal:
    value: Any


@dataclass(slots=True)
class _Variable:
    name: str
    token: _Token


@dataclass(slots=True)
class _Unary:
    operator: str
    right: Any
    token: _Token


@dataclass(slots=True)
class _Binary:
    operator: str
    left: Any
    right: Any
    token: _Token


@dataclass(slots=True)
class _Logical:
    operator: str
    left: Any
    right: Any


@dataclass(slots=True)
class _Call:
    callee: Any
    arguments: list[Any]
    token: _Token


@dataclass(slots=True)
class _FunctionExpr:
    parameters: list[str]
    body: Any
    token: _Token


@dataclass(slots=True)
class _Let:
    name: str
    initializer: Any


@dataclass(slots=True)
class _Assign:
    name: str
    value: Any
    token: _Token


@dataclass(slots=True)
class _ExpressionStatement:
    expression: Any


@dataclass(slots=True)
class _Block:
    statements: list[Any]


@dataclass(slots=True)
class _If:
    condition: Any
    then_branch: _Block
    else_branch: Any


@dataclass(slots=True)
class _While:
    condition: Any
    body: _Block


@dataclass(slots=True)
class _Return:
    value: Any


@dataclass(slots=True)
class _Break:
    pass


@dataclass(slots=True)
class _Continue:
    pass


# ---------------------------------------------------------------------------
# Parser


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.function_depth = 0
        self.loop_depth = 0

    @property
    def current(self) -> _Token:
        return self.tokens[self.pos]

    def check(self, *kinds: str) -> bool:
        return self.current.kind in kinds

    def match(self, *kinds: str) -> _Token | None:
        if self.check(*kinds):
            token = self.current
            self.pos += 1
            return token
        return None

    def consume(self, kind: str, message: str) -> _Token:
        token = self.match(kind)
        if token is None:
            self.error(message)
        return token

    def error(self, message: str, token: _Token | None = None) -> None:
        token = self.current if token is None else token
        raise LangError(f"{message} at line {token.line}, column {token.column}")

    def skip_newlines(self) -> None:
        while self.match("NEWLINE") is not None:
            pass

    def skip_separators(self) -> None:
        while self.match("NEWLINE", ";") is not None:
            pass

    def parse(self) -> list[Any]:
        statements = self.statement_list("EOF")
        self.consume("EOF", "expected end of input")
        return statements

    def statement_list(self, stop: str) -> list[Any]:
        statements: list[Any] = []
        self.skip_separators()
        while not self.check(stop, "EOF"):
            statements.append(self.statement())
            if self.check("NEWLINE", ";"):
                self.skip_separators()
            elif not self.check(stop, "EOF"):
                self.error("expected a newline or ';' between statements")
        return statements

    def statement(self) -> Any:
        if self.match("LET") is not None:
            return self.let_statement()
        if self.match("IF") is not None:
            return self.if_statement()
        if self.match("WHILE") is not None:
            return self.while_statement()
        if self.match("RETURN") is not None:
            return self.return_statement()
        if (token := self.match("BREAK")) is not None:
            if self.loop_depth == 0:
                self.error("'break' outside a loop", token)
            return _Break()
        if (token := self.match("CONTINUE")) is not None:
            if self.loop_depth == 0:
                self.error("'continue' outside a loop", token)
            return _Continue()

        if self.check("IDENT") and self.tokens[self.pos + 1].kind == "=":
            name_token = self.current
            self.pos += 2
            self.skip_newlines()
            return _Assign(name_token.value, self.expression(), name_token)

        return _ExpressionStatement(self.expression())

    def let_statement(self) -> _Let:
        name = self.consume("IDENT", "expected an identifier after 'let'")
        self.consume("=", "expected '=' after the variable name")
        self.skip_newlines()
        return _Let(name.value, self.expression())

    def if_statement(self) -> _If:
        self.skip_newlines()
        condition = self.expression()
        self.skip_newlines()
        then_branch = self.block()

        # A newline before `else` does not end the if statement.  If there is no
        # else, restore the position so the enclosing statement list sees its
        # separator.
        saved = self.pos
        self.skip_newlines()
        if self.match("ELSE") is not None:
            self.skip_newlines()
            if self.match("IF") is not None:
                else_branch: Any = self.if_statement()
            else:
                else_branch = self.block()
        else:
            self.pos = saved
            else_branch = None
        return _If(condition, then_branch, else_branch)

    def while_statement(self) -> _While:
        self.skip_newlines()
        condition = self.expression()
        self.skip_newlines()
        self.loop_depth += 1
        try:
            body = self.block()
        finally:
            self.loop_depth -= 1
        return _While(condition, body)

    def return_statement(self) -> _Return:
        if self.function_depth == 0:
            self.error("'return' outside a function")
        if self.check("NEWLINE", ";", "}", "EOF"):
            return _Return(None)
        return _Return(self.expression())

    def block(self) -> _Block:
        self.consume("{", "expected '{'")
        statements = self.statement_list("}")
        self.consume("}", "expected '}' after block")
        return _Block(statements)

    def function_literal(self, token: _Token) -> _FunctionExpr:
        self.skip_newlines()
        self.consume("(", "expected '(' after 'fn'")
        self.skip_newlines()
        parameters: list[str] = []
        if not self.check(")"):
            while True:
                name = self.consume("IDENT", "expected a parameter name")
                if name.value in parameters:
                    self.error(f"duplicate parameter {name.value!r}", name)
                parameters.append(name.value)
                self.skip_newlines()
                if self.match(",") is None:
                    break
                self.skip_newlines()
                if self.check(")"):
                    self.error("expected a parameter name after ','")
        self.consume(")", "expected ')' after parameters")
        self.skip_newlines()

        old_loop_depth = self.loop_depth
        self.function_depth += 1
        self.loop_depth = 0
        try:
            body = self.block()
        finally:
            self.function_depth -= 1
            self.loop_depth = old_loop_depth
        return _FunctionExpr(parameters, body, token)

    def expression(self) -> Any:
        return self.or_expression()

    def or_expression(self) -> Any:
        expr = self.and_expression()
        while self.match("OR") is not None:
            self.skip_newlines()
            expr = _Logical("or", expr, self.and_expression())
        return expr

    def and_expression(self) -> Any:
        expr = self.equality_expression()
        while self.match("AND") is not None:
            self.skip_newlines()
            expr = _Logical("and", expr, self.equality_expression())
        return expr

    def equality_expression(self) -> Any:
        expr = self.comparison_expression()
        if (token := self.match("==", "!=")) is not None:
            self.skip_newlines()
            expr = _Binary(token.kind, expr, self.comparison_expression(), token)
            if self.check("==", "!="):
                self.error("equality operators cannot be chained")
        return expr

    def comparison_expression(self) -> Any:
        expr = self.additive_expression()
        if (token := self.match("<", "<=", ">", ">=")) is not None:
            self.skip_newlines()
            expr = _Binary(token.kind, expr, self.additive_expression(), token)
            if self.check("<", "<=", ">", ">="):
                self.error("comparison operators cannot be chained")
        return expr

    def additive_expression(self) -> Any:
        expr = self.multiplicative_expression()
        while (token := self.match("+", "-")) is not None:
            self.skip_newlines()
            expr = _Binary(token.kind, expr, self.multiplicative_expression(), token)
        return expr

    def multiplicative_expression(self) -> Any:
        expr = self.unary_expression()
        while (token := self.match("*", "/", "%")) is not None:
            self.skip_newlines()
            expr = _Binary(token.kind, expr, self.unary_expression(), token)
        return expr

    def unary_expression(self) -> Any:
        if (token := self.match("-", "NOT")) is not None:
            self.skip_newlines()
            return _Unary(token.kind, self.unary_expression(), token)
        return self.power_expression()

    def power_expression(self) -> Any:
        expr = self.call_expression()
        if (token := self.match("**")) is not None:
            self.skip_newlines()
            # Using unary_expression here both permits `2 ** -1` to parse and
            # makes exponentiation right associative.
            expr = _Binary("**", expr, self.unary_expression(), token)
        return expr

    def call_expression(self) -> Any:
        expr = self.primary()
        while (token := self.match("(")) is not None:
            self.skip_newlines()
            arguments: list[Any] = []
            if not self.check(")"):
                while True:
                    arguments.append(self.expression())
                    self.skip_newlines()
                    if self.match(",") is None:
                        break
                    self.skip_newlines()
                    if self.check(")"):
                        self.error("expected an argument after ','")
            self.consume(")", "expected ')' after arguments")
            expr = _Call(expr, arguments, token)
        return expr

    def primary(self) -> Any:
        if (token := self.match("INT", "STRING")) is not None:
            return _Literal(token.value)
        if self.match("TRUE") is not None:
            return _Literal(True)
        if self.match("FALSE") is not None:
            return _Literal(False)
        if self.match("NIL") is not None:
            return _Literal(None)
        if (token := self.match("IDENT")) is not None:
            return _Variable(token.value, token)
        if (token := self.match("FN")) is not None:
            return self.function_literal(token)
        if self.match("(") is not None:
            self.skip_newlines()
            expr = self.expression()
            self.skip_newlines()
            self.consume(")", "expected ')' after expression")
            return expr
        self.error("expected an expression")
        raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Evaluator


class _Environment:
    __slots__ = ("values", "parent")

    def __init__(self, parent: _Environment | None = None) -> None:
        self.values: dict[str, Any] = {}
        self.parent = parent

    def get(self, name: str) -> Any:
        environment: _Environment | None = self
        while environment is not None:
            if name in environment.values:
                return environment.values[name]
            environment = environment.parent
        raise LangError(f"undefined name {name!r}")

    def define(self, name: str, value: Any) -> None:
        if name in self.values:
            raise LangError(f"name {name!r} is already declared in this scope")
        self.values[name] = value

    def assign(self, name: str, value: Any) -> None:
        environment: _Environment | None = self
        while environment is not None:
            if name in environment.values:
                environment.values[name] = value
                return
            environment = environment.parent
        raise LangError(f"cannot assign undefined name {name!r}")


@dataclass(slots=True, eq=False)
class _Function:
    parameters: list[str]
    body: _Block
    closure: _Environment

    def __repr__(self) -> str:
        return "<function>"


@dataclass(slots=True, eq=False)
class _Builtin:
    name: str
    arity: int
    implementation: Callable[[list[Any]], Any]

    def __repr__(self) -> str:
        return f"<builtin {self.name}>"


class _ReturnSignal(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


class _BreakSignal(Exception):
    pass


class _ContinueSignal(Exception):
    pass


def truthy(value: Any) -> bool:
    return value is not None and value is not False


def language_string(value: Any) -> str:
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return value
    raise LangError("str() does not support functions")


def _builtin_len(arguments: list[Any]) -> int:
    value = arguments[0]
    if type(value) is not str:
        raise LangError("len() expects a string")
    return len(value)


def _builtin_str(arguments: list[Any]) -> str:
    return language_string(arguments[0])


def _builtin_print(arguments: list[Any]) -> None:
    OUTPUT.append(language_string(arguments[0]))
    return None


def new_global_environment() -> _Environment:
    builtins = _Environment()
    builtins.values = {
        "len": _Builtin("len", 1, _builtin_len),
        "str": _Builtin("str", 1, _builtin_str),
        "print": _Builtin("print", 1, _builtin_print),
    }
    return _Environment(builtins)


def execute_block(block: _Block, parent: _Environment) -> Any:
    return execute_statements(block.statements, _Environment(parent))


def execute_statements(statements: list[Any], environment: _Environment) -> Any:
    result = None
    for statement in statements:
        result = execute_statement(statement, environment)
    return result


def execute_statement(statement: Any, environment: _Environment) -> Any:
    if isinstance(statement, _ExpressionStatement):
        return evaluate(statement.expression, environment)

    if isinstance(statement, _Let):
        value = evaluate(statement.initializer, environment)
        environment.define(statement.name, value)
        return None

    if isinstance(statement, _Assign):
        value = evaluate(statement.value, environment)
        environment.assign(statement.name, value)
        return None

    if isinstance(statement, _If):
        if truthy(evaluate(statement.condition, environment)):
            execute_block(statement.then_branch, environment)
        elif statement.else_branch is not None:
            if isinstance(statement.else_branch, _If):
                execute_statement(statement.else_branch, environment)
            else:
                execute_block(statement.else_branch, environment)
        return None

    if isinstance(statement, _While):
        while truthy(evaluate(statement.condition, environment)):
            try:
                execute_block(statement.body, environment)
            except _BreakSignal:
                break
            except _ContinueSignal:
                continue
        return None

    if isinstance(statement, _Return):
        value = None if statement.value is None else evaluate(statement.value, environment)
        raise _ReturnSignal(value)

    if isinstance(statement, _Break):
        raise _BreakSignal()

    if isinstance(statement, _Continue):
        raise _ContinueSignal()

    raise LangError("unknown statement")


def equal(left: Any, right: Any) -> bool:
    if isinstance(left, (_Function, _Builtin)) or isinstance(right, (_Function, _Builtin)):
        return type(left) is type(right) and left is right
    if type(left) is not type(right):
        return False
    return left == right


def evaluate(node: Any, environment: _Environment) -> Any:
    if isinstance(node, _Literal):
        return node.value

    if isinstance(node, _Variable):
        return environment.get(node.name)

    if isinstance(node, _FunctionExpr):
        return _Function(node.parameters, node.body, environment)

    if isinstance(node, _Unary):
        value = evaluate(node.right, environment)
        if node.operator == "NOT":
            return not truthy(value)
        if type(value) is not int:
            raise LangError("unary '-' expects an integer")
        return -value

    if isinstance(node, _Logical):
        left = evaluate(node.left, environment)
        if node.operator == "or":
            return left if truthy(left) else evaluate(node.right, environment)
        return evaluate(node.right, environment) if truthy(left) else left

    if isinstance(node, _Binary):
        left = evaluate(node.left, environment)
        right = evaluate(node.right, environment)
        return evaluate_binary(node.operator, left, right)

    if isinstance(node, _Call):
        callee = evaluate(node.callee, environment)
        arguments = [evaluate(argument, environment) for argument in node.arguments]
        return call_value(callee, arguments)

    raise LangError("unknown expression")


def evaluate_binary(operator: str, left: Any, right: Any) -> Any:
    if operator == "==":
        return equal(left, right)
    if operator == "!=":
        return not equal(left, right)

    if operator in {"<", "<=", ">", ">="}:
        if type(left) is int and type(right) is int:
            pass
        elif type(left) is str and type(right) is str:
            pass
        else:
            raise LangError("comparison expects two integers or two strings")
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        return left >= right

    if operator == "+":
        if type(left) is int and type(right) is int:
            return left + right
        if type(left) is str and type(right) is str:
            return left + right
        raise LangError("'+' expects two integers or two strings")

    if type(left) is not int or type(right) is not int:
        raise LangError(f"{operator!r} expects integer operands")

    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        if right == 0:
            raise LangError("division by zero")
        return left // right
    if operator == "%":
        if right == 0:
            raise LangError("division by zero")
        return left % right
    if operator == "**":
        if right < 0:
            raise LangError("negative exponents are not allowed")
        return left**right

    raise LangError(f"unknown operator {operator!r}")


def call_value(callee: Any, arguments: list[Any]) -> Any:
    if isinstance(callee, _Builtin):
        if len(arguments) != callee.arity:
            raise LangError(
                f"{callee.name}() expects {callee.arity} argument(s), got {len(arguments)}"
            )
        return callee.implementation(arguments)

    if not isinstance(callee, _Function):
        raise LangError("attempted to call a non-function value")

    if len(arguments) != len(callee.parameters):
        raise LangError(
            f"function expects {len(callee.parameters)} argument(s), got {len(arguments)}"
        )

    environment = _Environment(callee.closure)
    for name, value in zip(callee.parameters, arguments):
        environment.define(name, value)

    try:
        # The body is a block, and therefore has a scope inside the parameter
        # scope.  No explicit return produces nil.
        execute_block(callee.body, environment)
    except _ReturnSignal as signal:
        return signal.value
    except (_BreakSignal, _ContinueSignal):
        raise LangError("loop control escaped into a function")
    return None


def run(src: str) -> Any:
    """Parse and execute *src*, returning the final statement's value.

    All guest-language failures are reported as LangError.  OUTPUT is reset for
    every invocation, including invocations that fail while parsing.
    """

    OUTPUT.clear()
    old_recursion_limit = sys.getrecursionlimit()
    try:
        if not isinstance(src, str):
            raise LangError("source must be a string")

        # Leave ample room for ordinary recursive guest programs while still
        # converting excessive Python recursion into a guest-language error.
        if old_recursion_limit < 10_000:
            sys.setrecursionlimit(10_000)

        tokens = _Lexer(src).scan()
        statements = _Parser(tokens).parse()
        environment = new_global_environment()
        return execute_statements(statements, environment)
    except LangError:
        raise
    except RecursionError as error:
        raise LangError("maximum recursion depth exceeded") from error
    except _ReturnSignal as error:
        raise LangError("'return' outside a function") from error
    except (_BreakSignal, _ContinueSignal) as error:
        raise LangError("loop control used outside a loop") from error
    except Exception as error:
        # Do not leak implementation exceptions (ZeroDivisionError, ValueError,
        # etc.) through the public interface.
        raise LangError("language evaluation failed") from error
    finally:
        if sys.getrecursionlimit() != old_recursion_limit:
            sys.setrecursionlimit(old_recursion_limit)
