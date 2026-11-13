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
        print("ERRO: faltam os Secrets SHOPEE_APP_ID e SHOPEE_SECRET.
