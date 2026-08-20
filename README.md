# adlib-collector

Recolha diária do arquivo público de anúncios da Meta, via API oficial.

Existe porque a janela do arquivo é **móvel de 12 meses**: um anúncio desaparece
doze meses depois da última impressão. Quem não capturar hoje não recupera
depois — a série histórica só existe para quem estava a coletar.

Corre em GitHub Actions porque um portátil não é infraestrutura.

## O que faz

Todos os dias, duas populações por consulta:

**Veteranos** — começaram há mais de 180 dias e continuam ativos. Registo
completo. É o conjunto de referência: o que sobreviveu.

**Risers** — entre 7 e 30 dias. Registo compacto: id, pagador, início, alcance e
destino, sem criativo nem segmentação. É o conjunto de descoberta. Com meia-vida
de oferta de 3 a 9 meses, esperar 180 dias para ver uma oferta é encontrá-la
quando a janela já passou. Medido: 16.351 risers em 460 KB, contra ~5,4 MB se
fosse registo completo — 165 MB/ano em vez de ~1,9 GB. E não perde nada de
definitivo: o que sobreviver entra nos veteranos com registo completo, e o que
ainda estiver a correr responde à API por id.

Medir as mesmas populações todos os dias é o que torna o **delta de alcance**
entre snapshots interpretável — alcance acumulado dividido por idade não
distingue quem entrega hoje de quem concentrou tudo há meses.

O corte inferior dos risers é feito pela API (`ad_delivery_date_max = hoje − 7`),
não localmente. Como a API devolve por recência, isso põe a janela pedida nas
primeiras páginas; sem esse truque seriam 40 páginas por nicho para lá chegar, e
o limite é de ~200 chamadas por hora.

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
