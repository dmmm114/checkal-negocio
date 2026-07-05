"""Põe a raiz do pacote (checkal/) no sys.path para `import app.*` funcionar
independentemente do diretório de onde o pytest é invocado."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
