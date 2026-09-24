"""Coletor genérico para lojas VTEX, usando a busca pública de catálogo (sem login).

Endpoint não oficial para terceiros: a loja pode bloquear ou mudar sem aviso.
Uma instância por loja (chave + domínio), registrada em sniper/stores.py.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from ..models import Offer, Watch
from ..ratelimit import RateLimiter
from .base import Collector, CollectorError

log = logging.getLogger("sniper.vtex")

SEARCH = "/api/catalog_system/pub/products/search"
# 3 níveis: em algumas lojas /10 leva 40+ s; se houver nível mais fundo, o filtro C: já inclui as subcategorias.
TREE = "/api/catalog_system/pub/category/tree/3"
PAGINA = 50  # a VTEX devolve no máximo 50 produtos por chamada (_from.._to)


def _to_offers(prod: dict, store: str, watch: Watch, only: Optional[set[str]] = None) -> list[Offer]:
    offers = []
    for item in prod.get("items") or []:
        sku = str(item.get("itemId", ""))
        if not sku or (only is not None and sku not in only):
            continue
        sellers = item.get("sellers") or []
        seller = next((s for s in sellers if s.get("sellerDefault")), sellers[0] if sellers else None)
        if not seller:
            continue
        co = seller.get("commertialOffer") or {}
        price = co.get("Price")
        if price is None or not co.get("IsAvailable", True) or (co.get("AvailableQuantity") or 0) <= 0:
            continue
        lista = co.get("ListPrice")
        imgs = item.get("images") or []
        offers.append(Offer(
            store=store,
            item_id=sku,
            title=prod.get("productName") or item.get("name") or "",
            price=float(price),
            original_price=float(lista) if lista and lista > price else None,
            url=prod.get("link") or "",
            thumbnail=(imgs[0].get("imageUrl") or "") if imgs else "",
            category=str(prod.get("categoryId") or ""),
            available_qty=co.get("AvailableQuantity"),
            watch=watch.name,
            seller_id=str(seller.get("sellerId") or ""),
            seller_name=seller.get("sellerName") or "",
            condition="new",
            catalog_id=item.get("ean") or "",
            brand=prod.get("brand") or "",
            official_seller=str(seller.get("sellerId")) == "1",  # "1" é a própria loja; o resto é marketplace
        ))
    return offers


class VtexCollector(Collector):
    supports_sweep = True
    supports_refresh = True
    peers_mesma_loja = False  # o mesmo EAN aparece em unidade e caixa: só compara com outras lojas
    precos_simbolicos = True  # a VTEX mostra R$ 0,00/0,01 em item "sob consulta" ou sem preço para o canal

    def __init__(self, chave: str, dominio: str, limiter: Optional[RateLimiter] = None, max_concurrency: int = 2):
        self.store = chave
        self.base = f"https://{dominio}"
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=True,
                                        headers={"user-agent": "Mozilla/5.0 (sniper-ofertas)"})
        self.sem = asyncio.Semaphore(max_concurrency)
        self.limiter = limiter
        self._sleep = asyncio.sleep  # trocado nos testes para não esperar de verdade

    async def _get(self, path: str, params=None, fila: str = "normal"):
        status = None
        for attempt in range(4):
            if self.limiter:
                await self.limiter.acquire(fila)
            async with self.sem:
                r = await self.client.get(f"{self.base}{path}", params=params)
            status = r.status_code
            if status == 429 or status >= 500:
                await self._sleep(2 ** attempt)
                continue
            if status == 403:
                self._penalize(f"{self.store} recusou {path} (403)")
                raise CollectorError(f"{self.store} bloqueou a consulta (403)")
            r.raise_for_status()  # 206 (Partial Content) é a resposta normal da busca paginada
            if self.limiter:
                self.limiter.success()
            return r.json()
        if status == 429:
            self._penalize(f"{self.store}: muitas requisições (429)")
        raise CollectorError(f"{self.store} não respondeu em {path} após várias tentativas (HTTP {status})")

    def _penalize(self, motivo: str) -> None:
        if self.limiter:
            dur = self.limiter.penalize(motivo)
            log.warning("%s pausada por %d min: %s", self.store, dur // 60, motivo)

    async def _search(self, params: list, watch: Watch, fila: str = "normal") -> list[Offer]:
        offers: list[Offer] = []
        for page in range(max(1, watch.max_pages)):
            ini = page * PAGINA
            data = await self._get(SEARCH, params + [("O", "OrderByPriceASC"), ("_from", ini),
                                                     ("_to", ini + PAGINA - 1)], fila=fila)
            for prod in data:
                offers += _to_offers(prod, self.store, watch)
            if len(data) < PAGINA:
                break
        return offers

    async def collect(self, watch: Watch) -> list[Offer]:
        params = []
        if watch.query:
            params.append(("ft", watch.query))
        if watch.category:
            params.append(("fq", f"C:{watch.category}"))
        return await self._search(params, watch) if params else []

    # ---------- varredura ----------
    async def sweep_units(self, watch: Watch) -> list[str]:
        """Caminhos das categorias finais ("/1/10/"), que é o formato do filtro fq=C: da VTEX."""
        leaves: list[str] = []

        def walk(node: dict, path: list[str]) -> None:
            p = path + [str(node["id"])]
            kids = node.get("children") or []
            if kids:
                for k in kids:
                    walk(k, p)
            else:
                leaves.append("/" + "/".join(p) + "/")

        for root in await self._get(TREE):
            walk(root, [])
        if watch.sweep_categories:  # ids de categoria em qualquer nível: fica só com as folhas abaixo delas
            ids = {str(c).strip("/") for c in watch.sweep_categories}
            leaves = [leaf for leaf in leaves if any(f"/{i}/" in leaf for i in ids)]
        return leaves

    async def sweep(self, unit: str, watch: Watch) -> list[Offer]:
        # Do mais barato para o mais caro: um preço com bug aparece no topo da categoria.
        return await self._search([("fq", f"C:{unit}")], watch)

    async def _skus(self, ids: list[str], watch: Watch, fila: str) -> list[Offer]:
        offers: list[Offer] = []
        for i in range(0, len(ids), PAGINA):
            lote = ids[i:i + PAGINA]
            data = await self._get(SEARCH, [("fq", f"skuId:{s}") for s in lote] + [("_from", 0), ("_to", PAGINA - 1)],
                                   fila=fila)
            for prod in data:
                offers += _to_offers(prod, self.store, watch, only=set(lote))
        return offers

    async def refresh(self, item_ids: list[str]) -> list[Offer]:
        return await self._skus(item_ids, Watch(name="Fila rápida", store=self.store), fila="rapida")

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        fresh = await self._skus([offer.item_id], Watch(name=offer.watch, store=self.store), fila="normal")
        if not fresh:
            return None
        fresh[0].confirmed = True
        return fresh[0]

    async def close(self) -> None:
        await self.client.aclose()
