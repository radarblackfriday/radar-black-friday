#!/usr/bin/env python3
"""Atualiza o products.json do Radar Black Friday.

Junta os produtos escolhidos à mão (manual.json) com ofertas buscadas
na API de afiliados da Shopee (termos em buscas.json). As chaves vêm
dos Secrets do GitHub e nunca são impressas.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = os.environ.get(
    "SHOPEE_API_URL",
    "https://open-api.affiliate.shopee.com.br/graphql",
)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))

# Campos que a busca precisa. Os opcionais saem sozinhos se a API recusar.
REQUIRED = ["productName", "price", "imageUrl", "offerLink"]
OPTIONAL = [
    "priceMin", "priceMax", "shopName",
    "sales", "ratingStar", "priceDiscountRate",
]
FIELDS = list(REQUIRED) + list(OPTIONAL)

# sortType: 1 relevância, 2 mais vendidos, 3 maior preço,
# 4 menor preço, 5 maior comissão
ORDEM_PADRAO = 2

# Desconto mínimo (%) para entrar. Dá para mudar com "min_desconto"
# no buscas.json.
MIN_DESCONTO_PADRAO = 20


class ApiError(Exception):
    pass


def ler_json(nome, padrao):
    caminho = os.path.join(ROOT, nome)
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def chamar(app_id, secret, query):
    """Chamada assinada: SHA256(AppId + Timestamp + Payload + Secret)."""
    payload = json.dumps(
        {"query": query}, ensure_ascii=False, separators=(",", ":")
    )
    dados = {}
    for tentativa in range(3):
        ts = str(int(time.time()))
        texto = app_id + ts + payload + secret
        assinatura = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        auth = "SHA256 Credential=%s, " % app_id
        auth += "Timestamp=%s, " % ts
        auth += "Signature=%s" % assinatura
        req = urllib.request.Request(
            API_URL,
            data=payload.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": auth,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                corpo = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")
        except urllib.error.URLError as e:
            raise ApiError("Sem conexão com a API: %s" % e.reason)
        try:
            dados = json.loads(corpo)
        except ValueError:
            raise ApiError("Resposta que não é JSON: %s" % corpo[:200])
        erros = dados.get("errors") if isinstance(dados, dict) else None
        limite = erros and "10030" in json.dumps(erros)
        if limite and tentativa < 2:
            time.sleep(3 * (tentativa + 1))
            continue
        return dados
    return dados


def texto_erros(dados):
    erros = dados.get("errors") or []
    junto = " | ".join(str(e.get("message", e)) for e in erros)
    return junto[:400]


def montar_query(termo, campos, limite, ordem):
    args = "keyword: %s, " % json.dumps(termo, ensure_ascii=False)
    args += "page: 1, limit: %d" % limite
    if ordem:
        args += ", sortType: %d" % int(ordem)
    lista = " ".join(campos)
    return "{ productOfferV2(%s) { nodes { %s } } }" % (args, lista)


def buscar(app_id, secret, termo, limite, ordem, estado):
    """Busca um termo. Tira campos recusados e repete se der System Error."""
    campos = list(estado["campos"])
    erros_10000 = 0
    for _ in range(14):
        query = montar_query(termo, campos, limite, ordem)
        dados = chamar(app_id, secret, query)
        if not dados.get("errors"):
            data = dados.get("data") or {}
            bloco = data.get("productOfferV2") or {}
            return bloco.get("nodes") or []
        msg = texto_erros(dados)
        padrao_auth = r"signature|credential|unauthori|forbidden|invalid app|auth"
        if re.search(padrao_auth, msg, re.I):
            raise ApiError("Autenticação recusada: %s" % msg)
        ruins = []
        for c in campos:
            if c in REQUIRED:
                continue
            if re.search(r"\b%s\b" % c, msg):
                ruins.append(c)
        if ruins:
            print("  campo(s) não aceito(s), removendo: " + ", ".join(ruins))
            campos = [c for c in campos if c not in ruins]
            estado["campos"] = [c for c in estado["campos"] if c not in ruins]
            continue
        if "10000" in msg or "system error" in msg.lower():
            erros_10000 += 1
            if erros_10000 == 1:
                print("  Shopee respondeu System Error. Esperando 4s.")
                time.sleep(4)
            elif erros_10000 == 2 and ordem:
                print("  Ainda com erro. Tentando sem ordenação.")
                ordem = None
            elif erros_10000 <= 3 and campos != REQUIRED:
                print("  Ainda com erro. Tentando só com campos básicos.")
                campos = list(REQUIRED)
            else:
                raise ApiError(msg)
            continue
        raise ApiError(msg)
    raise ApiError("Não consegui montar uma busca aceita pela API")


def numero(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except (ValueError, TypeError):
        return No
