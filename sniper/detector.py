"""Detector de anomalias de preço.

Combina vários sinais numa nota de 0 a 100:
  * item de graça / preço simbólico
  * queda em relação à mediana do histórico do anúncio
  * queda em relação aos outros vendedores do mesmo produto (catálogo)
  * queda brusca em relação à última leitura
  * preço abaixo do piso configurado na regra
  * preço que é 1/10 ou 1/100 do normal (vírgula no lugar errado)
O desconto "de/por" anunciado pela loja não soma pontos: é marketing.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional, Sequence

from .models import Offer, Verdict, Watch


@dataclass
class DetectorConfig:
    free_threshold: float = 1.00      # até R$ 1,00 conta como "de graça"
    free_min_ref: float = 10.0        # ...mas só se o preço normal era pelo menos isso (fermento de R$ 1,18 não conta)
    min_history: int = 3              # leituras mínimas para confiar na mediana
    min_peers: int = 2                # concorrentes mínimos para usar como referência
    min_peers_outras_lojas: int = 3   # mesmo código de barras em outras lojas: com 2 ainda erra muito
    market_band: float = 0.30         # concorrente até 30% acima (ou mais barato) conta como "vende perto"
    market_min_peers: int = 2         # ...e com tantos vendendo perto, é preço de mercado, não bug
    typo_tolerance: float = 0.08      # 1/10 ou 1/100 do preço normal, com 8% de folga, conta como vírgula errada
    level_critico: int = 90
    level_alto: int = 70
    level_medio: int = 50


def _drop(price: float, ref: Optional[float]) -> Optional[float]:
    if not ref or ref <= 0:
        return None
    return max(0.0, 1 - price / ref)


DROP_TABLE = ((0.85, 75), (0.70, 62), (0.55, 50), (0.40, 40), (0.25, 15))


def _drop_points(drop: Optional[float]) -> int:
    if drop is None:
        return 0
    for limit, pts in DROP_TABLE:
        if drop >= limit:
            return pts
    return 0


def _fracao_de_digitacao(price: float, refs: Sequence[float], tol: float) -> Optional[int]:
    """10 ou 100 se o preço for ~1/10 ou ~1/100 de alguma referência (vírgula deslocada)."""
    for ref in refs:
        for fracao in (10, 100):
            if abs(price * fracao / ref - 1) <= tol:
                return fracao
    return None


def evaluate(
    offer: Offer,
    history: Sequence[float],
    watch: Optional[Watch] = None,
    cfg: DetectorConfig = DetectorConfig(),
    peers: Sequence[float] = (),
) -> Verdict:
    """Avalia uma oferta.
    `history` = preços anteriores DESTE anúncio (mais antigo -> mais recente), sem a leitura atual.
    `peers`   = preços atuais de OUTROS vendedores do mesmo produto (catálogo)."""
    price = offer.price
    reasons: list[str] = []
    score = 0

    hist_med = median(history) if len(history) >= cfg.min_history else None
    peer_med = median(peers) if len(peers) >= cfg.min_peers else None
    typical = hist_med or peer_med or (median(history) if history else None)

    # Regra de ruído: item naturalmente barato (capinha, cabo) não interessa.
    if watch and watch.min_price and typical and typical < watch.min_price:
        return Verdict(0, "NENHUM", [], typical, None)

    # 1) De graça (sem referência também conta: item novo a R$ 0,00 é suspeito; preço simbólico fixo é filtrado no motor)
    if price <= cfg.free_threshold and (typical is None or typical >= cfg.free_min_ref):
        ref = typical
        return Verdict(100, "GRATIS", ["Preço simbólico: R$ " + f"{price:.2f}".replace(".", ",")], ref, _drop(price, ref))

    # 2) Queda vs histórico do próprio anúncio e vs concorrentes do mesmo produto
    d_hist, d_peer = _drop(price, hist_med), _drop(price, peer_med)
    p_hist, p_peer = _drop_points(d_hist), _drop_points(d_peer)
    if p_peer:
        # Bug é um preço isolado. Se outros vendem perto, é o preço de mercado (a mediana é que está alta).
        perto = sum(1 for p in peers if p <= price * (1 + cfg.market_band))  # mais barato também conta
        if perto >= cfg.market_min_peers:
            p_peer = 0
            reasons.append(f"Outros {perto} vendem perto desse preço")
        # Abaixo dos concorrentes, mas sempre custou isso aqui (ex.: unidade x caixa com o mesmo código).
        elif d_hist is not None and d_hist < 0.10:
            p_peer = 0
            reasons.append("É o preço de sempre nesta loja")
    if p_hist:
        reasons.append(f"{d_hist:.0%} abaixo do próprio histórico")
    if p_peer:
        reasons.append(f"{d_peer:.0%} abaixo de {len(peers)} concorrentes")
    score += max(p_hist, p_peer)
    if p_hist >= 40 and p_peer >= 40:
        score += 10; reasons.append("Confirmado por histórico e concorrentes")
    elif p_peer >= 62 and len(peers) >= 3:
        score += 15; reasons.append("Muito abaixo de vários concorrentes")
    # Caiu no histórico, mas os concorrentes vendem pelo mesmo preço: é queda de mercado, não bug.
    mercado = p_hist >= 40 and d_peer is not None and d_peer < 0.15
    if mercado:
        score -= 25; reasons.append("Concorrentes já vendem por preço parecido")
    # Vírgula no lugar errado: R$ 499,90 no lugar de R$ 4.999,00 é o bug mais comum.
    refs = [r for r, pts in ((hist_med, p_hist), (peer_med, p_peer)) if pts]
    fracao = None if mercado else _fracao_de_digitacao(price, refs, cfg.typo_tolerance)
    if fracao:
        score += 20; reasons.append(f"Parece vírgula errada: 1/{fracao} do preço normal")

    if peer_med and p_peer >= p_hist:
        ref_price, drop_pct = peer_med, d_peer
    else:
        ref_price, drop_pct = hist_med, d_hist

    # 3) Queda brusca vs última leitura
    if history:
        d_last = _drop(price, history[-1])
        if d_last is not None and d_last >= 0.50:
            score += 20; reasons.append(f"Caiu {d_last:.0%} desde a última coleta")
        elif d_last is not None and d_last >= 0.30:
            score += 10; reasons.append(f"Caiu {d_last:.0%} desde a última coleta")

    # 4) Abaixo do piso da regra
    if watch and watch.floor and price < watch.floor:
        below = 1 - price / watch.floor
        score += 30 if below >= 0.5 else 20
        reasons.append(f"Abaixo do piso de R$ {watch.floor:,.2f}")

    # O "de/por" que a loja anuncia não conta: é marketing, não referência de preço.

    # Bônus pequeno: frete grátis em queda forte
    if offer.free_shipping and score >= 40:
        score += 5; reasons.append("Frete grátis")

    # Sem nenhuma referência confiável, limita a nota.
    if hist_med is None and peer_med is None and not (watch and watch.floor):
        score = min(score, 75)
        if score:
            reasons.append("Pouca referência de preço (confiança reduzida)")

    score = max(0, min(score, 100))
    if score >= cfg.level_critico:
        level = "CRITICO"
    elif score >= cfg.level_alto:
        level = "ALTO"
    elif score >= cfg.level_medio:
        level = "MEDIO"
    else:
        level = "NENHUM"
    return Verdict(score, level, reasons, ref_price, drop_pct)
