"""Rota /api/lojas e painel sem lista fixa de lojas."""
import sys
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.config import LojaConfig, Settings  # noqa: E402
from sniper.server import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ApiLojasTests(unittest.TestCase):
    def test_lista_lojas_com_etiqueta_e_estado(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            s = Settings(base_dir=base, db_path=base / "t.db", windows_on=False,
                         lojas={"mercadolivre": LojaConfig(ativo=True)})
            app = create_app(s)
            eng = app.state.engine
            eng.store_errors["mercadolivre"] = {"desde": 0, "avisado": False, "msg": "sem internet"}
            try:
                lojas = TestClient(app).get("/api/lojas").json()   # sem "with": o motor não liga
            finally:
                eng.db.conn.close()
        ml = next(x for x in lojas if x["chave"] == "mercadolivre")
        self.assertEqual((ml["nome"], ml["oficial"], ml["ativa"], ml["configurada"]),
                         ("ML", True, True, False))
        self.assertIn("Conectar ML", ml["motivo"])
        self.assertEqual(ml["limite"]["limite"], 60)
        self.assertEqual(ml["erro"], "sem internet")

    def test_painel_usa_nomes_da_api(self):
        html = (ROOT / "sniper" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("const STORE", html)
        self.assertIn("/api/lojas", html)


if __name__ == "__main__":
    unittest.main()
