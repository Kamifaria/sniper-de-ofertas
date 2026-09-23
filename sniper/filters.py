"""Filtros que descartam anúncios que não valem seu tempo:
lojas testando, anúncios de teste, usados, acessórios, vendedores sem histórico.

Duas etapas:
  * check_listing(): barata, só olha o anúncio (roda em tudo que é coletado)
  * check_seller():  consulta o vendedor (roda só em quem ia virar alerta)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .models import Offer, SellerInfo, Watch

# Termos que indicam anúncio de teste ou que não é o produto de verdade.
TEST_WORDS = [
    "teste", "testes", "testando", "test", "testing", "anuncio teste", "produto teste",
    "nao comprar", "nao compre", "nao efetue", "favor nao comprar", "ignorar", "ignore",
    "desativado", "indisponivel", "sem estoque", "esgotado",
    "somente a caixa", "so a caixa", "apenas a caixa", "caixa vazia", "somente caixa",
    "replica", "copia", "similar ao", "linha premium",
    "com defeito", "defeito", "para pecas", "retirada de pecas", "sucata", "tela quebrada",
    "leia a descricao", "leia o anuncio", "reserva", "sinal de", "aluguel", "locacao", "consorcio",
    "foto ilustrativa", "vale presente", "cupom de", "servico de",
]

# Acessórios que aparecem na busca do produto principal.
ACCESSORY_WORDS = [
    "capa", "capinha", "case", "pelicula", "skin", "adesivo", "suporte", "pulseira",
    "bolsa para", "estojo", "protetor", "compativel com", "para iphone", "para samsung",
]

# Palavras da busca que não precisam aparecer no título.
STOPWORDS = {"de", "da", "do", "das", "dos", "e", "para", "com", "a", "o", "em", "gb", "tb"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _has_phrase(norm_title: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(normalize(phrase))}(?![a-z0-9])", norm_title) is not None


@dataclass
class FilterConfig:
    test_words: list[str] = field(default_factory=lambda: list(TEST_WORDS))
    accessory_words: list[str] = field(default_factory=lambda: list(ACCESSORY_WORDS))
    exclude_used: bool = True
    require_query_terms: bool = True
    min_seller_sales: int = 10
    min_seller_days: int = 30
    confirm_before_alert: bool = True


def check_listing(o: Offer, w: Optional[Watch], cfg: FilterConfig, blocked: set[str]) -> Optional[str]:
    """Retorna o motivo do descarte, ou None se o anúncio passou."""
    if o.seller_id and f"{o.store}:{o.seller_id}" in blocked:
        return f"Vendedor bloqueado ({o.seller_name or o.seller_id})"
    if o.available_qty is not None and o.available_qty <= 0:
        return "Sem estoque"
    if cfg.exclude_used and o.condition == "used" and not (w and w.allow_used):
        return "Produto usado"

    title = normalize(o.title)
    query = normalize(w.query) if w and w.query else ""

    for word in cfg.test_words + (w.exclude_words if w else []):
        if _has_phrase(title, word) and not (query and _has_phrase(query, word)):
            return f"Título contém \"{word}\""

    if query:
        for word in cfg.accessory_words:
            if _has_phrase(title, word) and not _has_phrase(query, word):
                return f"Acessório (\"{word}\")"
        if cfg.require_query_terms:
            missing = missing_query_terms(title, query)
            if missing:
                return f"Não bate com a busca (falta \"{missing}\")"
    return None


# Sinônimos comuns em títulos (a busca "playstation 5" deve aceitar "PS5").
ALIASES = {
    "playstation": ["ps", "ps3", "ps4", "ps5", "psn"],
    "televisao": ["tv", "televisor"], "tv": ["televisao", "televisor"],
    "notebook": ["laptop"], "celular": ["smartphone"], "smartphone": ["celular"],
    "geladeira": ["refrigerador"], "refrigerador": ["geladeira"],
    "fone": ["headphone", "headset", "earbuds"],
}


def _token_in_title(title: str, token: str) -> bool:
    if token.isdigit():  # "5" casa com "ps5", mas não com "15"
        return re.search(rf"(?<![0-9]){token}(?![0-9])", title) is not None
    if _has_phrase(title, token):
        return True
    return any(re.search(rf"(?<![a-z0-9]){a}", title) for a in ALIASES.get(token, []))


def missing_query_terms(norm_title: str, norm_query: str) -> Optional[str]:
    """Números da busca são obrigatórios (modelo: 15 ≠ 13); das palavras, pelo menos metade."""
    tokens = [t for t in norm_query.split() if t not in STOPWORDS]
    for t in tokens:
        if t.isdigit() and not _token_in_title(norm_title, t):
            return t
    words = [t for t in tokens if not t.isdigit()]
    hits = sum(_token_in_title(norm_title, t) for t in words)
    if words and hits < max(1, (len(words) + 1) // 2):
        return next(t for t in words if not _token_in_title(norm_title, t))
    return None


def check_seller(s: Optional[SellerInfo], cfg: FilterConfig) -> Optional[str]:
    """Descarta lojas de teste: conta nova, sem vendas ou inativa."""
    if s is None:
        return None  # sem dados do vendedor: não dá para julgar
    if s.status and s.status != "active":
        return f"Vendedor {s.status}"
    if s.sales is not None and s.sales < cfg.min_seller_sales:
        return f"Loja com {s.sales} venda(s) — provável teste"
    if s.registered_days is not None and s.registered_days < cfg.min_seller_days:
        return f"Conta criada há {s.registered_days} dia(s) — provável teste"
    return None
