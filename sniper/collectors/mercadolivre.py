"""Coletor do Mercado Livre usando a API oficial (api.mercadolibre.com).

Autenticação: OAuth2. Rode `python auth_ml.py` uma vez para gerar o token;
depois o coletor renova sozinho com o refresh_token.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from datetime import datetime, timezone

from .. import segredos
from ..models import Offer, SellerInfo, Watch
from ..ratelimit import RateLimiter
from .base import Collector, CollectorError

log = logging.getLogger("sniper.ml")

API = "https://api.mercadolibre.com"
SITE = "MLB"  # Brasil


class TokenStore:
    def __init__(self, path: Path, client_id: str, client_secret: str, cofre: bool = False):
        self.path = path
        self.client_id = client_id
        self.client_secret = client_secret
        self.cofre = cofre  # True: tokens no cofre do Windows em vez de arquivo
        if cofre:
            self.data: dict = json.loads(segredos.ler("ml_token") or "{}")
        else:
            self.data = json.loads(path.read_text()) if path.exists() else {}
        self._lock = asyncio.Lock()

    @property
    def has_token(self) -> bool:
        return bool(self.data.get("refresh_token") or self.data.get("access_token"))

    def save(self, payload: dict) -> None:
        self.data = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token", self.data.get("refresh_token")),
            "expires_at": time.time() + int(payload.get("expires_in", 21600)) - 120,
            "user_id": payload.get("user_id", self.data.get("user_id")),
        }
        if self.cofre:
            segredos.guardar("ml_token", json.dumps(self.data))
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    async def access_token(self, client: httpx.AsyncClient) -> str:
        async with self._lock:
            if self.data.get("access_token") and time.time() < self.data.get("expires_at", 0):
                return self.data["access_token"]
            if not self.data.get("refresh_token"):
                raise CollectorError("Mercado Livre sem conexão. Abra \"Conectar ML\" no app e autorize.")
            r = await client.post(f"{API}/oauth/token", data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.data["refresh_token"],
            }, headers={"accept": "application/json"})
            if r.status_code != 200:
                raise CollectorError(f"Falha ao renovar token do ML ({r.status_code}): {r.text[:200]}. "
                                     "Abra \"Conectar ML\" e confira o Client ID e o Client Secret.")
            self.save(r.json())
            log.info("Token do Mercado Livre renovado")
            return self.data["access_token"]


def _to_offer(it: dict, watch: Watch, catalog_id: str, nome: str, thumb: str,
              marca: str = "") -> Optional[Offer]:
    """Um vendedor de um produto do catálogo (/products/{id}/items)."""
    if not it or it.get("price") is None or not it.get("item_id"):
        return None
    iid = it["item_id"]
    return Offer(
        store="mercadolivre",
        item_id=iid,
        title=nome,
        price=float(it["price"]),
        original_price=float(it["original_price"]) if it.get("original_price") else None,
        url=f"https://produto.mercadolivre.com.br/{iid[:3]}-{iid[3:]}",
        thumbnail=thumb,
        category=it.get("category_id", ""),
        free_shipping=bool((it.get("shipping") or {}).get("free_shipping")),
        watch=watch.name,
        seller_id=str(it.get("seller_id") or ""),
        condition=it.get("condition") or "",
        catalog_id=catalog_id,
        brand=marca,
        # loja oficial da marca ou venda do próprio Mercado Livre
        official_seller=bool(it.get("official_store_id")) or "first_party" in (it.get("tags") or []),
    )


class MercadoLivreCollector(Collector):
    store = "mercadolivre"
    supports_sweep = True
    supports_refresh = True
    refresh_por_catalogo = True  # a fila rápida manda ids de produto do catálogo, não de anúncio

    def __init__(self, client_id: str, client_secret: str, token_path: Path, max_concurrency: int = 4,
                 limiter: Optional[RateLimiter] = None, cofre: bool = False):
        self.tokens = TokenStore(token_path, client_id, client_secret, cofre=cofre)
        self.client = httpx.AsyncClient(timeout=15, headers={"user-agent": "sniper-ofertas/0.1"})
        self.sem = asyncio.Semaphore(max_concurrency)
        self.limiter = limiter
        self._sleep = asyncio.sleep  # trocado nos testes para não esperar de verdade
        self._produtos: dict[str, tuple[str, str, str]] = {}  # cache: id do produto -> (nome, foto, marca)
        self._aviso_itens = False

    async def _get(self, path: str, params: dict | None = None, fila: str = "normal",
                   timeout: float | None = None, penalizar: bool = True) -> dict | list:
        token = await self.tokens.access_token(self.client)
        extra = {"timeout": timeout} if timeout else {}
        status = None
        for attempt in range(4):
            if self.limiter:
                await self.limiter.acquire(fila)
            async with self.sem:
                r = await self.client.get(f"{API}{path}", params=params,
                                          headers={"Authorization": f"Bearer {token}"}, **extra)
            status = r.status_code
            if status == 429 or status >= 500:
                await self._sleep(2 ** attempt)
                continue
            if status == 401:
                self.tokens.data["expires_at"] = 0
                token = await self.tokens.access_token(self.client)
                continue
            if status == 403:
                if penalizar:
                    self._penalize(f"ML recusou {path} (403)")
                raise CollectorError(f"ML recusou {path} (403). Confira se o app tem permissão "
                                     f"para esse recurso. Resposta: {r.text[:160]}")
            r.raise_for_status()
            if self.limiter:
                self.limiter.success()
            return r.json()
        if status == 429 and penalizar:
            self._penalize("ML: muitas requisições (429)")
        raise CollectorError(f"ML não respondeu em {path} após várias tentativas")

    def _penalize(self, motivo: str) -> None:
        if self.limiter:
            dur = self.limiter.penalize(motivo)
            log.warning("Mercado Livre pausado por %d min: %s", dur // 60, motivo)

    # ---------- catálogo ----------
    # A busca de anúncios (/sites/MLB/search) e a leitura direta (/items) dão 403 para apps comuns;
    # o catálogo é liberado e mostra todos os vendedores do MESMO produto lado a lado (ótimo para achar bug).
    async def _produto(self, pid: str, fila: str) -> tuple[str, str, str]:
        """Nome, foto e marca do produto do catálogo (em cache: não mudam)."""
        if pid not in self._produtos:
            try:
                p = await self._get(f"/products/{pid}", fila=fila, penalizar=False)
            except (CollectorError, httpx.HTTPError):
                p = {}
            pics = p.get("pictures") or [{}]
            marca = next((a.get("value_name") or "" for a in p.get("attributes") or [] if a.get("id") == "BRAND"), "")
            self._produtos[pid] = (p.get("name") or pid, (pics[0].get("url") or "").replace("http://", "https://"),
                                   marca)
        return self._produtos[pid]

    async def _vendedores(self, pid: str, watch: Watch, fila: str = "normal") -> list[Offer]:
        """Todos os vendedores de um produto do catálogo."""
        nome, thumb, marca = await self._produto(pid, fila)
        try:
            data = await self._get(f"/products/{pid}/items", {"limit": 100}, fila=fila, penalizar=False)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:  # produto sem vendedor ativo
                return []
            raise
        return [o for o in (_to_offer(it, watch, pid, nome, thumb, marca) for it in data.get("results", [])) if o]

    async def _mais_vendidos(self, categoria: str) -> list[str]:
        try:
            data = await self._get(f"/highlights/{SITE}/category/{categoria}", penalizar=False)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:  # categoria sem ranking de mais vendidos
                return []
            raise
        return [c["id"] for c in data.get("content", []) if c.get("type") == "PRODUCT"]

    async def _de_produtos(self, pids: list[str], watch: Watch, fila: str = "normal") -> list[Offer]:
        offers: list[Offer] = []
        for pid in dict.fromkeys(pids):
            offers += await self._vendedores(pid, watch, fila)
        return offers

    async def collect(self, watch: Watch) -> list[Offer]:
        if watch.item_ids and not self._aviso_itens:
            self._aviso_itens = True
            log.warning("ML: leitura de anúncio avulso (itens=[...]) é bloqueada pela API; use busca ou categoria")
        pids: list[str] = []
        if watch.query:
            for page in range(max(1, watch.max_pages)):
                data = await self._get("/products/search", {"status": "active", "site_id": SITE,
                                                            "q": watch.query, "limit": 10, "offset": page * 10})
                res = data.get("results", [])
                pids += [r["id"] for r in res if r.get("id")]
                if len(res) < 10:
                    break
        if watch.category:
            pids += await self._mais_vendidos(watch.category)
        return await self._de_produtos(pids, watch)

    # ---------- varredura ----------
    async def _category_dump(self) -> dict[str, list[str]]:
        """Árvore inteira em uma chamada. Se falhar, devolve {} e sweep_units lê nó a nó."""
        try:
            data = await self._get(f"/sites/{SITE}/categories/all", timeout=120, penalizar=False)
        except (CollectorError, httpx.HTTPError, ValueError) as e:
            log.warning("Dump de categorias do ML indisponível (%s); lendo a árvore nó a nó", e)
            return {}
        return {cid: [c["id"] for c in (node.get("children_categories") or [])] for cid, node in data.items()}

    async def sweep_units(self, watch: Watch) -> list[str]:
        """Categorias do 2º nível (algumas centenas): cada uma tem seu ranking de mais vendidos.
        Com categorias escolhidas na regra, usa exatamente elas."""
        if watch.sweep_categories:
            return list(watch.sweep_categories)
        roots = [c["id"] for c in await self._get(f"/sites/{SITE}/categories")]
        tree = await self._category_dump()
        units: list[str] = []
        for root in roots:
            if root in tree:
                kids = tree[root]
            else:
                node = await self._get(f"/categories/{root}")
                kids = [c["id"] for c in (node.get("children_categories") or [])]
            units += kids or [root]
        return list(dict.fromkeys(units))

    async def sweep(self, unit: str, watch: Watch) -> list[Offer]:
        # Mais vendidos da categoria e, de cada um, todos os vendedores: um preço fora da curva salta aos olhos.
        return await self._de_produtos(await self._mais_vendidos(unit), watch)

    async def refresh(self, item_ids: list[str]) -> list[Offer]:
        """Recebe ids de PRODUTO do catálogo (refresh_por_catalogo) e relê todos os vendedores."""
        return await self._de_produtos(item_ids, Watch(name="Fila rápida", store=self.store), fila="rapida")

    async def seller_info(self, offer: Offer) -> Optional[SellerInfo]:
        if not offer.seller_id:
            return None
        u = await self._get(f"/users/{offer.seller_id}")
        rep = u.get("seller_reputation") or {}
        tx = rep.get("transactions") or {}
        days = None
        if u.get("registration_date"):
            try:
                reg = datetime.fromisoformat(u["registration_date"].replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - reg).days
            except ValueError:
                pass
        site_status = (u.get("status") or {}).get("site_status", "active")
        return SellerInfo(seller_id=offer.seller_id, nickname=u.get("nickname", ""),
                          sales=tx.get("completed", tx.get("total")), level=rep.get("level_id"),
                          registered_days=days, status=site_status)

    async def confirm(self, offer: Offer) -> Optional[Offer]:
        """Relê o produto do catálogo e acha o anúncio do vendedor. None se ele saiu do produto."""
        if not offer.catalog_id:
            return offer
        w = Watch(name=offer.watch, store=self.store)
        fresh = next((o for o in await self._vendedores(offer.catalog_id, w) if o.item_id == offer.item_id), None)
        if fresh:
            fresh.seller_name = offer.seller_name
            fresh.confirmed = True
        return fresh

    async def close(self) -> None:
        await self.client.aclose()
