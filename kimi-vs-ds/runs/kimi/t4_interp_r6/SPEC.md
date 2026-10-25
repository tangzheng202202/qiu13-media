# Spec: tiny language interpreter `lang.py`
Expose `run(src: str) -> value` (value of the last expression statement, or None) and `class LangError(Exception)`. All errors (syntax, runtime, name, type, division by zero) must raise `LangError` (never other exception types).

## Lexical
- Integers (arbitrary size, e.g. `123`), strings in double quotes with escapes `\"`, `\\`, `\n`. `true`, `false`, `nil`.
- Identifiers `[A-Za-z_][A-Za-z0-9_]*`. Comments start with `#` to end of line.
## Statements (separated by `;` or newlines; blank lines allowed)
- `let x = expr` declares in current scope (redeclare in same scope is an error). `x = expr` assigns to the nearest existing binding (error if none).
- `if cond { ... } else { ... }` (else optional; `else if` chains allowed). `while cond { ... }`. `return expr` (only inside functions; bare `return` returns nil). `break` / `continue` inside loops only (otherwise LangError).
- Blocks `{}` introduce a new scope.
- An `if` or `while` used as the last statement yields None as program value.
## Expressions (lowest to highest precedence)
1. `or`, then `and` (short-circuit, return the deciding operand value)
2. `==` `!=` (non-chaining: `a == b == c` is a syntax error)
3. `<` `<=` `>` `>=` (ints, or strings lexicographically; mixed types -> error; non-chaining)
4. `+` `-` (`+` also concatenates two strings; int+string is an error)
5. `*` `/` `%` (`/` is floor division like Python `//`; `%` like Python; division by zero -> error)
6. unary `-`, `not`
7. `**` right-associative, binds tighter than unary minus on its left: `-2 ** 2 == -4`, `2 ** -1` is error (negative exponent), `2 ** 3 ** 2 == 512`
8. call `f(a, b)`, grouping `( )`
- `fn(a, b) { ... }` is a function literal (closures with lexical scope, recursion via let-bound name works). Calling with wrong arity -> error. Calling a non-function -> error.
- Truthiness: only `false` and `nil` are falsy. `not` returns bool.
- Builtins: `len(s)` for strings, `str(x)` (ints -> decimal, true/false/nil -> "true"/"false"/"nil", strings unchanged), `print(x)` appends `str(x)` to a list exposed as module global `OUTPUT` (cleared at the start of each `run`) and returns nil.
- Equality: values of different types are unequal (no error); functions compare by identity.
- Python values returned: int, str, True/False, None; functions return some opaque object.
- Recursion depth: deep recursion (e.g. 10000 nested calls of a non-tail function) must raise LangError rather than crash, OR succeed.
Write tests in `test_lang.py`.
