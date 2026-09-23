"""Coletor de demonstração: simula uma loja com preços estáveis e,
de vez em quando, um "bug" (vírgula errada, R$ 0,00, queda brusca).
Também simula lojas de teste, anúncios "TESTE NÃO COMPRAR", usados e capinhas,
para mostrar os filtros trabalhando. Não precisa de credencial."""
from __future__ import annotations

import random
from typing import Optional

from ..models import Offer, SellerInfo, Watch
from .base import Collector

CATALOGO = [
    ("iPhone 15 128GB", 4899.0), ("PlayStation 5 Slim", 3599.0), ("Notebook Gamer RTX 4060", 6499.0),
    ("Smart TV 55\" 4K", 2499.0), ("Air Fryer 5L", 399.0), ("Galaxy S24", 3999.0),
    ("Fone Bluetooth ANC", 899.0), ("Monitor 27\" 165Hz", 1299.0), ("Geladeira Frost Free", 3299.0),
    ("Cadeira Gamer", 1199.0), ("Kindle Paperwhite", 799.0), ("Nintendo Switch OLED", 2299.0),
    ("Robô Aspirador", 1499.0), ("Tênis de Corrida", 599.0), ("SSD NVMe 2TB", 849.0),
]

# (id, apelido, vendas, dias de conta)
VENDEDORES = [
    ("S1", "MEGASTORE_OFICIAL", 48210, 2900), ("S2", "TECHBR", 9120, 1500),
    ("S3", "CASA_E_CIA", 3304, 800), ("SX", "LOJA_TESTE_2026", 0, 3),
]
LIXO = [  # anúncios que os filtros devem descartar
    ("TESTE NÃO COMPRAR iPhone 15", 1.00, "S2", "new"),
    ("Capinha iPhone 15 Silicone", 19.90, "S3", "new"),
    ("PlayStation 5 com defeito para peças", 900.0, "S3", "used"),
]


class DemoCollector(Collector):
    store = "demo"

    def __init__(self, glitch_rate: float = 0.005, junk_rate: float = 0.05, seed: int | None = None):
        self.rng = random.Random(seed)
        self.glitch_rate = glitch_rate
        self.junk_rate = junk_rate

    def _offer(self, item_id, title, price, seller, watch, catalog="", orig=None, cond="new"):
        sid, nick, *_ = next(v for v in VENDEDORES if v[0] == seller)
        return Offer(store="demo", item_id=item_id, title=f"[DEMO] {title}", price=price,
                     original_price=orig, url=f"https://www.mercadolivre.com.br/?demo={item_id}",
                     category="demo", free_shipping=self.rng.random() < 0.5, watch=watch.name,
                     seller_id=sid, seller_name=nick, condition=cond, catalog_id=catalog, available_qty=5)

    async def collect(self, watch: Watch) -> list[Offer]:
        offers = []
        for i, (title, base) in enumerate(CATALOGO):
            for j, seller in enumerate(("S1", "S2", "S3")):  # 3 vendedores por produto
                price = round(base * self.rng.uniform(0.95, 1.05) * (1 + 0.03 * j), 2)
                orig = round(base * 1.3, 2) if self.rng.random() < 0.3 else None
                if j == 0 and self.rng.random() < self.glitch_rate:
                    kind = self.rng.choice(["virgula", "gratis", "queda"])
                    price = {"virgula": round(base / 10, 2), "gratis": 0.0,
                             "queda": round(base * self.rng.uniform(0.3, 0.5), 2)}[kind]
                offers.append(self._offer(f"D{i:02d}{seller}", title, price, seller, watch,
                                          catalog=f"CAT{i:02d}", orig=orig))
        # Loja de teste: conta nova, sem vendas, preço absurdo
        if self.rng.random() < self.junk_rate:
            i = self.rng.randrange(len(CATALOGO))
            offers.append(self._offer(f"DX{i:02d}", CATALOGO[i][0], round(CATALOGO[i][1] / 20, 2), "SX",
                                      watch, catalog=f"CAT{i:02d}"))
        if self.rng.random() < self.junk_rate:
            k = self.rng.randrange(len(LIXO))
            t, p, s, c = LIXO[k]
            offers.append(self._offer(f"DJ{k}", t, p, s, watch, cond=c))
        return offers

    async def seller_info(self, offer: Offer) -> Optional[SellerInfo]:
        for sid, nick, sales, days in VENDEDORES:
            if sid == offer.seller_id:
                return SellerInfo(seller_id=sid, nickname=nick, sales=sales, registered_days=days)
        return None

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        offer.confirmed = True
        return offer
