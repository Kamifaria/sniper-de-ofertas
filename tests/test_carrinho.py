"""Link que já põe o produto no carrinho: VTEX e Amazon, gravado no alerta e mandado no aviso."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_amazon import item  # noqa: E402
from test_vtex import produto, rodar, W  # noqa: E402
import httpx  # noqa: E402
from sniper.collectors import amazon as amz  # noqa: E402
from sniper.db import Database  # noqa: E402
from sniper.models import Offer, Verdict, Watch  # noqa: E402
from sniper.notify import format_text  # noqa: E402


class CarrinhoTests(unittest.TestCase):
    def test_vtex(self):
        offers = rodar(lambda req: httpx.Response(200, json=[produto("1", "100", 30.0)]),
                       lambda c: c.sweep("/2/", W))
        self.assertEqual(offers[0].cart_url,
                         "https://loja.test/checkout/cart/add?sku=100&qty=1&seller=1&redirect=true")

    def test_amazon_com_tag_de_afiliado(self):
        o = amz._to_offer(item("A1", 199.9), Watch(name="w", store="amazon"), tag="minhatag-20")
        self.assertEqual(o.cart_url, "https://www.amazon.com.br/gp/aws/cart/add.html"
                                     "?ASIN.1=A1&Quantity.1=1&AssociateTag=minhatag-20")

    def test_gravado_no_alerta_e_no_aviso(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "t.db")
            o = Offer(store="t", item_id="1", title="Produto", price=10.0, url="https://x/p",
                      cart_url="https://x/carrinho")
            a = db.save_alert(o, Verdict(95, "CRITICO", ["motivo"], 100.0, 0.9))
            db.conn.close()
        self.assertEqual(a["cart_url"], "https://x/carrinho")
        self.assertIn("🛒 Pôr no carrinho: https://x/carrinho", format_text(a))

    def test_sem_carrinho_o_aviso_nao_muda(self):
        a = {"level": "ALTO", "score": 70, "title": "P", "price": 10.0, "url": "https://x/p", "cart_url": ""}
        self.assertNotIn("carrinho", format_text(a))


if __name__ == "__main__":
    unittest.main()
