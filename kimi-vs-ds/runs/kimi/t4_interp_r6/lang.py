"""Interpreter for the tiny language described in SPEC.md."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Optional

__all__ = ["run", "LangError", "OUTPUT"]


class LangError(Exception):
    """A syntax or runtime error in the tiny language."""


# The same list object is retained so references to lang.OUTPUT remain useful.
OUTPUT: list[str] = []


# ---------------------------------------------------------------------------
# Lexer


@dataclass
class _Token:
    kind: str
    value: Any
    line: int
    column: int

    @property
    def where(self) -> str:
        return f"line {self.line}, column {self.column}"


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


def _decimal_to_int(digits: str) -> int:
    """Convert without depending on Python's decimal digit safety limit."""
    result = 0
    for start in range(0, len(digits), 9):
        chunk = digits[start : start + 9]
        result = result * (10 ** len(chunk)) + int(chunk)
    return result


def _int_to_decimal(value: int) -> str:
    """Format any language integer, including integers over 4300 digits."""
    if value == 0:
        return "0"
    negative = value < 0
    if negative:
        value = -value
    base = 1_000_000_000
    chunks: list[int] = []
    while value:
        value, chunk = divmod(value, base)
        chunks.append(chunk)
    text = str(chunks[-1]) + "".join(
        f"{chunk:09d}" for chunk in reversed(chunks[:-1])
    )
    return "-" + text if negative else text


class _Lexer:
    def __init__(self, source: str):
        # Treat all common line endings as one logical newline.
        self.source = source.replace("\r\n", "\n").replace("\r", "\n")
        self.length = len(self.source)
        self.index = 0
        self.line = 1
        self.column = 1
        self.tokens: list[_Token] = []

    def tokenize(self) -> list[_Token]:
        while self.index < self.length:
            ch = self.source[self.index]
            if ch in " \t\f":
                self._advance()
            elif ch == "\n":
                self._add("NEWLINE", "\n")
                self._advance()
            elif ch == "#":
                while self.index < self.length and self.source[self.index] != "\n":
                    self._advance()
            elif "0" <= ch <= "9":
                self._number()
            elif ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch == "_":
                self._identifier()
            elif ch == '"':
                self._string()
            else:
                self._operator()
        self.tokens.append(_Token("EOF", None, self.line, self.column))
        return self.tokens

    def _advance(self) -> str:
        ch = self.source[self.index]
        self.index += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _add(self, kind: str, value: Any, line: int = -1, column: int = -1) -> None:
        self.tokens.append(
            _Token(
                kind,
                value,
                self.line if line < 0 else line,
                self.column if column < 0 else column,
            )
        )

    def _error(self, message: str, line: int, column: int) -> None:
        raise LangError(f"{message} at line {line}, column {column}")

    def _number(self) -> None:
        line, column = self.line, self.column
        start = self.index
        while self.index < self.length and "0" <= self.source[self.index] <= "9":
            self._advance()
        digits = self.source[start : self.index]
        self._add("INT", _decimal_to_int(digits), line, column)

    def _identifier(self) -> None:
        line, column = self.line, self.column
        start = self.index
        while self.index < self.length:
            ch = self.source[self.index]
            if not (
                ("A" <= ch <= "Z")
                or ("a" <= ch <= "z")
                or ("0" <= ch <= "9")
                or ch == "_"
            ):
                break
            self._advance()
        text = self.source[start : self.index]
        self._add(_KEYWORDS.get(text, "IDENT"), text, line, column)

    def _string(self) -> None:
        line, column = self.line, self.column
        self._advance()  # opening quote
        chars: list[str] = []
        escapes = {'"': '"', "\\": "\\", "n": "\n"}
        while self.index < self.length:
            ch = self._advance()
            if ch == '"':
                self._add("STRING", "".join(chars), line, column)
                return
            if ch == "\n":
                self._error("unterminated string", line, column)
            if ch == "\\":
                if self.index >= self.length:
                    self._error("unterminated string", line, column)
                escape = self._advance()
                if escape not in escapes:
                    self._error(
                        f"unknown escape \\{escape}", self.line, self.column - 1
                    )
                chars.append(escapes[escape])
            else:
                chars.append(ch)
        self._error("unterminated string", line, column)

    def _operator(self) -> None:
        line, column = self.line, self.column
        remaining = self.source[self.index : self.index + 2]
        if remaining in ("==", "!=", "<=", ">=", "**"):
            self._advance()
            self._advance()
            self._add(remaining, remaining, line, column)
            return
        ch = self.source[self.index]
        if ch in ";+-*/%<>=(){},":
            self._advance()
            self._add(ch, ch, line, column)
            return
        self._error(f"unexpected character {ch!r}", line, column)


