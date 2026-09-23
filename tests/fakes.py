"""Coletores e motor falsos compartilhados pelos testes da fase 1."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sniper.collectors.base import Collector  # noqa: E402
from sniper.config import Settings  # noqa: E402
from sniper.engine import Engine  # noqa: E402
from sniper.models import Offer, SellerInfo  # noqa: E402


def oferta(iid: str, price: float, title: str = "Apple iPhone 15 128GB", seller: str = "GOOD",
           store: str = "t", catalog: str = "C1", **kw) -> Offer:
    return Offer(store=store, item_id=iid, title=title, price=price, url="https://x",
                 seller_id=seller, catalog_id=catalog, **kw)


class FakeCollector(Collector):
    store = "t"

    def __init__(self):
        self.batch: list[Offer] = []
        self.sellers = {"GOOD": SellerInfo("GOOD", "BOA_LOJA", 5000, "5_green", 2000)}

    async def collect(self, watch):
        return [Offer(**o.__dict__) for o in self.batch]

    async def seller_info(self, o):
        return self.sellers.get(o.seller_id)

    async def confirm(self, o):
        f = Offer(**o.__dict__)
        f.confirmed = True
        return f


class MotorDeTeste:
    """Engine sobre um banco temporário. Uso: `with MotorDeTeste(watches=[...]) as m: m.engine...`"""

    def __init__(self, watches=(), **settings_kw):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.settings = Settings(base_dir=base, db_path=base / "t.db", windows_on=False, **settings_kw)
        self.settings.watches = list(watches)
        self.engine = Engine(self.settings)

    def reabrir(self) -> Engine:
        """Fecha e recria o Engine sobre o mesmo banco (simula reiniciar o PC)."""
        self.engine.db.conn.close()
        self.engine = Engine(self.settings)
        return self.engine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.engine.db.conn.close()
        self.tmp.cleanup()


class FakeSweepCollector(FakeCollector):
    """Loja com varredura: cada unidade devolve uma oferta. `fail` = unidades que dão erro; `down` = sem internet."""
    supports_sweep = True

    def __init__(self, units):
        super().__init__()
        self.units = list(units)
        self.seen: list[str] = []
        self.fail: set[str] = set()
        self.down = False

    async def sweep_units(self, watch):
        return list(self.units)

    async def sweep(self, unit, watch):
        import httpx
        if self.down:
            raise httpx.ConnectError("sem internet")
        if unit in self.fail:
            raise ValueError("categoria sumiu")
        self.seen.append(unit)
        return [oferta(f"{unit}-1", 100.0, title="Produto qualquer", catalog="")]


class FakeRefreshCollector(FakeCollector):
    """Loja com refresh: devolve os preços de `prices` (item_id → preço) para os ids pedidos."""
    supports_refresh = True

    def __init__(self, prices):
        super().__init__()
        self.prices = dict(prices)
        self.pedidos: list[list[str]] = []

    async def refresh(self, item_ids):
        self.pedidos.append(list(item_ids))
        return [oferta(i, self.prices[i], catalog="") for i in item_ids if i in self.prices]
