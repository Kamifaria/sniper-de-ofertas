"""run.py: detecta se já existe uma instância rodando na porta antes de subir outra."""
import importlib.util
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = Path(__file__).resolve().parents[1]


def _carregar_run():
    spec = importlib.util.spec_from_file_location("run_module", BASE / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_module = _carregar_run()


class JaRodandoTests(unittest.TestCase):
    def test_true_com_porta_escutando(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(run_module._ja_rodando(port))
        finally:
            srv.close()

    def test_false_depois_de_fechar(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        srv.close()
        self.assertFalse(run_module._ja_rodando(port))


if __name__ == "__main__":
    unittest.main()
