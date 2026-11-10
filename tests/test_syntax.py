"""Проверка синтаксиса до импорта обработчиков на новых версиях Python."""
import ast
from pathlib import Path
import unittest


class SyntaxCompatibilityTests(unittest.TestCase):
    def test_python_311_syntax(self):
        root = Path(__file__).resolve().parents[1]
        paths = [root / 'main.py']
        for directory in ('bot', 'database', 'tests'):
            paths.extend((root / directory).rglob('*.py'))
        for path in paths:
            with self.subTest(path=path.relative_to(root)):
                ast.parse(path.read_text(encoding='utf-8'), filename=str(path),
                          feature_version=(3, 11))