# ---------------------------------------------------------------------------
# AST


@dataclass
class _Literal:
    value: Any


@dataclass
class _Variable:
    name: str
    token: _Token


@dataclass
class _Unary:
    operator: str
    operand: Any
    token: _Token


@dataclass
class _Binary:
    operator: str
    left: Any
    right: Any
    token: _Token


@dataclass
class _Call:
    callee: Any
    arguments: list[Any]
    token: _Token


@dataclass
class _FunctionExpr:
    parameters: list[str]
    body: Any
    token: _Token


@dataclass
class _ExpressionStatement:
    expression: Any


@dataclass
class _Let:
    name: str
    initializer: Any
    token: _Token


@dataclass
class _Assign:
    name: str
    value: Any
    token: _Token


@dataclass
class _Block:
    statements: list[Any]


@dataclass
class _If:
    condition: Any
    then_branch: _Block
    else_branch: Any


@dataclass
class _While:
    condition: Any
    body: _Block


@dataclass
class _Return:
    value: Any
    token: _Token


@dataclass
class _Break:
    token: _Token


@dataclass
class _Continue:
    token: _Token


# ---------------------------------------------------------------------------
# Parser


class _Parser:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.position = 0
        self.function_depth = 0
        self.loop_depth = 0

    def parse(self) -> list[Any]:
        statements: list[Any] = []
        self._skip_separators()
        while not self._check("EOF"):
            if self._check("}"):
                raise self._at(self._peek(), "unexpected '}'")
            statements.append(self._statement())
            if self._is_separator():
                self._skip_separators()
            elif not self._check("EOF"):
                raise self._at(self._peek(), "expected a statement separator")
        return statements

    def _peek(self, distance: int = 0) -> _Token:
        index = self.position + distance
        if index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[index]

    def _previous(self) -> _Token:
        return self.tokens[self.position - 1]

    def _check(self, kind: str) -> bool:
        return self._peek().kind == kind

    def _advance(self) -> _Token:
        token = self._peek()
        if token.kind != "EOF":
            self.position += 1
        return token

    def _match(self, *kinds: str) -> bool:
        if self._peek().kind in kinds:
            self._advance()
            return True
        return False

    def _expect(self, kind: str, message: str) -> _Token:
        if self._check(kind):
            return self._advance()
        raise self._at(self._peek(), message)

    @staticmethod
    def _at(token: _Token, message: str) -> LangError:
        return LangError(f"{message} at {token.where}")

    def _is_separator(self) -> bool:
        return self._peek().kind in ("NEWLINE", ";")

    def _skip_separators(self) -> None:
        while self._is_separator():
            self._advance()

    def _skip_newlines(self) -> None:
        while self._check("NEWLINE"):
            self._advance()

    def _statement(self) -> Any:
        if self._match("LET"):
            return self._let(self._previous())
        if self._match("IF"):
            return self._if(self._previous())
        if self._match("WHILE"):
            return self._while(self._previous())
        if self._match("RETURN"):
            token = self._previous()
            if self.function_depth == 0:
                raise self._at(token, "return outside a function")
            value = None
            if self._peek().kind not in ("NEWLINE", ";", "}", "EOF"):
                value = self._expression()
            return _Return(value, token)
        if self._match("BREAK"):
            token = self._previous()
            if self.loop_depth == 0:
                raise self._at(token, "break outside a loop")
            return _Break(token)
        if self._match("CONTINUE"):
            token = self._previous()
            if self.loop_depth == 0:
                raise self._at(token, "continue outside a loop")
            return _Continue(token)
        if self._check("{"):
            return self._block()
        if self._check("IDENT") and self._peek(1).kind == "=":
            name = self._advance()
            self._advance()  # =
            self._skip_newlines()
            return _Assign(name.value, self._expression(), name)
        return _ExpressionStatement(self._expression())

    def _let(self, token: _Token) -> _Let:
        name = self._expect("IDENT", "expected an identifier after 'let'")
        self._expect("=", "expected '=' after the declared name")
        self._skip_newlines()
        return _Let(name.value, self._expression(), name)

    def _if(self, token: _Token) -> _If:
        condition = self._expression()
        self._skip_newlines()
        then_branch = self._block()

        # A newline before else does not end the if statement. Restore the
        # position when there is no else so it remains a statement separator.
        saved = self.position
        self._skip_newlines()
        else_branch = None
        if self._match("ELSE"):
            self._skip_newlines()
            if self._match("IF"):
                else_branch = self._if(self._previous())
            else:
                else_branch = self._block()
        else:
            self.position = saved
        return _If(condition, then_branch, else_branch)

    def _while(self, token: _Token) -> _While:
        condition = self._expression()
        self._skip_newlines()
        self.loop_depth += 1
        try:
            body = self._block()
        finally:
            self.loop_depth -= 1
        return _While(condition, body)

    def _block(self) -> _Block:
        self._expect("{", "expected '{' to start a block")
        statements: list[Any] = []
        self._skip_separators()
        while not self._check("}"):
            if self._check("EOF"):
                raise self._at(self._peek(), "unterminated block")
            statements.append(self._statement())
            if self._is_separator():
                self._skip_separators()
            elif not self._check("}"):
                if self._check("EOF"):
                    raise self._at(self._peek(), "unterminated block")
                raise self._at(self._peek(), "expected a statement separator")
        self._expect("}", "expected '}' after block")
        return _Block(statements)

    def _expression(self) -> Any:
        return self._or()

    def _or(self) -> Any:
        expression = self._and()
        while self._match("OR"):
            token = self._previous()
            self._skip_newlines()
            expression = _Binary("or", expression, self._and(), token)
        return expression

    def _and(self) -> Any:
        expression = self._equality()
        while self._match("AND"):
            token = self._previous()
            self._skip_newlines()
            expression = _Binary("and", expression, self._equality(), token)
        return expression

    def _equality(self) -> Any:
        expression = self._comparison()
        if self._match("==", "!="):
            token = self._previous()
            self._skip_newlines()
            expression = _Binary(
                token.value, expression, self._comparison(), token
            )
            if self._peek().kind in ("==", "!="):
                raise self._at(self._peek(), "equality operators do not chain")
        return expression

    def _comparison(self) -> Any:
        expression = self._addition()
        if self._match("<", "<=", ">", ">="):
            token = self._previous()
            self._skip_newlines()
            expression = _Binary(token.value, expression, self._addition(), token)
            if self._peek().kind in ("<", "<=", ">", ">="):
                raise self._at(self._peek(), "comparison operators do not chain")
        return expression

    def _addition(self) -> Any:
        expression = self._multiplication()
        while self._match("+", "-"):
            token = self._previous()
            self._skip_newlines()
            expression = _Binary(
                token.value, expression, self._multiplication(), token
            )
        return expression

    def _multiplication(self) -> Any:
        expression = self._unary()
        while self._match("*", "/", "%"):
            token = self._previous()
            self._skip_newlines()
            expression = _Binary(token.value, expression, self._unary(), token)
        return expression

    def _unary(self) -> Any:
        if self._match("-", "NOT"):
            token = self._previous()
            self._skip_newlines()
            operator = "not" if token.kind == "NOT" else "-"
            return _Unary(operator, self._unary(), token)
        return self._power()

    def _power(self) -> Any:
        expression = self._call()
        if self._match("**"):
            token = self._previous()
            self._skip_newlines()
            # Parsing the exponent as unary both permits 2 ** -1 (which is a
            # runtime error) and makes ** right associative.
            return _Binary("**", expression, self._unary(), token)
        return expression

    def _call(self) -> Any:
        expression = self._primary()
        while self._match("("):
            token = self._previous()
            arguments: list[Any] = []
            self._skip_newlines()
            if not self._check(")"):
                while True:
                    if self._check(")"):
                        raise self._at(self._peek(), "expected an argument")
                    arguments.append(self._expression())
                    self._skip_newlines()
                    if not self._match(","):
                        break
                    self._skip_newlines()
            self._expect(")", "expected ')' after arguments")
            expression = _Call(expression, arguments, token)
        return expression

    def _primary(self) -> Any:
        if self._match("INT", "STRING"):
            return _Literal(self._previous().value)
        if self._match("TRUE"):
            return _Literal(True)
        if self._match("FALSE"):
            return _Literal(False)
        if self._match("NIL"):
            return _Literal(None)
        if self._match("IDENT"):
            token = self._previous()
            return _Variable(token.value, token)
        if self._match("FN"):
            return self._function(self._previous())
        if self._match("("):
            self._skip_newlines()
            expression = self._expression()
            self._skip_newlines()
            self._expect(")", "expected ')' after expression")
            return expression
        raise self._at(self._peek(), "expected an expression")

    def _function(self, token: _Token) -> _FunctionExpr:
        self._expect("(", "expected '(' after 'fn'")
        self._skip_newlines()
        parameters: list[str] = []
        parameter_tokens: dict[str, _Token] = {}
        if not self._check(")"):
            while True:
                name = self._expect("IDENT", "expected a parameter name")
                if name.value in parameter_tokens:
                    raise self._at(name, "duplicate function parameter")
                parameters.append(name.value)
                parameter_tokens[name.value] = name
                self._skip_newlines()
                if not self._match(","):
                    break
                self._skip_newlines()
        self._expect(")", "expected ')' after parameters")
        self._skip_newlines()

        old_loop_depth = self.loop_depth
        self.function_depth += 1
        self.loop_depth = 0
        try:
            body = self._block()
        finally:
            self.function_depth -= 1
            self.loop_depth = old_loop_depth
        return _FunctionExpr(parameters, body, token)


