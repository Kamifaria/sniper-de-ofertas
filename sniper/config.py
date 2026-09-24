"""Carrega o config.toml (em português) para objetos do motor."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .detector import DetectorConfig
from .filters import FilterConfig
from .models import Watch


@dataclass
class LojaConfig:
    """Bloco [lojas.<chave>] do config.toml."""
    ativo: bool = False
    por_minuto: Optional[int] = None   # None = limite padrão da loja em sniper/stores.py


@dataclass
class Settings:
    base_dir: Path
    db_path: Path
    port: int = 8765
    min_alert_score: int = 70        # modo "só bugs": 70 = queda de ~70%+ ou queda brusca
    cooldown_min: int = 30
    repeat_alert_h: int = 24         # mesmo item e mesmo preço não alerta de novo nesse prazo
    valor_alto: float = 300.0        # fila rápida: itens a partir deste preço
    intervalo_rapido: int = 120      # fila rápida: segundos entre voltas
    max_itens_rapida: int = 1000     # fila rápida: teto de itens (os mais caros primeiro)
    ml_client_id: str = ""
    ml_client_secret: str = ""
    ml_redirect_uri: str = ""
    telegram_on: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_min_score: int = 70
    telegram_resumo: str = "09:00"   # horário do resumo diário; "" desliga
    telegram_travada_min: int = 30   # avisa se uma loja ficar esse tempo com erro ou pausada
    windows_on: bool = True
    windows_min_score: int = 70
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    watches: list[Watch] = field(default_factory=list)
    lojas: dict[str, LojaConfig] = field(default_factory=dict)


def _valida_horario(texto: str) -> str:
    """Valida `resumo_diario`: "" (desligado) ou "HH:MM" (H com 1 ou 2 dígitos, M com 2)."""
    if texto == "":
        return ""
    partes = texto.split(":")
    erro = ValueError(f'[telegram] resumo_diario inválido: "{texto}". '
                       'Use "HH:MM" (ex.: "09:00") ou "" para desligar.')
    if len(partes) != 2:
        raise erro
    hh, mm = partes
    if not (1 <= len(hh) <= 2) or not hh.isdigit() or len(mm) != 2 or not mm.isdigit():
        raise erro
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23) or not (0 <= m <= 59):
        raise erro
    return f"{h:02d}:{m:02d}"


def load(path: str | Path) -> Settings:
    path = Path(path).resolve()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    g = raw.get("geral", {})
    d = raw.get("detector", {})
    ml = raw.get("mercadolivre", {})
    tg = raw.get("telegram", {})
    win = raw.get("windows", {})
    f = raw.get("filtros", {})
    vr = raw.get("varredura", {})
    fc = FilterConfig()
    fc.test_words += [str(x) for x in f.get("palavras_teste_extras", [])]
    fc.accessory_words += [str(x) for x in f.get("acessorios_extras", [])]
    fc.counterfeit_brands += [str(x) for x in f.get("marcas_falsificadas_extras", [])]
    fc.exclude_used = bool(f.get("excluir_usados", fc.exclude_used))
    fc.require_query_terms = bool(f.get("exigir_termos_da_busca", fc.require_query_terms))
    fc.min_seller_sales = int(f.get("min_vendas_vendedor", fc.min_seller_sales))
    fc.min_seller_days = int(f.get("min_dias_conta_vendedor", fc.min_seller_days))
    fc.confirm_before_alert = bool(f.get("reconfirmar_preco", fc.confirm_before_alert))

    watches = []
    for w in raw.get("vigiar", []):
        watches.append(Watch(
            name=w["nome"],
            store=w.get("loja", "mercadolivre"),
            query=w.get("busca", ""),
            category=w.get("categoria", ""),
            item_ids=list(w.get("itens", [])),
            interval=int(w.get("intervalo", 120)),
            floor=w.get("piso"),
            max_pages=int(w.get("paginas", 1)),
            min_price=w.get("preco_minimo"),
            exclude_words=[str(x) for x in w.get("excluir", [])],
            allow_used=bool(w.get("aceitar_usados", False)),
        ))

    for v in raw.get("varrer", []):
        cats = v.get("categorias", "todas")
        if cats == "todas":
            sweep_categories = None
        elif isinstance(cats, str):
            sweep_categories = [cats]
        else:
            sweep_categories = [str(c) for c in cats]
        watches.append(Watch(
            name=v["nome"],
            store=v.get("loja", "mercadolivre"),
            kind="varrer",
            sweep_categories=sweep_categories,
            cycle_min=int(v.get("ciclo_minutos", 60)),
            max_pages=int(v.get("paginas", 1)),
            min_price=v.get("preco_minimo"),
            exclude_words=[str(x) for x in v.get("excluir", [])],
            allow_used=bool(v.get("aceitar_usados", False)),
        ))

    lojas: dict[str, LojaConfig] = {}
    for chave, lc in raw.get("lojas", {}).items():
        pm = lc.get("por_minuto")
        lojas[str(chave)] = LojaConfig(ativo=bool(lc.get("ativo", True)),
                                       por_minuto=int(pm) if pm is not None else None)
    if "mercadolivre" not in lojas and ml.get("client_id"):
        lojas["mercadolivre"] = LojaConfig(ativo=True)  # config antigo: só [mercadolivre]

    return Settings(
        base_dir=base,
        db_path=base / g.get("banco", "data/sniper.db"),
        port=int(g.get("porta", 8765)),
        min_alert_score=int(g.get("nota_minima_alerta", 70)),
        cooldown_min=int(g.get("cooldown_minutos", 30)),
        repeat_alert_h=int(g.get("repetir_alerta_horas", 24)),
        valor_alto=float(vr.get("valor_alto", 300)),
        intervalo_rapido=int(vr.get("intervalo_rapido", 120)),
        max_itens_rapida=int(vr.get("max_itens_rapida", 1000)),
        ml_client_id=str(ml.get("client_id", "")),
        ml_client_secret=str(ml.get("client_secret", "")),
        ml_redirect_uri=str(ml.get("redirect_uri", "")),
        telegram_on=bool(tg.get("ativo", False)),
        telegram_token=str(tg.get("bot_token", "")),
        telegram_chat_id=str(tg.get("chat_id", "")),
        telegram_min_score=int(tg.get("nota_minima", 70)),
        telegram_resumo=_valida_horario(str(tg.get("resumo_diario", "09:00"))),
        telegram_travada_min=int(tg.get("avisar_travada_minutos", 30)),
        windows_on=bool(win.get("notificacao", True)),
        windows_min_score=int(win.get("nota_minima", 70)),
        detector=DetectorConfig(
            free_threshold=float(d.get("preco_gratis", 1.0)),
            free_min_ref=float(d.get("gratis_referencia_minima", 10.0)),
            min_history=int(d.get("historico_minimo", 3)),
            min_peers=int(d.get("concorrentes_minimos", 2)),
        ),
        filters=fc,
        watches=watches,
        lojas=lojas,
    )
