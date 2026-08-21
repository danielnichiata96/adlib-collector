#!/usr/bin/env python3
"""Recolha diária, para correr sem supervisão.

Grava comprimido, sanitiza o token, e sai com código de erro se alguma coisa
falhar — o valor do dataset é a continuidade, e uma falha silenciosa custa dias
que não voltam.

Duas populações, por razões diferentes:

  VETERANOS   180+ dias e ainda ativos, registo completo. É o conjunto de
              referência: o que sobreviveu. Serve para responder "que tipo de
              oferta aguenta", e o delta de alcance diz quais ainda entregam.

  RISERS      7 a 30 dias. É o conjunto de descoberta. Com meia-vida de oferta
              estimada em 3 a 9 meses, esperar 180 dias para ver uma oferta é
              descobri-la quando a maior parte da janela já passou. O que se
              procura é o padrão dos risers que se parece com o que os veteranos
              tinham meses antes.

O corte inferior dos risers é feito pela API, não localmente:
`ad_delivery_date_max = hoje − 7` exclui no servidor tudo o que começou esta
semana. Como a API devolve por recência, as primeiras páginas passam a ser
exatamente a janela pedida — sem isto seriam precisas 40 páginas por nicho para
lá chegar, e o limite é de ~200 chamadas por hora.

Riser guarda **registo compacto**: id, pagador, início, alcance e destino. Sem
criativo, sem segmentação. Medido na primeira recolha real: 16.351 risers em
460 KB, contra ~5,4 MB no registo completo — 165 MB/ano em vez de ~1,9 GB. E não
se perde nada de definitivo: o que sobreviver entra no conjunto de veteranos,
onde o registo é completo, e o que ainda estiver a correr responde à API por id.
"""

import gzip
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import FIELDS, load_env, resolve_token, sanitize  # noqa: E402

OUT_DIR = "data/snapshots"
MAX_PAGES = 20          # veteranos: o conjunto é pequeno
MAX_RISER_PAGES = 35    # risers: 3.500 anúncios por nicho e por dia
                        # medido: oposiciones esgota em 24, aprender-inglés em ~22

RISER_FIELDS = [
    "id", "page_id", "page_name", "beneficiary_payers",
    "ad_delivery_start_time", "eu_total_reach",
    "ad_creative_link_captions", "publisher_platforms",
]


def slug(countries, terms):
    return "-".join(c.lower() for c in countries) + "_" + "".join(
        c if c.isalnum() else "-" for c in terms.lower())


def age(ad, hoje):
    t = ad.get("ad_delivery_start_time")
    if not t:
        return None
    try:
        return (hoje - datetime.fromisoformat(t.replace("Z", "+00:00")).date()).days
    except ValueError:
        return None


def call(url):
    try:
        with urllib.request.urlopen(url, timeout=90) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        try:
            return None, json.loads(exc.read().decode())["error"]["message"]
        except Exception:
            return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, type(exc).__name__


def url_for(token, countries, terms, fields, **extra):
    params = {
        "access_token": token, "ad_reached_countries": json.dumps(countries),
        "ad_type": "ALL", "ad_active_status": "ACTIVE", "search_terms": terms,
        "limit": "100", "fields": ",".join(fields), **extra,
    }
    return f"https://graph.facebook.com/v26.0/ads_archive?{urllib.parse.urlencode(params)}"


def fetch(token, countries, terms, cut):
    """Veteranos: tudo o que começou antes do corte e continua ativo."""
    url = url_for(token, countries, terms, FIELDS, ad_delivery_date_max=cut)
    ads, pages, err = [], 0, None
    while url and pages < MAX_PAGES:
        body, err = call(url)
        if err:
            break
        ads.extend(body.get("data", []))
        url = body.get("paging", {}).get("next")
        pages += 1
    return ads, pages, err


