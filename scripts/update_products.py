#!/usr/bin/env python3
"""Atualiza o products.json do Radar Black Friday.

Junta os produtos escolhidos à mão (manual.json) com ofertas da API
da Shopee (termos em buscas.json). A parte da API fica em shopee_api.py.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from shopee_api import ApiError, FIELDS, ORDEM_PADRAO, buscar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))

# Desconto mínimo (%) para entrar. Dá para mudar com "min_desconto"
# no buscas.json.
MIN_DESCONTO_PADRAO = 20

# Produtos com estas palavras no nome são descartados. Dá para somar
# outras palavras com "bloquear" no buscas.json.
BLOQUEADAS_PADRAO = ["airpods", "airpod", "apple", "iphone"]


def ler_json(nome, padrao):
    caminho = os.path.join(ROOT, nome)
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def numero(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


def limpar(nome):
    return re.sub(r"\s+", " ", str(nome or "")).strip()[:120]


def escolher(nos, cat, cfg, hoje):
    """Filtra e escolhe os de maior desconto (empate: mais vendas)."""
    divisor = numero(cfg.get("preco_divisor")) or 1
    teto = numero(cfg.get("preco_max"))
    minimo_desc = numero(cfg.get("min_desconto"))
    if minimo_desc is None:
        minimo_desc = MIN_DESCONTO_PADRAO
    extras = cfg.get("bloquear") or []
    bloqueadas = [str(x).lower() for x in BLOQUEADAS_PADRAO + list(extras)]
    itens = []
    for n in nos:
        nome = limpar(n.get("productName"))
        preco = numero(n.get("price")) or numero(n.get("priceMin"))
        link = str(n.get("offerLink") or "")
        img = str(n.get("imageUrl") or "")
        if not nome or not preco or preco <= 0:
            continue
        if not link.startswith("https://"):
            continue
        minusculo = nome.lower()
        if any(p in minusculo for p in bloqueadas):
            continue
        preco_final = round(preco / divisor, 2)
        if teto and preco_final > teto:
            continue
        vendas = numero(n.get("sales"))
        nota = numero(n.get("ratingStar"))
        if vendas is not None and vendas < cfg.get("min_vendas", 0):
            continue
        if nota and nota < cfg.get("min_nota", 0):
            continue
        desc = numero(n.get("priceDiscountRate")) or 0
        if desc < minimo_desc:
            continue
        prod = {
            "nome": nome,
            "loja": "Shopee",
            "cat": cat,
            "preco": preco_final,
            "antes": None,
            "visto": hoje,
            "link": link,
            "imagem": img if img.startswith("https://") else "",
            "exemplo": False,
            "auto": True,
            "desconto": int(round(desc)),
        }
        itens.append((desc, vendas or 0, nota or 0, prod))
    itens.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    quantos = int(cfg.get("por_busca", 4))
    return [t[3] for t in itens[:quantos]]


def main():
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_SECRET", "").strip()
    if not app_id or not secret:
        print("ERRO: faltam os Secrets SHOPEE_APP_ID e SHOPEE_SECRET.")
        return 1

    cfg = ler_json("buscas.json", {})
    buscas = cfg.get("buscas") or []
    manual = []
    for p in ler_json("manual.json", []):
        if isinstance(p, dict) and not p.get("exemplo"):
            manual.append(p)
    hoje = datetime.now(BRT).strftime("%d/%m")
    print("Produtos manuais: %d | buscas: %d" % (len(manual), len(buscas)))

    estado = {"campos": list(FIELDS)}
    autos = []
    ok = 0
    falhas = 0
    mostrou = False
    for i, b in enumerate(buscas):
        termo = b.get("termo")
        cat = b.get("cat", "Outros")
        if not termo:
            continue
        if i > 0:
            time.sleep(1.5)
        ordem = b.get("ordem", cfg.get("ordem", ORDEM_PADRAO))
        limite = int(cfg.get("busca_limite", 30))
        try:
            nos = buscar(app_id, secret, termo, limite, ordem, estado)
        except ApiError as e:
            falhas += 1
            print("FALHOU '%s': %s" % (termo, e))
            if "Autenticação" in str(e):
                break
            continue
        ok += 1
        if nos and not mostrou:
            exemplo = json.dumps(nos[0], ensure_ascii=False)[:700]
            print("Exemplo do que a API devolveu (primeiro item):")
            print(exemplo)
            mostrou = True
        cfg_busca = dict(cfg)
        for chave in ("preco_max", "min_desconto"):
            if b.get(chave) is not None:
                cfg_busca[chave] = b[chave]
        escolhidos = escolher(nos, cat, cfg_busca, hoje)
        linha = "'%s': %d resultados, " % (termo, len(nos))
        linha += "%d escolhidos" % len(escolhidos)
        print(linha)
        autos.extend(escolhidos)

    if buscas and ok == 0:
        print("ERRO: nenhuma busca funcionou. products.json NÃO alterado.")
        return 1

    vistos = set()
    for p in manual:
        vistos.add(p.get("link"))
        vistos.add(str(p.get("nome", "")).lower())
    produtos = list(manual)
    for p in autos:
        if p["link"] in vistos or p["nome"].lower() in vistos:
            continue
        vistos.add(p["link"])
        vistos.add(p["nome"].lower())
        produtos.append(p)

    if not produtos:
        print("ERRO: lista vazia. products.json NÃO alterado.")
        return 1

    atual = ler_json("products.json", {})
    if atual.get("produtos") == produtos:
        print("Sem mudanças nos produtos (%d)." % len(produtos))
        return 0
    agora = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
    saida = {"atualizado_em": agora, "produtos": produtos}
    caminho = os.path.join(ROOT, "products.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
        f.write("\n")
    da_api = len(produtos) - len(manual)
    msg = "products.json atualizado: %d produtos" % len(produtos)
    msg += " (%d manuais, %d da API)." % (len(manual), da_api)
    msg += " Buscas com falha: %d." % falhas
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
