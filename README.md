# adlib-collector

Recolha diária do arquivo público de anúncios da Meta, via API oficial.

Existe porque a janela do arquivo é **móvel de 12 meses**: um anúncio desaparece
doze meses depois da última impressão. Quem não capturar hoje não recupera
depois — a série histórica só existe para quem estava a coletar.

Corre em GitHub Actions porque um portátil não é infraestrutura.

## O que faz

Todos os dias pede os anúncios que começaram há mais de 180 dias e continuam
ativos, para um conjunto de consultas. Medir a mesma população todos os dias é o
que torna o **delta de alcance** entre snapshots interpretável — alcance
acumulado dividido por idade não distingue quem entrega hoje de quem concentrou
tudo há meses.

Grava JSONL comprimido em `data/snapshots/`.

## Configurar

Dois Secrets no repositório:

- `META_TOKEN` — token de utilizador da Graph API com acesso ao arquivo.
  Requer confirmação de identidade em `facebook.com/ID`. Expira em ~60 dias.
- `NICHES` — o JSON de configuração das consultas.

## Nota sobre o token

O `ad_snapshot_url` devolvido pela API traz o `access_token` embutido. O coletor
sanitiza antes de gravar — senão a credencial fica espalhada por todo o dataset.
