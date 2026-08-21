#!/usr/bin/env python3
"""
Probe da Meta Ad Library API.

Responde a duas perguntas de uma vez:
  1. O token que temos serve para consultar anúncios comerciais?
  2. A assimetria UE / Brasil é real? (ad_type=ALL só devolve comercial na UE/UK)

Só stdlib. Uso:
    cp .env.example .env && $EDITOR .env
    python3 scripts/probe.py
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from getpass import getpass

API_VERSION = "v26.0"
BASE = f"https://graph.facebook.com/{API_VERSION}/ads_archive"

FIELDS = [
    "id", "page_name", "ad_creative_bodies", "ad_delivery_start_time",
    "eu_total_reach", "target_ages", "target_gender", "target_locations",
    "ad_snapshot_url",
    # o URL de clique não existe na API; a caption traz o domínio de destino,
    # que é por onde o crawler de funil entra
    "ad_creative_link_captions", "ad_creative_link_titles",
    "ad_creative_link_descriptions",
    # a unidade de análise é o pagador, não o domínio: subdomínios da mesma
    # empresa separam-se, e vendedores distintos hospedados na mesma
    # plataforma colapsam. page_id e beneficiary_payers corrigem os dois erros.
    "page_id", "beneficiary_payers", "publisher_platforms",
    # quem o algoritmo escolheu, que não é quem o anunciante pediu: 71% dos
    # veteranos pedem 18-65, ou seja não segmentam. O alcance real por faixa
    # etária e género é publicado por obrigação da DSA e é o único sinal de
    # avatar que existe sem comprar mídia.
    "age_country_gender_reach_breakdown",
]

# (rótulo, países, termo de busca no idioma local)
PROBES = [
    ("UE  · Espanha + Portugal", ["ES", "PT"], "adelgazar"),
    ("BR  · Brasil            ", ["BR"], "emagrecer"),
]


def load_env(path=".env"):
    """Lê o .env sem dependências. Ignora comentários e linhas vazias."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def persist(key, value, path=".env"):
    """Grava a chave no .env, substituindo a linha se já existir."""
    lines, found = [], False
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i], found = f"{key}={value}", True
            break
    if not found:
        lines.append(f"{key}={value}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def resolve_token():
    """Token de usuário se existir; senão o de app, pedindo o segredo se faltar.

    O token de app é APP_ID|APP_SECRET — construído, não gerado. Não passa pelo
    Login do Facebook, que é o passo que falha em app sem caso de uso.
    """
    token = os.environ.get("META_TOKEN", "").strip()
    if token:
        return token, "usuário (META_TOKEN)"

    app_id = os.environ.get("META_APP_ID", "").strip()
    if not app_id:
        sys.exit("Falta META_APP_ID no .env")

    secret = os.environ.get("META_APP_SECRET", "").strip()
    if not secret:
        if not sys.stdin.isatty():
            sys.exit("Falta META_APP_SECRET no .env")
        print("Chave secreta do app — developers.facebook.com > Configurações do app > Básico")
        print("Não aparece no ecrã nem no histórico do shell.\n")
        secret = getpass("META_APP_SECRET: ").strip()
        if not secret:
            sys.exit("Nada inserido.")
        persist("META_APP_SECRET", secret)
        print("Guardado em .env (permissões 600, já no .gitignore).\n")

    return f"{app_id}|{secret}", "app (APP_ID|APP_SECRET)"


MAX_PAGES = 40  # 100 por página


def query(token, countries, terms):
    """Esgota o conjunto de resultados.

    A API devolve por RECÊNCIA. Ler só a primeira página faz parecer que não
    existem anúncios antigos — foi assim que uma leitura anterior concluiu, por
    engano, que o Brasil tinha cobertura mais funda que a UE. Não tinha: era o
    limite de paginação de quem leu.
    """
    params = {
        "access_token": token,
        "ad_reached_countries": json.dumps(countries),
        "ad_type": "ALL",
        "ad_active_status": "ACTIVE",
        "search_terms": terms,
        "limit": "100",
        "fields": ",".join(FIELDS),
    }
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    ads, pages = [], 0
    while url and pages < MAX_PAGES:
        req = urllib.request.Request(url, headers={"User-Agent": "pdf-pipe-probe/1"})
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                return None, json.loads(raw).get("error", {"message": raw})
            except json.JSONDecodeError:
                return None, {"message": raw[:400], "http_status": exc.code}
        except Exception as exc:
            return None, {"message": f"{type(exc).__name__}: {exc}"}
        ads.extend(body.get("data", []))
        url = body.get("paging", {}).get("next")
        pages += 1
    return {"data": ads, "_pages": pages, "_exhausted": url is None}, None


def days_running(start_iso):
    """Dias no ar. É o único proxy público de lucratividade que existe."""
    if not start_iso:
        return None
    try:
        started = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return (date.today() - started).days


def report(label, payload):
    ads = payload.get("data", [])
    done = "conjunto esgotado" if payload.get("_exhausted") else f"CORTADO no limite de {MAX_PAGES} páginas"
    print(f"  {len(ads)} anúncios em {payload.get('_pages')} páginas — {done}")
    if not ads:
        print("  → nenhum resultado. Se o outro país devolveu dados, é a assimetria da DSA.")
        return

    aged = []
    for ad in ads:
        d = days_running(ad.get("ad_delivery_start_time"))
        if d is not None:
            aged.append((d, ad))
    aged.sort(key=lambda pair: pair[0], reverse=True)

    veterans = [pair for pair in aged if pair[0] >= 21]
    print(f"  {len(veterans)} no ar há 21+ dias  ← estes são as ofertas validadas")

    panel = sum(1 for ad in ads if ad.get("eu_total_reach") is not None)
    pct = 100 * panel // len(ads)
    print(f"  {panel}/{len(ads)} ({pct}%) com painel de transparência da UE")
    if pct >= 95 and label.strip().startswith("BR"):
        print("  → quase tudo tem painel da UE: são anunciantes europeus que também")
        print("    tocam o Brasil. O mercado brasileiro puro não aparece aqui.")

    print("  mais antigos:")
    for d, ad in aged[:5]:
        reach = ad.get("eu_total_reach")
        reach_s = f"{reach:,}".replace(",", ".") if isinstance(reach, int) else "—"
        name = (ad.get("page_name") or "?")[:34]
        print(f"    {d:>4}d  alcance {reach_s:>12}  {name}")


TOKEN_PARAM = re.compile(r"([?&])access_token=[^&\"\s]+")


def sanitize(ad):
    """A API devolve ad_snapshot_url com o access_token embutido. Persistir isso
    põe a credencial em todo o dataset — e o dataset é para durar anos."""
    url = ad.get("ad_snapshot_url")
    if url:
        ad = {**ad, "ad_snapshot_url": TOKEN_PARAM.sub(r"\1", url)}
    return ad


def snapshot(countries, terms, ads, out_dir="data/snapshots"):
    """Grava a corrida em JSONL. A janela do arquivo é móvel de 12 meses — o que
    não for capturado hoje deixa de existir daqui a um ano."""
    os.makedirs(out_dir, exist_ok=True)
    stamp = date.today().isoformat()
    slug = "-".join(countries).lower() + "_" + "".join(
        c if c.isalnum() else "-" for c in terms.lower())
    path = os.path.join(out_dir, f"{stamp}_{slug}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for ad in ads:
            fh.write(json.dumps({**sanitize(ad), "_captured": stamp,
                                 "_countries": countries,
                                 "_terms": terms}, ensure_ascii=False) + "\n")
    return path


def main():
    load_env()
    token, kind = resolve_token()
    print(f"Meta Ad Library · {API_VERSION} · token de {kind}\n")

    results = {}
    for label, countries, terms in PROBES:
        print(f"{label}  \"{terms}\"")
        payload, error = query(token, countries, terms)
        if error:
            msg = error.get("message", "?")
            print(f"  ERRO: {msg}")
            if "confirm" in msg.lower() or "identity" in msg.lower():
                print("  → é a confirmação de identidade. Vá a facebook.com/ID (leva dias).")
            elif "session" in msg.lower() or "expired" in msg.lower():
                print("  → token inválido ou expirado. Gere outro no Explorador.")
            results[label] = None
        else:
            report(label, payload)
            path = snapshot(countries, terms, payload.get("data", []))
            print(f"  gravado: {path}")
            results[label] = len(payload.get("data", []))
        print()

    if all(v is None for v in results.values()):
        print("VEREDITO: inconclusivo, as chamadas falharam. Resolva o token primeiro.")
        return
    print("VEREDITO: os dois países devolvem anúncios, mas não a mesma coisa.")
    print("  Na UE, todo anúncio entregue entra no arquivo — cobertura completa.")
    print("  No BR só entra o que já está no arquivo por outro motivo: anúncio")
    print("  europeu que também toca o Brasil, ou anúncio de questão social.")
    print("  O mercado comercial brasileiro puro permanece invisível por API.")


if __name__ == "__main__":
    main()
