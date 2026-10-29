"""Coletor da KaBuM pela API pública de catálogo do site (sem login).

Endpoint não oficial: a loja pode bloquear ou mudar sem aviso.
Cada categoria lista até 100 páginas; pedimos do mais barato para o mais caro, então um preço com bug
aparece na primeira página.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from ..models import Offer, Watch
from ..ratelimit import RateLimiter
from .base import Collector, CollectorError

log = logging.getLogger("sniper.kabum")

API = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2"
SITE = "https://www.kabum.com.br"
POR_PAGINA = 100
# Categorias de topo que têm produto (conferido em 2026-10-29).
CATEGORIAS = ["hardware", "perifericos", "computadores", "tv", "celular-smartphone", "audio",
              "casa-inteligente", "cameras-e-drones", "eletrodomesticos"]


def _preco(a: dict) -> Optional[float]:
    """Menor preço que a loja pratica agora: oferta relâmpago, senão preço com desconto (Pix), senão cheio."""
    oferta = (a.get("offer") or {}).get("price_with_discount")
    for p in (oferta, a.get("price_with_discount"), a.get("price")):
        if p and p > 0:
            return float(p)
    return None


def _to_offer(prod: dict, watch: Watch) -> Optional[Offer]:
    a = prod.get("attributes") or {}
    pid = str(prod.get("id") or "")
    preco = _preco(a)
    if not pid or preco is None or not a.get("available") or (a.get("stock") or 0) <= 0:
        return None
    cheio = a.get("old_price") or 0
    mp = a.get("is_marketplace")
    vend = a.get("marketplace") or {}
    fotos = (a.get("photos") or {}).get("p") or (a.get("images") or [])
    return Offer(
        store="kabum",
        item_id=pid,
        title=a.get("title") or "",
        price=preco,
        original_price=float(cheio) if cheio and cheio > preco else None,
        url=f"{SITE}/produto/{pid}/{a.get('product_link') or ''}".rstrip("/"),
        thumbnail=fotos[0] if fotos and isinstance(fotos[0], str) else "",
        category=(a.get("menu") or "").split("/")[0],
        free_shipping=bool(a.get("has_free_shipping")),
        available_qty=a.get("stock"),
        watch=watch.name,
        seller_id=str(vend.get("seller_id") or "") if mp else "",
        seller_name=vend.get("seller_name") or "" if mp else "",
        condition="used" if a.get("is_openbox") else "new",
        brand=(a.get("manufacturer") or {}).get("name") or "",
        official_seller=not mp,  # vendido e entregue pela própria KaBuM
    )


class KabumCollector(Collector):
    store = "kabum"
    supports_sweep = True
    supports_refresh = True
    peers_mesma_loja = False  # a API não traz código de barras: referência é o histórico do item
    precos_simbolicos = False

    def __init__(self, limiter: Optional[RateLimiter] = None, max_concurrency: int = 2):
        self.client = httpx.AsyncClient(timeout=30, follow_redirects=True,
                                        headers={"user-agent": "Mozilla/5.0 (sniper-ofertas)"})
        self.sem = asyncio.Semaphore(max_concurrency)
        self.limiter = limiter
        self._sleep = asyncio.sleep  # trocado nos testes para não esperar de verdade

    async def _get(self, path: str, params=None, fila: str = "normal") -> Optional[dict]:
        """None = a KaBuM respondeu 404 (categoria vazia ou produto que saiu do ar)."""
        status = None
        for attempt in range(4):
            if self.limiter:
                await self.limiter.acquire(fila)
            async with self.sem:
                r = await self.client.get(f"{API}{path}", params=params)
            status = r.status_code
            if status == 404:
                return None
            if status == 429 or status >= 500:
                await self._sleep(2 ** attempt)
                continue
            if status == 403:
                if self.limiter:
                    self.limiter.penalize("KaBuM recusou a consulta (403)")
                raise CollectorError("KaBuM bloqueou a consulta (403)")
            r.raise_for_status()
            if self.limiter:
                self.limiter.success()
            return r.json()
        if status == 429 and self.limiter:
            self.limiter.penalize("KaBuM: muitas requisições (429)")
        raise CollectorError(f"KaBuM não respondeu em {path} após várias tentativas (HTTP {status})")

    async def _lista(self, path: str, params: dict, watch: Watch, fila: str = "normal") -> list[Offer]:
        offers: list[Offer] = []
        for pagina in range(1, max(1, watch.max_pages) + 1):
            data = await self._get(path, {**params, "page_number": pagina, "page_size": POR_PAGINA, "sort": "price"},
                                   fila=fila)
            itens = (data or {}).get("data") or []
            offers += [o for o in (_to_offer(p, watch) for p in itens) if o]
            if len(itens) < POR_PAGINA:
                break
        return offers

    async def collect(self, watch: Watch) -> list[Offer]:
        if not watch.query:
            return []
        return await self._lista("/products", {"query": watch.query}, watch)

    async def sweep_units(self, watch: Watch) -> list[str]:
        return list(watch.sweep_categories) if watch.sweep_categories else list(CATEGORIAS)

    async def sweep(self, unit: str, watch: Watch) -> list[Offer]:
        return await self._lista(f"/products-by-category/{unit}", {}, watch)

    async def _produto(self, pid: str, watch: Watch, fila: str) -> Optional[Offer]:
        data = await self._get(f"/products/{pid}", fila=fila)
        return _to_offer(data, watch) if data else None

    async def refresh(self, item_ids: list[str]) -> list[Offer]:
        w = Watch(name="Fila rápida", store=self.store)
        achados = await asyncio.gather(*(self._produto(i, w, "rapida") for i in item_ids))
        return [o for o in achados if o]

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        fresh = await self._produto(offer.item_id, Watch(name=offer.watch, store=self.store), "normal")
        if fresh:
            fresh.confirmed = True
        return fresh

    async def close(self) -> None:
        await self.client.aclose()
