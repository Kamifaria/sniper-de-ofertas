# Sniper de Ofertas

Caçador de bugs de preço para Windows, pensado para rodar 24 horas. Ele varre o catálogo das lojas, relê os itens caros com frequência, detecta preço fora do normal (erro de vírgula, item de graça, queda brusca) e avisa no painel, com notificação do Windows e no Telegram.

Lojas: **Mercado Livre** (API oficial, precisa de `auth_ml.py`; lê pelo **catálogo**: mais vendidos de cada categoria e todos os vendedores de cada produto, porque a busca de anúncios e a leitura direta de anúncios são bloqueadas para apps comuns) e **81 lojas VTEX**, a **KaBuM** e **5 lojas de maquiagem em Shopify** (Boca Rosa, Mari Maria, Vizzela, Sallve e Dailus), todas por consulta pública, sem login pela busca pública, sem login (lista completa em `sniper/stores.py`):
- **Mercado, farmácia e beleza:** Americanas, Sam's Club, Atacadão, Giassi, Savegnago, Super Nosso, Zona Sul, Pague Menos, Drogaria São Paulo, Drogarias Pacheco, Drogal, Drogaria Venancio, Extrafarma, São João Farmácias, Dermage, Hinode, Jequiti.
- **Eletro e casa:** Brastemp, Consul, Compra Certa, Electrolux, Fast Shop, Motorola, Polishop, Mondial, Arno, Oster, Multilaser, WebContinental, Tok&Stok, Brinox, Oxford Porcelanas, Telhanorte, Obramax, Amoedo, DPaschoal, Cobasi, Ri Happy.
- **Maquiagem (VTEX):** Océane, Dermage, Hinode, Jequiti. A Sephora Brasil responde "410" para acesso externo e fica de fora.
- **Esporte e tênis:** Authentic Feet, Kenner, Asics, Mizuno, Olympikus, Fila, Umbro, Penalty, New Balance, Under Armour, Skechers, Speedo, Crocs, Artwalk, Overboard.
- **Moda, calçados e acessórios:** C&A, Hering, Reserva, Animale, Farm Rio, Bobô, Aramis, Calvin Klein, Levi's, Osklen, Malwee, Morena Rosa, Lupo, Duloren, Valisere, Puket, Dakota, Ferracini, Jorge Bischoff, Piccadilly, Santa Lolla, Usaflex, Chilli Beans, Óticas Diniz, Kipling, Vivara, Monte Carlo.

As lojas novas vêm desligadas: ligue no bloco **Lojas** do painel. Loja ligada sem `[[varrer]]` no config ganha sozinha uma varredura de todas as categorias a cada 60 min. Nas lojas VTEX, item que já aparece a R$ 0,00/0,01 é tratado como preço simbólico (sem alerta); só alerta quando o preço **cai** para isso. **Amazon** pela API oficial de afiliados (Creators API): veja "Ligar a Amazon". Steam, Epic, Nuuvem, Shopee e Shein vêm nas próximas fases.

## Como rodar (Windows)

1. Instale o **Python 3.11+** em python.org e marque **"Add python.exe to PATH"**.
2. Dê dois cliques em **`iniciar.bat`**.
   - Na primeira vez, ele cria o ambiente e instala as dependências (1–2 min).
   - Ele copia `config.exemplo.toml` para `config.toml`.
3. O painel abre em uma janela própria. Sem loja configurada ele fica vazio: siga "Ligar o Mercado Livre de verdade" abaixo.

