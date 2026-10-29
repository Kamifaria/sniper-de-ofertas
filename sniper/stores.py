"""Registro de lojas: nome, etiqueta oficial/não oficial, limite padrão e como criar o coletor.

Para ligar uma loja nova: escreva o coletor em sniper/collectors/ e acrescente uma LojaInfo em LOJAS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .collectors import AmazonCollector, Collector, KabumCollector, MercadoLivreCollector, VtexCollector
from .config import Settings
from .ratelimit import RateLimiter


@dataclass
class LojaInfo:
    chave: str
    nome: str
    oficial: bool                                                   # API oficial (True) ou endpoint público (False)
    criar: Callable[[Settings, RateLimiter], Optional[Collector]]   # None = falta credencial
    por_minuto: int                                                 # limite padrão de consultas
    motivo_sem_config: str = ""                                     # mostrado quando criar() devolve None


def _mercadolivre(s: Settings, lim: RateLimiter) -> Optional[Collector]:
    if not s.ml_client_id:
        return None
    arq = s.base_dir / "data" / "ml_token.json"
    # instalação antiga (token em arquivo) segue como está; instalação nova usa o cofre do Windows
    return MercadoLivreCollector(s.ml_client_id, s.ml_client_secret, arq, limiter=lim, cofre=not arq.exists())


def _amazon(s: Settings, lim: RateLimiter) -> Optional[Collector]:
    if not (s.amazon_id and s.amazon_secret and s.amazon_tag):
        return None
    return AmazonCollector(s.amazon_id, s.amazon_secret, s.amazon_tag, limiter=lim)


def _kabum(s: Settings, lim: RateLimiter) -> Optional[Collector]:
    return KabumCollector(limiter=lim)


def _vtex(chave: str, dominio: str) -> Callable[[Settings, RateLimiter], Optional[Collector]]:
    return lambda s, lim: VtexCollector(chave, dominio, limiter=lim)


# Lojas VTEX cuja busca pública respondeu sem login: árvore de categorias, busca por categoria e
# releitura por SKU (conferido em 2026-09-23 e 2026-09-24). Use o domínio da API, não o do redirecionamento.
# Fora: Carrefour, Netshoes, Petlove, Assaí etc. bloqueiam (403); Britânia e Philco têm categorias vazias;
# Rommanel mostra tudo indisponível; PBKids é espelho da Ri Happy (mesmos SKUs); Nike, Adidas, Puma,
# Renner, Magalu, Casas Bahia, Boticário etc. não são VTEX; Imaginarium, Makro, Drogaria Araujo e outras
# têm certificado incompleto e falham na conexão.
VTEX = [
    ("cea", "C&A", "www.cea.com.br"),
    ("tokstok", "Tok&Stok", "www.tokstok.com.br"),
    ("cobasi", "Cobasi", "www.cobasi.com.br"),
    ("paguemenos", "Pague Menos", "www.paguemenos.com.br"),
    ("americanas", "Americanas", "www.americanas.com.br"),
    ("telhanorte", "Telhanorte", "www.telhanorte.com.br"),
    ("samsclub", "Sam's Club", "www.samsclub.com.br"),
    ("drogariasaopaulo", "Drogaria São Paulo", "www.drogariasaopaulo.com.br"),
    ("pacheco", "Drogarias Pacheco", "www.drogariaspacheco.com.br"),
    ("atacadao", "Atacadão", "www.atacadao.com.br"),
    # Eletro, eletrônicos e casa
    ("brastemp", "Brastemp", "www.brastemp.com.br"),
    ("consul", "Consul", "www.consul.com.br"),  # divide parte dos SKUs com a Brastemp (Whirlpool)
    ("compracerta", "Compra Certa", "www.compracerta.com.br"),
    ("electrolux", "Electrolux", "loja.electrolux.com.br"),
    ("fastshop", "Fast Shop", "site.fastshop.com.br"),
    ("motorola", "Motorola", "www.motorola.com.br"),
    ("polishop", "Polishop", "www.polishop.com.br"),
    ("mondial", "Mondial", "www.mondial.com.br"),
    ("arno", "Arno", "www.arno.com.br"),
    ("oster", "Oster", "www.oster.com.br"),
    ("multilaser", "Multilaser", "www.multilaser.com.br"),
    ("webcontinental", "WebContinental", "www.webcontinental.com.br"),
    ("brinox", "Brinox", "www.brinox.com.br"),
    ("oxford", "Oxford Porcelanas", "www.oxfordporcelanas.com.br"),
    ("obramax", "Obramax", "www.obramax.com.br"),
    ("amoedo", "Amoedo", "www.amoedo.com.br"),
    ("dpaschoal", "DPaschoal", "www.dpaschoal.com.br"),
    # Esporte
    ("asics", "Asics", "www.asics.com.br"),
    ("mizuno", "Mizuno", "www.mizuno.com.br"),
    ("olympikus", "Olympikus", "www.olympikus.com.br"),
    ("fila", "Fila", "www.fila.com.br"),
    ("umbro", "Umbro", "www.umbro.com.br"),
    ("penalty", "Penalty", "www.penalty.com.br"),
    ("newbalance", "New Balance", "www.newbalance.com.br"),
    ("underarmour", "Under Armour", "www.underarmour.com.br"),
    ("skechers", "Skechers", "www.skechers.com.br"),
    ("speedo", "Speedo", "www.speedo.com.br"),
    ("crocs", "Crocs", "www.crocs.com.br"),
    ("artwalk", "Artwalk", "www.artwalk.com.br"),
    ("authenticfeet", "Authentic Feet", "www.authenticfeet.com.br"),
    ("kenner", "Kenner", "www.kenner.com.br"),
    ("overboard", "Overboard", "www.overboard.com.br"),
    # Moda e calçados
    ("hering", "Hering", "www.hering.com.br"),
    ("reserva", "Reserva", "www.usereserva.com"),
    ("animale", "Animale", "www.animale.com.br"),
    ("farmrio", "Farm Rio", "www.farmrio.com.br"),
    ("bobo", "Bobô", "www.bobo.com.br"),
    ("aramis", "Aramis", "www.aramis.com.br"),
    ("calvinklein", "Calvin Klein", "www.calvinklein.com.br"),
    ("levis", "Levi's", "www.levi.com.br"),
    ("osklen", "Osklen", "www.osklen.com.br"),
    ("malwee", "Malwee", "www.malwee.com.br"),
    ("morenarosa", "Morena Rosa", "www.morenarosa.com.br"),
    ("lupo", "Lupo", "www.lupo.com.br"),
    ("duloren", "Duloren", "www.duloren.com.br"),
    ("valisere", "Valisere", "www.valisere.com.br"),
    ("puket", "Puket", "www.puket.com.br"),
    ("dakota", "Dakota", "www.dakota.com.br"),
    ("ferracini", "Ferracini", "www.ferracini.com.br"),
    ("jorgebischoff", "Jorge Bischoff", "www.jorgebischoff.com.br"),
    ("piccadilly", "Piccadilly", "www.piccadilly.com.br"),
    ("santalolla", "Santa Lolla", "www.santalolla.com.br"),
    ("usaflex", "Usaflex", "www.usaflex.com.br"),
    # Acessórios, joias e óculos
    ("chillibeans", "Chilli Beans", "loja.chillibeans.com.br"),
    ("oticasdiniz", "Óticas Diniz", "www.oticasdiniz.com.br"),
    ("kipling", "Kipling", "www.kipling.com.br"),
    ("vivara", "Vivara", "www.vivara.com.br"),
    ("montecarlo", "Monte Carlo", "www.montecarlo.com.br"),
    # Beleza e farmácia
    ("dermage", "Dermage", "www.dermage.com.br"),
    ("hinode", "Hinode", "www.hinode.com.br"),
    ("jequiti", "Jequiti", "www.jequiti.com.br"),
    ("drogal", "Drogal", "www.drogal.com.br"),
    ("venancio", "Drogaria Venancio", "www.drogariavenancio.com.br"),
    ("extrafarma", "Extrafarma", "www.extrafarma.com.br"),
    ("saojoao", "São João Farmácias", "www.saojoaofarmacias.com.br"),
    # Mercado e brinquedos
    ("giassi", "Giassi", "www.giassi.com.br"),
    ("savegnago", "Savegnago", "www.savegnago.com.br"),
    ("supernosso", "Super Nosso", "www.supernosso.com"),
    ("zonasul", "Zona Sul", "www.zonasul.com.br"),
    ("rihappy", "Ri Happy", "www.rihappy.com.br"),
]

LOJAS: dict[str, LojaInfo] = {i.chave: i for i in [
    LojaInfo("mercadolivre", "ML", True, _mercadolivre, 60,
             "Clique em \"Conectar ML\" no painel e cadastre a sua conta de desenvolvedor"),
    LojaInfo("amazon", "Amazon", True, _amazon, 50,
             "Preencha [amazon] no config.toml: credencial da Creators API e tag de afiliado"),
    LojaInfo("kabum", "KaBuM", False, _kabum, 30),
    *(LojaInfo(chave, nome, False, _vtex(chave, dominio), 30) for chave, nome, dominio in VTEX),
]}
