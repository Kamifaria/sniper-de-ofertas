"""Testes da remoção do modo demonstração."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import collectors, config  # noqa: E402
from sniper.db import Database  # noqa: E402
from sniper.detector import evaluate  # noqa: E402
from sniper.models import Offer  # noqa: E402


class LimpezaDemoTests(unittest.TestCase):
    def test_banco_apaga_so_linhas_demo(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.db"
            db = Database(p)
            for store in ("demo", "mercadolivre"):
                o = Offer(store=store, item_id="I1", title="Produto", price=10.0, url="https://x",
                          seller_id="S1", seller_name="LOJA")
                db.save_offer(o)
                db.save_alert(o, evaluate(o, []))
                db.save_discard(o, 50, "motivo")
                db.block_seller(store, "S1", "LOJA", "teste")
            db.conn.close()

            db = Database(p)
            for table in ("prices", "items", "alerts", "discards", "sellers"):
                stores = {r[0] for r in db.conn.execute(f"SELECT store FROM {table}")}
                self.assertEqual(stores, {"mercadolivre"}, table)
            db.conn.close()

    def test_coletor_demo_nao_existe(self):
        self.assertFalse(hasattr(collectors, "DemoCollector"))

    def test_config_ignora_bloco_demo(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[demo]\nativo = true\nintervalo = 5\n", encoding="utf-8")
            s = config.load(p)
            self.assertEqual([w for w in s.watches if w.store == "demo"], [])
            self.assertFalse(hasattr(s, "demo_on"))


if __name__ == "__main__":
    unittest.main()
