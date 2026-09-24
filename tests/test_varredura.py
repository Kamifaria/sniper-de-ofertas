"""Modo varredura: rodízio pelo catálogo com cursor salvo no banco."""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeCollector, FakeSweepCollector, MotorDeTeste  # noqa: E402
from sniper import config  # noqa: E402
from sniper.models import Watch  # noqa: E402

W = Watch(name="Varre", store="t", kind="varrer", cycle_min=60)


class VarreduraTests(unittest.TestCase):
    def prepara(self, m, col):
        m.engine.collectors["t"] = col
        m.engine.watch_status[W.name] = {}

    def passo(self, m, n=1):
        for _ in range(n):
            asyncio.run(m.engine.sweep_step(W))

    def test_percorre_todas_e_volta_ao_inicio(self):
        with MotorDeTeste(watches=[W]) as m:
            col = FakeSweepCollector(["a", "b", "c"])
            self.prepara(m, col)
            self.passo(m, 4)
            self.assertEqual(col.seen, ["a", "b", "c", "a"])
            st = m.engine.watch_status[W.name]
            self.assertEqual((st["unidade"], st["total"], st["state"]), (1, 3, "ok"))

    def test_retoma_de_onde_parou(self):
        with MotorDeTeste(watches=[W]) as m:
            self.prepara(m, FakeSweepCollector(["a", "b", "c"]))
            self.passo(m, 2)
            m.reabrir()
            col = FakeSweepCollector(["a", "b", "c"])
            self.prepara(m, col)
            self.passo(m)
            self.assertEqual(col.seen, ["c"])

    def test_pula_unidade_com_erro(self):
        with MotorDeTeste(watches=[W]) as m:
            col = FakeSweepCollector(["a", "b", "c"])
            col.fail = {"b"}
            self.prepara(m, col)
            self.passo(m, 2)
            self.assertIn("b pulada", m.engine.watch_status[W.name]["error"])
            self.passo(m)
            self.assertEqual(col.seen, ["a", "c"])

    def test_sem_internet_nao_avanca(self):
        with MotorDeTeste(watches=[W]) as m:
            col = FakeSweepCollector(["a", "b"])
            self.prepara(m, col)
            col.down = True
            self.passo(m)
            self.assertEqual(m.engine.watch_status[W.name]["state"], "erro")
            col.down = False
            self.passo(m)
            self.assertEqual(col.seen, ["a"])

    def test_erro_de_conexao_sem_mensagem_mostra_o_tipo(self):
        import httpx
        with MotorDeTeste(watches=[W]) as m:
            col = FakeSweepCollector(["a"])
            self.prepara(m, col)

            async def cai(unit, watch):
                raise httpx.ReadTimeout("")  # a httpx costuma vir sem texto quando a internet cai
            col.sweep = cai
            self.passo(m)
            self.assertIn("ReadTimeout", m.engine.watch_status[W.name]["error"])

    def test_lista_recarregada_mantem_a_unidade_atual(self):
        with MotorDeTeste(watches=[W]) as m:
            self.prepara(m, FakeSweepCollector(["a", "b", "c"]))
            self.passo(m)                                   # leu "a"; próxima é "b"
            sw = m.engine.db.get_sweep(W.name)
            m.engine.db.save_sweep(W.name, sw["units"], 0.0, sw["cursor"], sw["cycle_started"])  # cache vencido
            col = FakeSweepCollector(["x", "b", "c"])
            self.prepara(m, col)
            self.passo(m)
            self.assertEqual(col.seen, ["b"])

    def test_loja_sem_suporte(self):
        with MotorDeTeste(watches=[W]) as m:
            self.prepara(m, FakeCollector())
            self.passo(m)
            self.assertEqual(m.engine.watch_status[W.name]["state"], "loja não suporta varredura")


class ConfigVarrerTests(unittest.TestCase):
    def test_bloco_varrer(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[[varrer]]\nnome = "ML geral"\nloja = "mercadolivre"\ncategorias = "todas"\n'
                         'ciclo_minutos = 90\npaginas = 2\n\n'
                         '[[varrer]]\nnome = "Eletro"\ncategorias = ["MLB1000", "MLB5726"]\n',
                         encoding="utf-8")
            ws = config.load(p).watches
        self.assertEqual([(w.name, w.kind, w.sweep_categories, w.cycle_min, w.max_pages) for w in ws], [
            ("ML geral", "varrer", None, 90, 2),
            ("Eletro", "varrer", ["MLB1000", "MLB5726"], 60, 1),
        ])

    def test_categoria_unica_como_texto(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text('[[varrer]]\nnome = "Unica"\ncategorias = "MLB1051"\n', encoding="utf-8")
            ws = config.load(p).watches
        self.assertEqual(ws[0].sweep_categories, ["MLB1051"])


if __name__ == "__main__":
    unittest.main()
