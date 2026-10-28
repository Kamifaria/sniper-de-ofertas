"""Comportamento só do app empacotado: atalho para o .exe e config inicial."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import paths, versao, winsys  # noqa: E402


class EmpacotadoTests(unittest.TestCase):
    def test_atalho_aponta_para_o_exe(self):
        exe = r"C:\Program Files\Sniper Oferta\SniperOferta.exe"
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", exe):
            s = winsys.script_atalho(Path(r"C:\Users\F\AppData\Roaming\SniperOferta"), Path(r"C:\x.lnk"))
        self.assertIn(f"$s.TargetPath = '{exe}'", s)
        self.assertNotIn("iniciar.bat", s)
        self.assertIn("$s.Arguments = '--sem-janela'", s)

    def test_cria_config_na_primeira_execucao(self):
        with tempfile.TemporaryDirectory() as d:
            destino = Path(d) / "novo" / "config.toml"
            paths.garantir_config(destino)
            self.assertTrue(destino.exists())
            self.assertIn("[mercadolivre]", destino.read_text(encoding="utf-8"))

    def test_nao_sobrescreve_config_existente(self):
        with tempfile.TemporaryDirectory() as d:
            destino = Path(d) / "config.toml"
            destino.write_text("# meu", encoding="utf-8")
            paths.garantir_config(destino)
            self.assertEqual(destino.read_text(encoding="utf-8"), "# meu")

    def test_versao(self):
        self.assertRegex(versao.VERSAO, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
