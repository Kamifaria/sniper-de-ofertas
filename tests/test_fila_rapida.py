"""Fila rápida: relê itens caros com frequência."""
import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, FakeRefreshCollector, MotorDeTeste, oferta  # noqa: E402
from sniper import config  # noqa: E402
from sniper.engine import FILA_RAPIDA  # noqa: E402


class SelecaoTests(unittest.TestCase):
    def test_itens_caros_recentes_do_mais_caro(self):
        with MotorDeTeste() as m:
            db = m.engine.db
            agora = time.time()
            db.save_offer(oferta("A", 5000, catalog=""))
            db.save_offer(oferta("B", 200, catalog=""))
            db.save_offer(oferta("C", 800, catalog="", collected_at=agora - 50 * 3600))  # visto há 50 h
            db.save_offer(oferta("D", 1000, catalog=""))
            db.save_offer(oferta("E", 9000, catalog="", store="outra"))
            self.assertEqual(db.fast_lane_items("t", 300, 10), ["A", "D"])
            self.assertEqual(db.fast_lane_items("t", 300, 1), ["A"])


class MotorFilaTests(unittest.TestCase):
    def test_bug_na_fila_rapida_vira_alerta(self):
        with MotorDeTeste() as m:
            eng = m.engine
            for _ in range(3):
                eng.db.save_offer(oferta("A", 5000, catalog=""))
            eng.db.save_offer(oferta("B", 3000, catalog=""))
            col = FakeRefreshCollector({"A": 490, "B": 3000})
            eng.collectors["t"] = col
            self.assertEqual(asyncio.run(eng.fast_lane_step()), 1)
            self.assertEqual(col.pedidos, [["A", "B"]])
            a = eng.db.list_alerts()[0]
            self.assertEqual((a["item_id"], a["watch"]), ("A", FILA_RAPIDA))
            st = eng.watch_status[FILA_RAPIDA]
            self.assertEqual((st["count"], st["state"], st["kind"]), (2, "ok", "rapida"))

    def test_loja_sem_refresh_e_ignorada(self):
        with MotorDeTeste() as m:
            m.engine.db.save_offer(oferta("A", 5000, catalog=""))
            m.engine.collectors["t"] = FakeCollector()
            self.assertEqual(asyncio.run(m.engine.fast_lane_step()), 0)
            self.assertEqual(m.engine.watch_status[FILA_RAPIDA]["count"], 0)


class ConfigVarreduraTests(unittest.TestCase):
    def test_bloco_varredura(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[varredura]\nvalor_alto = 500\nintervalo_rapido = 60\nmax_itens_rapida = 200\n",
                         encoding="utf-8")
            s = config.load(p)
        self.assertEqual((s.valor_alto, s.intervalo_rapido, s.max_itens_rapida), (500.0, 60, 200))

    def test_padroes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("", encoding="utf-8")
            s = config.load(p)
        self.assertEqual((s.valor_alto, s.intervalo_rapido, s.max_itens_rapida), (300.0, 120, 1000))


if __name__ == "__main__":
    unittest.main()
