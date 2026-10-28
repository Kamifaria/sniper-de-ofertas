"""Retenção de dados do ML (termos 2.2.1.3 e 5.2) e nomes sem as palavras proibidas (2.2.4)."""
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper import config  # noqa: E402
from sniper.db import Database  # noqa: E402
from sniper.detector import evaluate  # noqa: E402
from sniper.models import Offer  # noqa: E402
from sniper.stores import LOJAS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROIBIDAS = re.compile(r"mercado|livre|pagamento|envios|cr[eé]dito", re.I)


class RetencaoTests(unittest.TestCase):
    def test_prune_apaga_alertas_e_itens_velhos_e_mantem_recentes(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "t.db")
            for iid in ("VELHO", "NOVO"):
                o = Offer(store="mercadolivre", item_id=iid, title=iid, price=10.0, url="https://x")
                db.save_offer(o)
                db.save_alert(o, evaluate(o, []))
            velho = time.time() - 40 * 86400
            for t in ("items", "alerts"):
                col = "last_seen" if t == "items" else "ts"
                db.conn.execute(f"UPDATE {t} SET {col}=? WHERE item_id='VELHO'", (velho,))
            db.conn.commit()
            db.prune(30)
            self.assertEqual([r[0] for r in db.conn.execute("SELECT item_id FROM items")], ["NOVO"])
            self.assertEqual([r[0] for r in db.conn.execute("SELECT item_id FROM alerts")], ["NOVO"])
            db.conn.close()

    def test_config_retencao_padrao_30_dias_e_configuravel(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("[geral]\n", encoding="utf-8")
            self.assertEqual(config.load(p).retention_days, 30)
            p.write_text("[geral]\nretencao_dias = 7\n", encoding="utf-8")
            self.assertEqual(config.load(p).retention_days, 7)

    def test_nome_da_loja_sem_palavras_proibidas(self):
        self.assertIsNone(PROIBIDAS.search(LOJAS["mercadolivre"].nome))
        self.assertIsNone(PROIBIDAS.search(LOJAS["mercadolivre"].motivo_sem_config))

    def test_painel_sem_palavras_proibidas_no_texto_visivel(self):
        html = (ROOT / "sniper" / "web" / "index.html").read_text(encoding="utf-8")
        html = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", html)
        texto = re.sub(r"<[^>]+>", " ", html)
        texto = re.sub(r"\S*\.com\.br\S*", "", texto)   # endereços do DevCenter precisam aparecer
        self.assertEqual(PROIBIDAS.findall(texto), [])


if __name__ == "__main__":
    unittest.main()
