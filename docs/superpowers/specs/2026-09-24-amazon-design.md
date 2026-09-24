# Amazon pela Creators API — desenho

Data: 2026-09-24. Fase 4 do roadmap (só a Amazon; Shopee e Shein ficam para depois).

## Objetivo

Vigiar buscas por termo na Amazon Brasil e alertar bug de preço, com o mesmo motor das outras lojas. Só pela API oficial de afiliados: ler o site direto vai contra as regras da Amazon e põe a conta de afiliada em risco.

## Restrições da Creators API

- A PA-API 5 foi desligada em 15/05/2026. A Creators API a substitui. Credenciais v2.x (Cognito) pararam em 11/09/2026: só v3.x (Login with Amazon).
- Token: `POST https://api.amazon.com/auth/o2/token` (região NA, que inclui o Brasil), `application/x-www-form-urlencoded`, `grant_type=client_credentials`, `scope=creatorsapi::default`, credencial em HTTP Basic. Vale 1 h.
- Chamadas: `POST https://creatorsapi.amazon/catalog/v1/searchItems` e `/getItems`, cabeçalhos `Authorization: Bearer <token>` e `x-marketplace: www.amazon.com.br`, corpo em lowerCamelCase.
- `searchItems`: até 10 itens por página, até 10 páginas; `sortBy = "Price:LowToHigh"`; `minPrice` em centavos; `condition = "New"`.
- `getItems`: até 10 ASINs por chamada.
- Começa com 1 consulta por segundo; cresce com as vendas. Guias de afiliados dizem que manter o acesso exige 10 vendas qualificadas em 30 dias (não confirmado na documentação pública).

## Desenho

**Loja.** `amazon` entra em `sniper/stores.py` como oficial, limite padrão de 50 consultas/minuto. Fica "não configurada" até o `config.toml` ter:

```toml
[amazon]
credencial_id = ""
credencial_segredo = ""
tag_afiliado = "seutag-20"
```

**Regras.** Só `[[vigiar]]` com `loja = "amazon"`: `busca` (searchItems do mais barato para o mais caro, a partir de `preco_minimo`, só novos, `paginas` × 10 itens) ou `itens` (ASINs, via getItems). Sem varredura de catálogo: não há consultas para isso. Itens caros vistos entram na fila rápida normal, relidos de 10 em 10.

**Coletor** (`sniper/collectors/amazon.py`, `AmazonCollector`):
- Token em memória, renovado 60 s antes de vencer e de novo após um 401.
- Espera 1,1 s entre chamadas (o limite por minuto do app deixa sair rajadas, e a Amazon recusaria).
- 429: pausa a loja pelo `RateLimiter` e levanta `CollectorError`. 403: `CollectorError` dizendo para conferir a credencial e o mínimo de vendas. 5xx: tenta de novo com espera crescente.
- Oferta: ASIN como `item_id`; título, marca (`byLineInfo.brand`), EAN (`externalIds`) como `catalog_id` para comparar com as lojas VTEX; preço da listagem vencedora do BuyBox (`offersV2.listings`), preço "de" pelo `savingBasis`; fora de estoque é ignorado; `detailPageURL` já vem com a tag de afiliado.
- `official_seller` = vendido pela própria Amazon (nome do vendedor começa com "Amazon"). Com o filtro de marca falsificada, Nike ou Apple de vendedor de fora não alerta.
- `peers_mesma_loja = False`: a comparação é pelo mesmo EAN em outras lojas.
- Leitura de chaves sem diferenciar maiúsculas (a documentação mistura `EANs`, `eans`).

## Testes

`tests/test_amazon.py` com `httpx.MockTransport`: pedido de token (Basic, escopo), corpo e cabeçalhos da busca, paginação, conversão da oferta (BuyBox, preço "de", EAN, marca, oficial, fora de estoque), releitura em lotes de 10, reconfirmação, 401 renova o token, 429 pausa a loja, 403 com mensagem clara, espera de 1,1 s entre chamadas, config e registro da loja.

Sem credencial real ainda: o teste de ponta a ponta com a Amazon fica para quando a credencial existir.
