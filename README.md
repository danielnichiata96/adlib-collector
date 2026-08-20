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

Grava JSONL comprimido e publica em
[`adlib-data`](https://github.com/danielnichiata96/adlib-data) — repositório
**privado**, por chave de implantação.

Este repositório é público porque a quota gratuita de Actions em repositório
privado está esgotada, e correr o cron aqui não custa nada. O código pode ser
público sem perda. A série, não: cada snapshot isolado é dado público que
qualquer pessoa pode ir buscar hoje, mas o histórico contínuo é irrecuperável
depois de a janela de 12 meses passar por cima. Guardá-lo num repositório
público era dar o único ativo que o projeto não consegue voltar a comprar.

## Configurar

Dois Secrets no repositório:

- `META_TOKEN` — token de utilizador da Graph API com acesso ao arquivo.
  Requer confirmação de identidade em `facebook.com/ID`. Expira em ~60 dias.
- `NICHES` — o JSON de configuração das consultas.
- `DATA_DEPLOY_KEY` — chave privada de implantação, com escrita, do repositório
  de dados. É de repositório único: não abre mais nada. Secrets não são
  expostos a workflows de forks, e este só dispara por agenda ou à mão.

## Nota sobre o token

O `ad_snapshot_url` devolvido pela API traz o `access_token` embutido. O coletor
sanitiza antes de gravar — senão a credencial fica espalhada por todo o dataset.