def fetch_risers(token, countries, terms, min_days, max_days, hoje):
    """Risers: o corte novo vem da API, o corte velho da paginação.

    Para de paginar quando duas páginas seguidas saem inteiras da janela. Duas,
    não uma: a ordenação por recência é medida, não documentada, e uma página
    fora de ordem não pode cortar a recolha do resto do nicho.
    """
    cut = (hoje - timedelta(days=min_days)).isoformat()
    url = url_for(token, countries, terms, RISER_FIELDS, ad_delivery_date_max=cut)
    ads, pages, err, fora = [], 0, None, 0
    while url and pages < MAX_RISER_PAGES:
        body, err = call(url)
        if err:
            break
        page = body.get("data", [])
        idades = [i for i in (age(a, hoje) for a in page) if i is not None]
        ads.extend(a for a in page
                   if (i := age(a, hoje)) is not None and min_days <= i <= max_days)
        pages += 1
        if idades and min(idades) > max_days:
            fora += 1
            if fora >= 2:
                break
        else:
            fora = 0
        url = body.get("paging", {}).get("next")
    return ads, pages, err


def write(path, ads, stamp, countries, terms, window, compact=False):
    # A hora importa: o delta de alcance divide-se pelo tempo real entre
    # capturas. Sem ela, duas recolhas separadas por nove horas mas em dias
    # diferentes dão uma velocidade 2,6× menor que a real.
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for ad in ads:
            rec = {k: ad[k] for k in RISER_FIELDS if k in ad} if compact else sanitize(ad)
            fh.write(json.dumps({**rec, "_captured": stamp, "_captured_at": agora,
                                 "_countries": countries, "_terms": terms,
                                 "_window": window}, ensure_ascii=False) + "\n")
    return os.path.getsize(path) // 1024


def main():
    load_env()
    cfg = json.load(open("niches.json", encoding="utf-8"))
    token, kind = resolve_token()
    hoje = date.today()
    stamp = hoje.isoformat()
    cut = (hoje - timedelta(days=cfg["veteran_days"])).isoformat()
    risers = cfg.get("risers")
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"{stamp} · token de {kind} · veteranos anteriores a {cut}")
    if risers:
        print(f"           risers entre {risers['min_days']} e {risers['max_days']} dias")
    print()
    total, total_r, failures = 0, 0, []

    for q in cfg["queries"]:
        countries, terms = q["countries"], q["terms"]
        name = slug(countries, terms)
        ads, pages, err = fetch(token, countries, terms, cut)
        if err and not ads:
            print(f"  FALHA  {terms[:28]:<28} veteranos: {err[:40]}")
            failures.append(terms)
        elif not ads:
            print(f"  vazio  {terms[:28]:<28} veteranos")
        else:
            kb = write(os.path.join(OUT_DIR, f"{stamp}_{name}.jsonl.gz"),
                       ads, stamp, countries, terms, "veterans")
            note = f"  ⚠ cortado em {MAX_PAGES} páginas" if pages >= MAX_PAGES else ""
            print(f"  ok     {terms[:28]:<28} vet {len(ads):>5} · {kb:>4} KB{note}")
            total += len(ads)

        if not risers:
            continue
        rads, rpages, rerr = fetch_risers(token, countries, terms,
                                          risers["min_days"], risers["max_days"], hoje)
        if rerr and not rads:
            print(f"  FALHA  {terms[:28]:<28} risers: {rerr[:43]}")
            failures.append(f"{terms} (risers)")
        elif not rads:
            print(f"  vazio  {terms[:28]:<28} risers")
        else:
            kb = write(os.path.join(OUT_DIR, f"{stamp}_{name}-risers.jsonl.gz"),
                       rads, stamp, countries, terms, "risers", compact=True)
            note = f"  ⚠ cortado em {MAX_RISER_PAGES} páginas" if rpages >= MAX_RISER_PAGES else ""
            print(f"  ok     {terms[:28]:<28} ris {len(rads):>5} · {kb:>4} KB{note}")
            total_r += len(rads)

    print(f"\ntotal: {total} veteranos · {total_r} risers "
          f"em {len(cfg['queries'])} consultas")

    if failures:
        print(f"FALHOU em: {', '.join(failures)}")
        sys.exit(1)
    if total == 0:
        print("FALHOU: zero veteranos recolhidos — token ou API")
        sys.exit(1)


if __name__ == "__main__":
    main()
