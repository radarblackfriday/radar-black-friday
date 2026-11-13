#!/usr/bin/env python3
"""Atualiza o products.json do Radar Black Friday.

Junta os produtos escolhidos à mão (manual.json) com ofertas buscadas na API
de afiliados da Shopee (termos em buscas.json). As chaves vêm dos Secrets do
GitHub (SHOPEE_APP_ID e SHOPEE_SECRET) e nunca são impressas.
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

API_URL = os.environ.get("SHOPEE_API_URL", "https://open-api.affiliate.shopee.com.br/graphql")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))

# Campos que a busca precisa. Os opcionais são removidos sozinhos se a API reclamar deles.
REQUIRED = ["productName", "price", "imageUrl", "offerLink"]
OPTIONAL = ["priceMin", "priceMax", "shopName", "sales", "soldCount", "ratingStar", "priceDiscountRate"]
FIELDS = list(REQUIRED) + list(OPTIONAL)


class ApiError(Exception):
    pass


def ler_json(nome, padrao):
    caminho = os.path.join(ROOT, nome)
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def chamar(app_id, secret, query):
    """Faz uma chamada assinada. Assinatura = SHA256(AppId + Timestamp + Payload + Secret)."""
    payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    for tentativa in range(3):
        ts = str(int(time.time()))
        assinatura = hashlib.sha256((app_id + ts + payload + secret).encode("utf-8")).hexdigest()
        req = urllib.request.Request(
            API_URL,
            data=payload.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "SHA256 Credential=%s, Timestamp=%s, Signature=%s" % (app_id, ts, assinatura),
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
        if erros and "10030" in json.dumps(erros) and tentativa < 2:  # limite de requisições
            time.sleep(3 * (tentativa + 1))
            continue
        return dados
    return dados


def texto_erros(dados):
    erros = dados.get("errors") or []
    return " | ".join(str(e.get("message", e)) for e in erros)[:400]


def montar_query(termo, campos, limite, ordem):
    args = "keyword: %s, page: 1, limit: %d" % (json.dumps(termo, ensure_ascii=False), limite)
    if ordem:
        args += ", sortType: %d" % int(ordem)
    return "{ productOfferV2(%s) { nodes { %s } } }" % (args, " ".join(campos))


def buscar(app_id, secret, termo, limite, ordem, estado):
    """Busca um termo; se a API reclamar de um campo opcional, remove e tenta de novo."""
    for _ in range(len(OPTIONAL) + 3):
        dados = chamar(app_id, secret, montar_query(termo, estado["campos"], limite, ordem))
        if dados.get("errors"):
            msg = texto_erros(dados)
            if re.search(r"signature|credential|unauthori|forbidden|invalid app|auth", msg, re.I):
                raise ApiError("Autenticação recusada: %s" % msg)
            ruins = [c for c in estado["campos"] if c not in REQUIRED and re.search(r"\b%s\b" % c, msg)]
            if ruins:
                print("  campo(s) não aceito(s), removendo: %s" % ", ".join(ruins))
                estado["campos"] = [c for c in estado["campos"] if c not in ruins]
                continue
            if estado["campos"] != REQUIRED:
                print("  erro na busca (%s). Tentando só com os campos básicos." % msg)
                estado["campos"] = list(REQUIRED)
                continue
            raise ApiError(msg)
        bloco = ((dados.get("data") or {}).get("productOfferV2") or {})
        return bloco.get("nodes") or []
    raise ApiError("Não consegui montar uma busca aceita pela API")


def numero(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


def limpar(nome):
    return re.sub(r"\s+", " ", str(nome or "")).strip()[:120]


def escolher(nos, cat, cfg, hoje):
    """Filtra e ordena os resultados de uma busca e devolve produtos no formato do site."""
    divisor = numero(cfg.get("preco_divisor")) or 1
    itens = []
    for n in nos:
        nome = limpar(n.get("productName"))
        preco = numero(n.get("price")) or numero(n.get("priceMin"))
        link = str(n.get("offerLink") or "")
        img = str(n.get("imageUrl") or "")
        if not nome or not preco or preco <= 0 or not link.startswith("https://"):
            continue
        vendas = numero(n.get("sales"))
        if vendas is None:
            vendas = numero(n.get("soldCount"))
        nota = numero(n.get("ratingStar"))
        if vendas is not None and vendas < cfg.get("min_vendas", 0):
            continue
        if nota and nota < cfg.get("min_nota", 0):
            continue
        prod = {
            "nome": nome, "loja": "Shopee", "cat": cat,
            "preco": round(preco / divisor, 2), "antes": None,
            "visto": hoje, "link": link,
            "imagem": img if img.startswith("https://") else "",
            "exemplo": False, "auto": True,
        }
        desc = numero(n.get("priceDiscountRate"))
        if desc and desc > 0:
            prod["desconto"] = int(round(desc))
        itens.append((vendas or 0, nota or 0, prod))
    itens.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [p for _, _, p in itens[: int(cfg.get("por_busca", 4))]]


def main():
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_SECRET", "").strip()
    if not app_id or not secret:
        print("ERRO: faltam os Secrets SHOPEE_APP_ID e SHOPEE_SECRET no GitHub.")
        return 1

    cfg = ler_json("buscas.json", {})
    buscas = cfg.get("buscas") or []
    manual = [p for p in ler_json("manual.json", []) if isinstance(p, dict) and not p.get("exemplo")]
    hoje = datetime.now(BRT).strftime("%d/%m")
    print("Produtos manuais: %d | buscas: %d" % (len(manual), len(buscas)))

    estado = {"campos": list(FIELDS)}
    autos, ok, falhas, mostrou = [], 0, 0, False
    for b in buscas:
        termo, cat = b.get("termo"), b.get("cat", "Outros")
        if not termo:
            continue
        try:
            nos = buscar(app_id, secret, termo, int(cfg.get("busca_limite", 30)), b.get("ordem", cfg.get("ordem")), estado)
        except ApiError as e:
            falhas += 1
            print("FALHOU '%s': %s" % (termo, e))
            if "Autenticação" in str(e):
                break
            continue
        ok += 1
        if nos and not mostrou:
            print("Exemplo do que a API devolveu (primeiro item): %s" % json.dumps(nos[0], ensure_ascii=False)[:700])
            mostrou = True
        escolhidos = escolher(nos, cat, cfg, hoje)
        print("'%s': %d resultados, %d escolhidos" % (termo, len(nos), len(escolhidos)))
        autos.extend(escolhidos)

    if buscas and ok == 0:
        print("ERRO: nenhuma busca funcionou. O products.json NÃO foi alterado.")
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
        print("ERRO: lista vazia. O products.json NÃO foi alterado.")
        return 1

    atual = ler_json("products.json", {})
    if atual.get("produtos") == produtos:
        print("Sem mudanças nos produtos (%d)." % len(produtos))
        return 0
    saida = {"atualizado_em": datetime.now(BRT).strftime("%d/%m/%Y %H:%M"), "produtos": produtos}
    with open(os.path.join(ROOT, "products.json"), "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("products.json atualizado: %d produtos (%d manuais, %d da API). Buscas com falha: %d." % (
        len(produtos), len(manual), len(produtos) - len(manual), falhas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
