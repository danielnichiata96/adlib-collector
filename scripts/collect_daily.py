#!/usr/bin/env python3
"""Recolha diária dos veteranos, para correr sem supervisão.

Grava comprimido, sanitiza o token, e sai com código de erro se alguma coisa
falhar — o valor do dataset é a continuidade, e uma falha silenciosa custa
dias que não voltam.

Mede-se aqui a mesma população todos os dias (anúncios com 180+ dias ainda
ativos) para que o delta de alcance entre snapshots signifique alguma coisa.
"""

import gzip
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import FIELDS, load_env, resolve_token, sanitize  # noqa: E402

OUT_DIR = "data/snapshots"
MAX_PAGES = 20


def slug(countries, terms):
    return "-".join(c.lower() for c in countries) + "_" + "".join(
        c if c.isalnum() else "-" for c in terms.lower())


def fetch(token, countries, terms, cut):
    params = {
        "access_token": token, "ad_reached_countries": json.dumps(countries),
        "ad_type": "ALL", "ad_active_status": "ACTIVE", "search_terms": terms,
        "limit": "100", "ad_delivery_date_max": cut, "fields": ",".join(FIELDS),
    }
    url = f"https://graph.facebook.com/v26.0/ads_archive?{urllib.parse.urlencode(params)}"
    ads, pages, err = [], 0, None
    while url and pages < MAX_PAGES:
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read().decode())["error"]["message"]
            except Exception:
                err = f"HTTP {exc.code}"
            break
        except Exception as exc:
            err = type(exc).__name__
            break
        ads.extend(body.get("data", []))
        url = body.get("paging", {}).get("next")
        pages += 1
    return ads, pages, err


def main():
    load_env()
    cfg = json.load(open("niches.json", encoding="utf-8"))
    token, kind = resolve_token()
    cut = (date.today() - timedelta(days=cfg["veteran_days"])).isoformat()
    stamp = date.today().isoformat()
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"{stamp} · token de {kind} · veteranos anteriores a {cut}\n")
    total, failures, empty = 0, [], []

    for q in cfg["queries"]:
        countries, terms = q["countries"], q["terms"]
        ads, pages, err = fetch(token, countries, terms, cut)
        name = slug(countries, terms)
        if err and not ads:
            print(f"  FALHA  {terms[:30]:<30} {err[:44]}")
            failures.append(terms)
            continue
        if not ads:
            print(f"  vazio  {terms[:30]:<30}")
            empty.append(terms)
            continue

        path = os.path.join(OUT_DIR, f"{stamp}_{name}.jsonl.gz")
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            for ad in ads:
                fh.write(json.dumps({**sanitize(ad), "_captured": stamp,
                                     "_countries": countries, "_terms": terms},
                                    ensure_ascii=False) + "\n")
        size = os.path.getsize(path) // 1024
        note = f"  ⚠ cortado em {MAX_PAGES} páginas" if pages >= MAX_PAGES else ""
        print(f"  ok     {terms[:30]:<30} {len(ads):>4} anúncios · {size:>4} KB{note}")
        total += len(ads)

    print(f"\ntotal: {total} anúncios em {len(cfg['queries']) - len(failures)} consultas")

    if failures:
        print(f"FALHOU em: {', '.join(failures)}")
        sys.exit(1)
    if total == 0:
        print("FALHOU: zero anúncios recolhidos — token ou API")
        sys.exit(1)


if __name__ == "__main__":
    main()
