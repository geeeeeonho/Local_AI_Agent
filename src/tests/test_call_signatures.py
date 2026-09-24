"""Calls into this repository's own modules have to fit what they call.

``launcher.actions.chat`` called ``searxng_runtime.start()`` while the function
had required ``env``. Python only notices at runtime, the call sat inside a
``try/except Exception`` that turned the TypeError into a warning, and so every
terminal Chat session ran with search silently switched off. Nothing failed
loudly and no test covered it.

Imports are already checked by ``test_no_phantom_imports``; this does the same
for arguments. It only inspects calls it can resolve with certainty — a plain
module attribute or a directly imported function, no aliases bound to two
different modules, no ``*args``/``**kwargs`` at the call site — so a finding
here is a real mismatch rather than something the checker could not follow.
"""
import ast
import importlib
import inspect
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
PACKAGES = ('apps', 'core', 'installer', 'integrations', 'launcher', 'services', 'tools')

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def module_of(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def resolve_relative(package: str, module: str, level: int) -> str:
    if not level:
        return module
    base = package.split('.') if package else []
    if level > 1:
        base = base[:len(base) - (level - 1)]
    return '.'.join([part for part in base if part] + ([module] if module else []))


def aliases_in(tree: ast.AST, package: str) -> dict:
    """local name -> dotted target, dropping any name bound more than once.

    ``network_policy.prepare_runtime`` binds the name ``runtime`` to both
    ``warp_runtime`` and ``tor_runtime`` on different branches; a checker that
    keeps one of them reports a mismatch that does not exist.
    """
    bound = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                name = item.asname or item.name.split('.')[0]
                target = item.name if item.asname else item.name.split('.')[0]
                bound.setdefault(name, set()).add(target)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(package, node.module or '', node.level or 0)
            for item in node.names:
                if item.name == '*':
                    continue
                bound.setdefault(item.asname or item.name, set()).add(
                    base + '.' + item.name if base else item.name)
    return {name: next(iter(targets)) for name, targets in bound.items() if len(targets) == 1}


def target_of(node: ast.Call, aliases: dict):
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        dotted = aliases.get(node.func.value.id)
        return (dotted, node.func.attr) if dotted else None
    if isinstance(node.func, ast.Name):
        dotted = aliases.get(node.func.id)
        if dotted and '.' in dotted:
            module, _, attribute = dotted.rpartition('.')
            return module, attribute
    return None


class CallSignatureTests(unittest.TestCase):
    def test_every_resolvable_call_fits_the_function_it_calls(self):
        problems = []
        for path in sorted(SRC.rglob('*.py')):
            relative = path.relative_to(SRC)
            if relative.parts[0] == 'tests':
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:                      # pragma: no cover
                continue
            me = module_of(path)
            package = me.rpartition('.')[0]
            aliases = aliases_in(tree, package)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = target_of(node, aliases)
                if target is None:
                    continue
                module, attribute = target
                if module.split('.')[0] not in PACKAGES:
                    continue
                try:
                    imported = importlib.import_module(module)
                except Exception:                    # optional/GUI-only imports
                    continue
                function = getattr(imported, attribute, None)
                if not inspect.isfunction(function):
                    continue
                if any(isinstance(argument, ast.Starred) for argument in node.args):
                    continue
                if any(keyword.arg is None for keyword in node.keywords):
                    continue
                try:
                    signature = inspect.signature(function)
                except (TypeError, ValueError):       # pragma: no cover
                    continue
                try:
                    signature.bind(*[None] * len(node.args),
                                   **{keyword.arg: None for keyword in node.keywords})
                except TypeError as exc:
                    problems.append('%s:%d  %s.%s -> %s'
                                    % (relative, node.lineno, module.rpartition('.')[2],
                                       attribute, exc))
        self.assertEqual(problems, [], '호출과 정의가 맞지 않는 곳:\n  '
                         + '\n  '.join(problems))


class CheckerTests(unittest.TestCase):
    """The checker has to be able to fail, and must not cry wolf."""

    def analyse(self, source, tmp_name='probe.py'):
        tree = ast.parse(source)
        return aliases_in(tree, 'launcher')

    def test_a_missing_required_argument_is_the_kind_of_thing_it_catches(self):
        from launcher import searxng_runtime
        required = [name for name, value in
                    inspect.signature(searxng_runtime.start).parameters.items()
                    if value.default is inspect.Parameter.empty]
        self.assertTrue(required, 'start() has a required parameter to miss')
        with self.assertRaises(TypeError):
            inspect.signature(searxng_runtime.start).bind()

    def test_a_name_bound_to_two_modules_is_not_guessed(self):
        aliases = self.analyse(
            'from . import warp_runtime as runtime\n'
            'from . import tor_runtime as runtime\n')
        self.assertNotIn('runtime', aliases)

    def test_a_name_bound_once_is_resolved(self):
        aliases = self.analyse('from . import searxng_runtime\n')
        self.assertEqual(aliases.get('searxng_runtime'), 'launcher.searxng_runtime')
