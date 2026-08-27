"""Aponta nomes usados mas nunca definidos/importados num arquivo Python.

Rede de seguranca do refactor: pega o caso de extrair um bloco e deixar para
tras uma referencia a algo que morava nele. Trata except-as, comprehensions,
walrus e globais implicitos do modulo.
"""
import ast
import builtins
import sys

MODULE_GLOBALS = {"__file__", "__name__", "__doc__", "__package__", "__spec__"}


def unresolved(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    defined, used = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.Name):
            (defined if isinstance(n.ctx, (ast.Store, ast.Del)) else used).add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                defined.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)          # except X as e
        elif isinstance(n, ast.Global):
            defined.update(n.names)
        elif isinstance(n, ast.alias):
            defined.add(n.asname or n.name.split(".")[0])
    return sorted(used - defined - set(dir(builtins)) - MODULE_GLOBALS)


if __name__ == "__main__":
    bad = 0
    for f in sys.argv[1:]:
        miss = unresolved(f)
        print(f"  {f:34} {miss if miss else 'ok'}")
        bad += len(miss)
    sys.exit(1 if bad else 0)