Outras formas de abrir: `iniciar.bat --navegador` (abre no Chrome/Edge) ou `iniciar.bat --sem-janela` (painel em http://127.0.0.1:8765).

## Ligar o Mercado Livre de verdade

1. Acesse https://developers.mercadolivre.com.br/devcenter e crie um aplicativo.
   - **Redirect URI:** `https://www.google.com` (ou outra URL https que você controle)
   - Escopos: leitura + `offline_access` (é esse escopo que gera o refresh token)
2. No `config.toml`, preencha `[mercadolivre]` com `client_id`, `client_secret` e `redirect_uri`.
3. Abra um terminal na pasta e rode:
   ```
   .venv\Scripts\activate
   python auth_ml.py
   ```
   Autorize no navegador, copie a URL para onde você foi mandado e cole no terminal. O token fica em `data/ml_token.json` e é renovado automaticamente.
4. Confira que o `config.toml` tem `[lojas.mercadolivre]` com `ativo = true` (configs antigos, só com `[mercadolivre]` preenchido, já ligam a loja).

## Ligar a Amazon

A Amazon só libera preços pela **Creators API**, do programa de afiliados (a antiga PA-API 5 foi desligada em maio de 2026). Precisa de conta no Amazon Associados aprovada; guias de afiliados dizem que manter o acesso exige 10 vendas qualificadas em 30 dias.

1. No Associados: **Tools → Creators API → Create Credential**. Use credencial **v3** (as v2 pararam em 11/09/2026).
2. No `config.toml`, preencha:
   ```toml
   [amazon]
   credencial_id = "..."
   credencial_segredo = "..."
   tag_afiliado = "seutag-20"
   ```
   Com a credencial preenchida, a loja Amazon já liga (dá para desligar no painel).
3. Crie regras `[[vigiar]]` com `loja = "amazon"` e `busca` (ou `itens = ["ASIN..."]`). A busca vem do mais barato para o mais caro, a partir do `preco_minimo`, só produto novo, 10 por página.

A Amazon começa liberando 1 consulta por segundo, então não há varredura de catálogo: só as buscas e a fila rápida. Os links dos alertas já saem com a sua tag de afiliado. Marca muito falsificada só alerta se for vendida pela própria Amazon.

## Atualização automática

Ao abrir pelo `iniciar.bat`, se a pasta veio do Git, ele roda `git pull` e reinstala as dependências. O painel também compara a versão com `versao.json` do repositório e avisa quando houver uma nova.

## Bug de preço x promoção

Cada alerta é de um de dois tipos, com etiqueta e filtro próprios no painel:
- **🐞 Bug de preço:** preço fora do normal (de graça, vírgula errada, muito abaixo dos concorrentes ou do histórico). Mostra a causa provável, toca som e vai para o Telegram e o Windows.
- **🏷️ Promoção:** promoção comum da loja, com 40% ou mais de desconto sobre o preço "de". Aparece só no painel, sem som e sem aviso no celular.

O botão **Limpar alertas** apaga a lista; o histórico de preços fica guardado.

## Telegram (alerta no celular)

1. Fale com o **@BotFather**, crie um bot e copie o token.
2. Mande qualquer mensagem para o seu bot e pegue o seu id com o **@userinfobot**.
3. Em `[telegram]`: `ativo = true`, `bot_token`, `chat_id`.

## Regras de vigilância

Cada bloco `[[vigiar]]` no `config.toml` é uma regra:

| campo | o que faz |
|---|---|
| `busca` | termo de busca (ex.: `"iphone 15"`) |
| `categoria` | id de categoria do ML (ex.: `MLB1055`) |
| `itens` | anúncios específicos: `["MLB123..."]` |
| `intervalo` | segundos entre coletas (itens caros: 60–90) |
| `piso` | preço abaixo disso já é suspeito |
| `preco_minimo` | ignora itens que normalmente custam menos (capinhas, cabos) |
| `paginas` | páginas de 50 resultados por busca |

## Varredura e fila rápida

- **`[[varrer]]`** percorre o catálogo da loja em rodízio (no ML, cada categoria final, do mais barato para o mais caro). Se o PC reiniciar, ele continua de onde parou.
- **Fila rápida:** todo item visto nas últimas 48 h com preço ≥ `valor_alto` é relido a cada `intervalo_rapido` segundos.
- **Limite por loja:** cada loja tem um teto de consultas por minuto. Se a loja bloquear (429/403), só ela pausa por 1, 5, 15 e depois 60 min. O painel mostra o motivo.

## Rodar 24 horas

- Enquanto o Sniper está aberto, o Windows não entra em suspensão (o monitor ainda desliga).
- `iniciar.bat --instalar-inicio` faz o Sniper abrir sozinho, minimizado, quando o Windows iniciar. `iniciar.bat --remover-inicio` desfaz.
- Com o Telegram ligado, chega um aviso se uma loja ficar mais de 30 min com problema e um resumo diário às 9h.
- O log fica em `data/sniper.log` (até 5 arquivos de 5 MB).

## Como a nota (0–100) é calculada

| sinal | pontos |
|---|---|
| preço ≤ R$ 1,00 | 100 → **GRÁTIS** |
| queda vs mediana de 30 dias (85% / 70% / 55% / 40% / 25%) | 75 / 62 / 50 / 40 / 15 |
| queda brusca vs última coleta (≥50% / ≥30%) | +20 / +10 |
| abaixo do piso da regra | +20 a +30 |
| vírgula errada: preço é ~1/10 ou ~1/100 do normal (folga de 8%) | +20 |
| frete grátis (quando já há queda forte) | +5 |

O "de/por" anunciado pela loja **não soma pontos**: é marketing. Sem histórico, concorrentes ou piso da regra, só item de graça vira alerta.

Níveis: **CRÍTICO** ≥ 90 · **ALTO** ≥ 70 · **MÉDIO** ≥ 50. O padrão é o modo **"só bugs"** (`nota_minima_alerta = 70`): promoção comum de 40-50% não aparece.

Contra falso alerta:
- **GRÁTIS** (preço ≤ R$ 1,00) só conta se o preço normal era pelo menos R$ 10.
- Nas lojas VTEX o mesmo código de barras aparece na unidade e na caixa, então **não** se compara produtos da mesma loja: a comparação é com o **mesmo código de barras em outras lojas** (EAN válido, único em cada loja, pelo menos 3 outras lojas).
- **Só original em marca muito falsificada:** Gucci, Nike, Adidas, Vans, Apple, Stanley, perfumes importados e outras (lista em `sniper/filters.py`) só alertam se quem vende é **oficial**: no Mercado Livre, loja oficial ou o próprio ML; nas lojas VTEX, a própria loja (não o marketplace). O resto vai para **Descartados** com o motivo. Acrescente marcas em `[filtros] marcas_falsificadas_extras`.
- **Preço de mercado não é bug:** se 2 ou mais concorrentes vendem até 30% acima (ou mais barato), a mediana é que está alta.
- **Preço de sempre não é bug:** abaixo dos concorrentes, mas sempre custou isso nesta loja (ex.: unidade comparada com a caixa).
- Títulos com cara de réplica ("inspired", "primeira linha", "AAA", "espelhado") e gift cards são descartados.
- O mesmo item com o mesmo preço só alerta de novo depois de 24 h (antes, só se cair mais 5%).

## Escolher as lojas e log de bugs

- No painel, bloco **Lojas**: botão **Ligar/Desligar** em cada loja. Vale na hora e fica salvo. Loja ligada ganha uma varredura automática (não precisa de `[[varrer]]`).
- Lista de alertas = log de bugs. Filtre por **Hoje / 24 h / 7 dias** e use **⬇ Exportar CSV** (abre no Excel). Item sem histórico e sem piso fica limitado a 75, porque ainda não dá para confiar.

## Estrutura

```
run.py                 inicia motor + API + janela (--instalar-inicio / --remover-inicio)
auth_ml.py             autorização OAuth do Mercado Livre (uma vez)
sniper/stores.py       registro de lojas (nome, oficial/não oficial, limite)
sniper/engine.py       regras, varredura, fila rápida, saúde das lojas e alertas
sniper/ratelimit.py    limite de consultas por loja e pausa por bloqueio
sniper/detector.py     cálculo da nota
sniper/collectors/     um coletor por plataforma (mercadolivre, vtex, amazon)
sniper/db.py           SQLite: itens, histórico, alertas, estado da varredura
sniper/notify.py       Telegram + notificação do Windows
sniper/server.py       API local (127.0.0.1) + transmissão ao vivo
sniper/winsys.py       sem suspensão e início com o Windows
sniper/web/index.html  painel
tests/                 python -m unittest discover tests
```

## Próximas fases

- **Fase 2:** jogos (Steam, Epic, IsThereAnyDeal com Nuuvem) e comparação de preço entre lojas de jogos.
- **Fase 3:** coletor VTEX genérico (Carrefour, Renner, Leroy Merlin e outras) e comparação por código de barras.
- **Fase 4:** Amazon (feita) e Shopee pelas APIs de afiliados; Shein e Grupo Boticário por arquivo de produtos de redes de afiliados (Awin, Lomadee, CJ).
- Depois: executor assistido de compra e aprendizado de quais lojas cancelam pedido.
