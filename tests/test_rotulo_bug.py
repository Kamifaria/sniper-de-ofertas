"""O alerta diz com todas as letras que é bug de preço e qual a causa provável."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sniper.detector import causa_bug  # noqa: E402
from sniper.notify import format_text  # noqa: E402


def alerta(level, reasons, **kw):
    return {"level": level, "score": 90, "title": "Tênis X", "price": 49.9, "ref_price": 499.0,
            "drop_pct": 0.9, "reasons": reasons, "url": "https://l/p", "cart_url": "", **kw}


class RotuloBugTests(unittest.TestCase):
    def test_causas(self):
        self.assertEqual(causa_bug("GRATIS", ["Preço simbólico: R$ 0,01"]), "Item de graça")
        self.assertEqual(causa_bug("CRITICO", ["Parece vírgula errada: 1/10 do preço normal"]),
                         "Vírgula no lugar errado")
        self.assertEqual(causa_bug("ALTO", ["80% abaixo de 4 concorrentes"]), "Preço isolado muito abaixo dos concorrentes")
        self.assertEqual(causa_bug("ALTO", ["60% abaixo do próprio histórico"]), "Queda brusca no preço do anúncio")
        self.assertEqual(causa_bug("MEDIO", ["Abaixo do piso de R$ 100,00"]), "Abaixo do piso da regra")

    def test_virgula_vence_queda(self):
        self.assertEqual(causa_bug("CRITICO", ["90% abaixo do próprio histórico", "Parece vírgula errada: 1/10 do preço normal"]),
                         "Vírgula no lugar errado")

    def test_sem_nivel_nao_e_bug(self):
        self.assertEqual(causa_bug("NENHUM", []), "")

    def test_telegram_abre_com_bug_de_preco_e_a_causa(self):
        t = format_text(alerta("CRITICO", ["Parece vírgula errada: 1/10 do preço normal"]))
        self.assertIn("BUG DE PREÇO", t.splitlines()[0])
        self.assertIn("Vírgula no lugar errado", t)

    def test_usa_o_campo_bug_quando_o_banco_ja_traz(self):
        t = format_text(alerta("ALTO", [], bug="Causa vinda do banco"))
        self.assertIn("Causa vinda do banco", t)


if __name__ == "__main__":
    unittest.main()
