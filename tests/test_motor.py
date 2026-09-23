"""Pipeline compartilhado e supervisor de loops."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, MotorDeTeste, oferta  # noqa: E402
from sniper.models import Watch  # noqa: E402


class SupervisorTests(unittest.TestCase):
    def test_reinicia_loop_que_caiu(self):
        with MotorDeTeste() as m:
            eng = m.engine
            eng.restart_delay = 0
            calls = []

            async def loop():
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("boom")

            asyncio.run(eng._supervise("regra X", loop))
            self.assertEqual(len(calls), 2)
            self.assertTrue(any("boom" in e.get("msg", "") for e in eng.events))


class ProcessTests(unittest.TestCase):
    def test_process_gera_alerta_com_nome_da_regra(self):
        w = Watch(name="Varredura X", store="t")
        with MotorDeTeste() as m:
            col = FakeCollector()
            m.engine.collectors["t"] = col
            offers = [oferta("A", 4900), oferta("B", 5000), oferta("C", 4950), oferta("D", 490)]
            r = asyncio.run(m.engine._process(w, col, offers))
            self.assertEqual(r["alertas"], 1)
            self.assertEqual(m.engine.db.list_alerts()[0]["watch"], "Varredura X")

    def test_process_conta_rejeitados(self):
        w = Watch(name="w", store="t")
        with MotorDeTeste() as m:
            col = FakeCollector()
            r = asyncio.run(m.engine._process(w, col, [oferta("T", 1.0, title="TESTE iPhone 15")]))
            self.assertEqual((r["alertas"], r["rejeitados"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
