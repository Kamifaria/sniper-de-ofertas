"""Coletor da Amazon Brasil pela Creators API (API oficial do programa de afiliados).

Credencial v3.x (Login with Amazon), criada no Associados em Tools → Creators API → Create Credential.
A API libera poucas consultas (começa em 1 por segundo), então aqui não há varredura de catálogo:
só regras [[vigiar]] por busca ou por ASIN, e a fila rápida relendo de 10 em 10.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from ..models import Offer, Watch
from ..ratelimit import RateLimiter
from .base import Collector, CollectorError

log = logging.getLogger("sniper.amazon")

TOKEN_URL = "https://api.amazon.com/auth/o2/token"  # região NA (EUA, Canadá, México e Brasil)
API = "https://creatorsapi.amazon/catalog/v1"
MARKETPLACE = "www.amazon.com.br"
LOTE = 10              # searchItems e getItems: no máximo 10 itens por chamada
INTERVALO_S = 1.1      # 1 consulta por segundo, com folga
RESOURCES = [
    "itemInfo.title", "itemInfo.byLineInfo", "itemInfo.externalIds", "images.primary.medium",
    "offersV2.listings.price", "offersV2.listings.availability", "offersV2.listings.merchantInfo",
    "offersV2.listings.condition", "offersV2.listings.isBuyBoxWinner",
]


def _k(d: Any, *chaves: str) -> Any:
    """Caminho num dicionário sem diferenciar maiúsculas (a documentação mistura "EANs" e "eans")."""
    for chave in chaves:
        if not isinstance(d, dict):
            return None
        d = next((v for k, v in d.items() if k.lower() == chave.lower()), None)
    return d


def _carrinho(asin: str, tag: str) -> str:
    """Formulário oficial de "adicionar ao carrinho" da Amazon, já com a tag de afiliado."""
    url = f"https://{MARKETPLACE}/gp/aws/cart/add.html?ASIN.1={asin}&Quantity.1=1"
    return f"{url}&AssociateTag={tag}" if tag else url


def _to_offer(it: dict, watch: Watch, tag: str = "") -> Optional[Offer]:
    listings = _k(it, "offersV2", "listings") or []
    listing = next((x for x in listings if _k(x, "isBuyBoxWinner")), listings[0] if listings else None)
    preco = _k(listing, "price", "money", "amount")
    if preco is None or _k(listing, "availability", "type") == "OUT_OF_STOCK":
        return None
    de = _k(listing, "price", "savingBasis", "money", "amount")
    vendedor = _k(listing, "merchantInfo", "name") or ""
    eans = _k(it, "itemInfo", "externalIds", "eans", "displayValues") or []
    condicao = (_k(listing, "condition", "value") or "").lower()
    asin = str(it.get("asin", ""))
    return Offer(
        store="amazon",
        item_id=asin,
        title=_k(it, "itemInfo", "title", "displayValue") or "",
        price=float(preco),
        original_price=float(de) if de and de > preco else None,
        url=_k(it, "detailPageURL") or "",  # já vem com a tag de afiliado
        thumbnail=_k(it, "images", "primary", "medium", "url") or "",
        watch=watch.name,
        seller_id=str(_k(listing, "merchantInfo", "id") or ""),
        seller_name=vendedor,
        condition="new" if condicao in ("new", "") else "used",
        catalog_id=eans[0] if eans else "",
        brand=_k(it, "itemInfo", "byLineInfo", "brand", "displayValue") or "",
        official_seller=vendedor.lower().startswith("amazon"),  # vendido pela própria Amazon
        cart_url=_carrinho(asin, tag),
    )


class AmazonCollector(Collector):
    store = "amazon"
    supports_refresh = True
    peers_mesma_loja = False  # compara pelo mesmo EAN em outras lojas

    def __init__(self, credencial_id: str, credencial_segredo: str, tag: str,
                 limiter: Optional[RateLimiter] = None):
        self.cred = (credencial_id, credencial_segredo)
        self.tag = tag
        self.limiter = limiter
        self.client = httpx.AsyncClient(timeout=20, headers={"user-agent": "sniper-ofertas/0.1"})
        self._token, self._vence = "", 0.0
        self._lock = asyncio.Lock()     # uma chamada por vez, com INTERVALO_S entre elas
        self._ultima = 0.0
        self._sleep = asyncio.sleep     # trocado nos testes para não esperar de verdade
        self._clock = time.monotonic

    async def _access_token(self) -> str:
        if self._token and time.time() < self._vence:
            return self._token
        r = await self.client.post(TOKEN_URL, auth=self.cred,
                                   data={"grant_type": "client_credentials", "scope": "creatorsapi::default"})
        if r.status_code != 200:
            raise CollectorError(f"Amazon recusou a credencial ({r.status_code}). Confira [amazon] no "
                                 f"config.toml: a credencial precisa ser v3 (Creators API). {r.text[:160]}")
        data = r.json()
        self._token, self._vence = data["access_token"], time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    async def _post(self, op: str, corpo: dict, fila: str = "normal") -> dict:
        corpo = {"partnerTag": self.tag, "resources": RESOURCES, **corpo}
        status = None
        for attempt in range(4):
            if self.limiter:
                await self.limiter.acquire(fila)
            async with self._lock:
                espera = INTERVALO_S - (self._clock() - self._ultima)
                if self._ultima and espera > 0:
                    await self._sleep(espera)
                token = await self._access_token()
                r = await self.client.post(f"{API}/{op}", json=corpo, headers={
                    "Authorization": f"Bearer {token}", "x-marketplace": MARKETPLACE})
                self._ultima = self._clock()
            status = r.status_code
            if status == 401:
                self._token = ""
                continue
            if status == 429 or status >= 500:
                await self._sleep(2 ** attempt)
                continue
            if status == 403:
                raise CollectorError("Amazon recusou a consulta (403). Confira a credencial e se a conta de "
                                     "afiliada tem o mínimo de vendas para usar a Creators API. "
                                     f"Resposta: {r.text[:160]}")
            r.raise_for_status()
            if self.limiter:
                self.limiter.success()
            return r.json()
        if status == 429 and self.limiter:
            dur = self.limiter.penalize("Amazon: muitas consultas (429)")
            log.warning("amazon pausada por %d min: muitas consultas (429)", dur // 60)
        raise CollectorError(f"Amazon não respondeu em {op} após várias tentativas (HTTP {status})")

    async def _itens(self, asins: list[str], watch: Watch, fila: str) -> list[Offer]:
        offers: list[Offer] = []
        for i in range(0, len(asins), LOTE):
            data = await self._post("getItems", {"itemIds": asins[i:i + LOTE], "itemIdType": "ASIN",
                                                 "condition": "New"}, fila=fila)
            for it in _k(data, "itemsResult", "items") or []:
                o = _to_offer(it, watch, self.tag)
                if o:
                    offers.append(o)
        return offers

    async def collect(self, watch: Watch) -> list[Offer]:
        offers: list[Offer] = []
        if watch.item_ids:
            offers += await self._itens(list(watch.item_ids), watch, "normal")
        if watch.query:
            # Do mais barato para o mais caro, já a partir do preço mínimo: um bug aparece no topo.
            base = {"keywords": watch.query, "itemCount": LOTE, "sortBy": "Price:LowToHigh", "condition": "New"}
            if watch.min_price:
                base["minPrice"] = int(round(watch.min_price * 100))  # em centavos
            for page in range(1, min(max(1, watch.max_pages), 10) + 1):
                itens = _k(await self._post("searchItems", {**base, "itemPage": page}), "searchResult", "items") or []
                offers += [o for o in (_to_offer(it, watch, self.tag) for it in itens) if o]
                if len(itens) < LOTE:
                    break
        return offers

    async def refresh(self, item_ids: list[str]) -> list[Offer]:
        return await self._itens(item_ids, Watch(name="Fila rápida", store=self.store), fila="rapida")

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        fresh = await self._itens([offer.item_id], Watch(name=offer.watch, store=self.store), fila="normal")
        if not fresh:
            return None
        fresh[0].confirmed = True
        return fresh[0]

    async def close(self) -> None:
        await self.client.aclose()
