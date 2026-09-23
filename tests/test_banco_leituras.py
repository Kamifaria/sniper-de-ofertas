"""Histórico de preços compacto: uma linha por mudança de preço, com contador de leituras."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.db import Database  # noqa: E402
from sniper.models import Offer  # noqa: E402


class LeiturasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")
        self.t = time.time() - 3600

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def o(self, price, dt=0.0, orig=None):
        return Offer(store="t", item_id="X", title="P", price=price, url="https://x",
                     original_price=orig, collected_at=self.t + dt)

    def rows(self):
        return [tuple(r) for r in self.db.conn.execute("SELECT price, reads FROM prices ORDER BY id")]

    def test_preco_igual_nao_cria_linha(self):
        for i in range(3):
            self.db.save_offer(self.o(100.0, i))
        self.assertEqual(self.rows(), [(100.0, 3)])
        self.assertEqual(self.db.history("t", "X"), [100.0, 100.0, 100.0])

    def test_preco_mudou_cria_linha(self):
        self.db.save_offer(self.o(100.0, 0))
        self.db.save_offer(self.o(100.0, 1))
        self.db.save_offer(self.o(90.0, 2))
        self.assertEqual(self.rows(), [(100.0, 2), (90.0, 1)])
        self.assertEqual(self.db.history("t", "X"), [100.0, 100.0, 90.0])

    def test_de_por_mudou_cria_linha(self):
        self.db.save_offer(self.o(100.0, 0))
        self.db.save_offer(self.o(100.0, 1, orig=200.0))
        self.assertEqual(len(self.rows()), 2)

    def test_depois_de_6h_cria_linha(self):
        self.t = time.time() - 8 * 3600
        self.db.save_offer(self.o(100.0, 0))
        self.db.save_offer(self.o(100.0, 7 * 3600))
        self.assertEqual(self.rows(), [(100.0, 1), (100.0, 1)])

    def test_limite_conta_leituras(self):
        for i in range(5):
            self.db.save_offer(self.o(100.0, i))
        self.assertEqual(self.db.history("t", "X", limit=3), [100.0, 100.0, 100.0])

    def test_stats_soma_leituras(self):
        for i in range(3):
            self.db.save_offer(self.o(100.0, i))
        self.assertEqual(self.db.stats()["leituras_24h"], 3)


if __name__ == "__main__":
    unittest.main()
