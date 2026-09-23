"""Atalho de inicialização do Windows (só a parte que dá para testar sem mexer no sistema)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import winsys  # noqa: E402


class AtalhoTests(unittest.TestCase):
    def test_script_aponta_para_iniciar_bat_sem_janela(self):
        base = Path(r"C:\Users\Fulana\Projeto\sniper")
        s = winsys.script_atalho(base, Path(r"C:\Startup\Sniper de Ofertas.lnk"))
        self.assertIn(r"'C:\Users\Fulana\Projeto\sniper\iniciar.bat'", s)
        self.assertIn("$s.Arguments = '--sem-janela'", s)
        self.assertIn(r"$s.WorkingDirectory = 'C:\Users\Fulana\Projeto\sniper'", s)
        self.assertIn("$s.WindowStyle = 7", s)

    def test_aspas_simples_escapadas(self):
        s = winsys.script_atalho(Path(r"C:\D'Avila"), Path(r"C:\x.lnk"))
        self.assertIn(r"'C:\D''Avila\iniciar.bat'", s)

    def test_nome_do_atalho(self):
        self.assertEqual(winsys.NOME_ATALHO, "Sniper de Ofertas.lnk")


if __name__ == "__main__":
    unittest.main()