# ---------------------------------------------------------------------------
# Runtime


class _Environment:
    def __init__(self, parent: Optional[_Environment] = None):
        self.parent = parent
        self.values: dict[str, Any] = {}

    def has_local(self, name: str) -> bool:
        return name in self.values

    def declare(self, name: str, value: Any) -> None:
        self.values[name] = value

    def get(self, name: str, token: _Token) -> Any:
        environment: Optional[_Environment] = self
        while environment is not None:
            if name in environment.values:
                return environment.values[name]
            environment = environment.parent
        raise LangError(f"undefined name {name!r} at {token.where}")

    def assign(self, name: str, value: Any, token: _Token) -> None:
        environment: Optional[_Environment] = self
        while environment is not None:
            if name in environment.values:
                environment.values[name] = value
                return
            environment = environment.parent
        raise LangError(f"assignment to undefined name {name!r} at {token.where}")


class _UserFunction:
    def __init__(
        self, parameters: list[str], body: _Block, closure: _Environment
    ):
        self.parameters = tuple(parameters)
        self.body = body
        self.closure = closure


class _Builtin:
    def __init__(self, name: str, implementation: Any):
        self.name = name
        self.implementation = implementation


class _ReturnSignal(Exception):
    def __init__(self, value: Any):
        self.value = value


class _BreakSignal(Exception):
    pass


class _ContinueSignal(Exception):
    pass


def _truthy(value: Any) -> bool:
    return value is not None and value is not False


def _is_int(value: Any) -> bool:
    # bool is a distinct language type even though it subclasses int in Python.
    return type(value) is int


def _stringify(value: Any) -> str:
    if type(value) is str:
        return value
    if _is_int(value):
        return _int_to_decimal(value)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "nil"
    raise LangError("str() does not support function values")


def _builtin_len(value: Any) -> int:
    if type(value) is not str:
        raise LangError("len() expects a string")
    return len(value)


def _builtin_print(value: Any) -> None:
    OUTPUT.append(_stringify(value))
    return None


class _Interpreter:
    # This limit produces a controlled LangError well before a 10000-call
    # non-tail recursion can exhaust the Python stack.
    MAX_CALL_DEPTH = 400

    def __init__(self):
        self.call_depth = 0
        builtin_environment = _Environment()
        builtin_environment.declare("len", _Builtin("len", _builtin_len))
        builtin_environment.declare("str", _Builtin("str", _stringify))
        builtin_environment.declare("print", _Builtin("print", _builtin_print))
        # Source declarations have their own global scope and may shadow the
        # predefined names, just as inner lexical scopes may shadow globals.
        self.globals = _Environment(builtin_environment)

    def run(self, statements: list[Any]) -> Any:
        value = None
        for statement in statements:
            value = self._execute(statement, self.globals)
        return value

    def _execute(self, statement: Any, environment: _Environment) -> Any:
        if isinstance(statement, _ExpressionStatement):
            return self._evaluate(statement.expression, environment)
        if isinstance(statement, _Let):
            if environment.has_local(statement.name):
                raise LangError(
                    f"redeclaration of {statement.name!r} at {statement.token.where}"
                )
            value = self._evaluate(statement.initializer, environment)
            environment.declare(statement.name, value)
            return None
        if isinstance(statement, _Assign):
            value = self._evaluate(statement.value, environment)
            environment.assign(statement.name, value, statement.token)
            return None
        if isinstance(statement, _Block):
            self._execute_block(statement, environment)
            return None
        if isinstance(statement, _If):
            if _truthy(self._evaluate(statement.condition, environment)):
                self._execute_block(statement.then_branch, environment)
            elif statement.else_branch is not None:
                if isinstance(statement.else_branch, _Block):
                    self._execute_block(statement.else_branch, environment)
                else:
                    self._execute(statement.else_branch, environment)
            return None
        if isinstance(statement, _While):
            while _truthy(self._evaluate(statement.condition, environment)):
                try:
                    self._execute_block(statement.body, environment)
                except _BreakSignal:
                    break
                except _ContinueSignal:
                    continue
            return None
        if isinstance(statement, _Return):
            value = (
                None
                if statement.value is None
                else self._evaluate(statement.value, environment)
            )
            raise _ReturnSignal(value)
        if isinstance(statement, _Break):
            raise _BreakSignal()
        if isinstance(statement, _Continue):
            raise _ContinueSignal()
        raise LangError("invalid statement")

    def _execute_block(self, block: _Block, parent: _Environment) -> None:
        environment = _Environment(parent)
        for statement in block.statements:
            self._execute(statement, environment)

    def _evaluate(self, expression: Any, environment: _Environment) -> Any:
        if isinstance(expression, _Literal):
            return expression.value
        if isinstance(expression, _Variable):
            return environment.get(expression.name, expression.token)
        if isinstance(expression, _FunctionExpr):
            return _UserFunction(expression.parameters, expression.body, environment)
        if isinstance(expression, _Unary):
            value = self._evaluate(expression.operand, environment)
            if expression.operator == "not":
                return not _truthy(value)
            if not _is_int(value):
                raise LangError(f"unary '-' expects an integer at {expression.token.where}")
            return -value
        if isinstance(expression, _Binary):
            return self._binary(expression, environment)
        if isinstance(expression, _Call):
            callee = self._evaluate(expression.callee, environment)
            arguments = [
                self._evaluate(argument, environment)
                for argument in expression.arguments
            ]
            return self._call(callee, arguments, expression.token)
        raise LangError("invalid expression")

    def _binary(self, expression: _Binary, environment: _Environment) -> Any:
        operator = expression.operator
        if operator == "or":
            left = self._evaluate(expression.left, environment)
            return left if _truthy(left) else self._evaluate(expression.right, environment)
        if operator == "and":
            left = self._evaluate(expression.left, environment)
            return self._evaluate(expression.right, environment) if _truthy(left) else left

        left = self._evaluate(expression.left, environment)
        right = self._evaluate(expression.right, environment)

        if operator in ("==", "!="):
            equal = self._equal(left, right)
            return equal if operator == "==" else not equal
        if operator in ("<", "<=", ">", ">="):
            if not (
                (_is_int(left) and _is_int(right))
                or (type(left) is str and type(right) is str)
            ):
                raise LangError(
                    f"comparison requires two integers or two strings at {expression.token.where}"
                )
            if operator == "<":
                return left < right
            if operator == "<=":
                return left <= right
            if operator == ">":
                return left > right
            return left >= right
        if operator == "+":
            if _is_int(left) and _is_int(right):
                return left + right
            if type(left) is str and type(right) is str:
                return left + right
            raise LangError(f"'+' requires two integers or two strings at {expression.token.where}")
        if operator in ("-", "*", "/", "%", "**"):
            if not (_is_int(left) and _is_int(right)):
                raise LangError(
                    f"'{operator}' requires integer operands at {expression.token.where}"
                )
            if operator == "-":
                return left - right
            if operator == "*":
                return left * right
            if operator == "/":
                if right == 0:
                    raise LangError(f"division by zero at {expression.token.where}")
                return left // right
            if operator == "%":
                if right == 0:
                    raise LangError(f"division by zero at {expression.token.where}")
                return left % right
            if right < 0:
                raise LangError(f"negative exponent at {expression.token.where}")
            return left**right
        raise LangError(f"unknown operator {operator!r}")

    @staticmethod
    def _equal(left: Any, right: Any) -> bool:
        if type(left) is not type(right):
            return False
        if isinstance(left, (_UserFunction, _Builtin)):
            return left is right
        return bool(left == right)

    def _call(self, callee: Any, arguments: list[Any], token: _Token) -> Any:
        if isinstance(callee, _Builtin):
            if len(arguments) != 1:
                raise LangError(
                    f"{callee.name}() expects 1 argument, got {len(arguments)} at {token.where}"
                )
            return callee.implementation(arguments[0])
        if not isinstance(callee, _UserFunction):
            raise LangError(f"attempt to call a non-function at {token.where}")
        if len(arguments) != len(callee.parameters):
            raise LangError(
                f"function expects {len(callee.parameters)} arguments, "
                f"got {len(arguments)} at {token.where}"
            )
        if self.call_depth >= self.MAX_CALL_DEPTH:
            raise LangError(f"maximum recursion depth exceeded at {token.where}")

        self.call_depth += 1
        try:
            call_environment = _Environment(callee.closure)
            for name, value in zip(callee.parameters, arguments):
                call_environment.declare(name, value)
            try:
                # The function body is a block, nested inside the parameter
                # scope, consistently with every other braced block.
                self._execute_block(callee.body, call_environment)
            except _ReturnSignal as signal:
                return signal.value
            return None
        finally:
            self.call_depth -= 1


# ---------------------------------------------------------------------------
# Public API


def run(src: str) -> Any:
    """Execute source and return the last expression statement's value.

    All language syntax and runtime failures are reported as LangError.
    """

    OUTPUT.clear()
    if not isinstance(src, str):
        raise LangError("source must be a string")

    old_recursion_limit = sys.getrecursionlimit()
    raised_limit = old_recursion_limit < 10000
    if raised_limit:
        sys.setrecursionlimit(10000)
    try:
        tokens = _Lexer(src).tokenize()
        statements = _Parser(tokens).parse()
        return _Interpreter().run(statements)
    except LangError:
        raise
    except RecursionError:
        raise LangError("maximum parser or evaluator recursion depth exceeded") from None
    except Exception as error:
        # Do not leak implementation exceptions (ZeroDivisionError, TypeError,
        # IndexError, etc.) through the language API.
        message = str(error) or error.__class__.__name__
        raise LangError(message) from None
    finally:
        if raised_limit:
            sys.setrecursionlimit(old_recursion_limit)
