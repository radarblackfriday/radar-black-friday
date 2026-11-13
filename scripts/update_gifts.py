
import json, os, sys, time
sys.path.insert(0, "scripts")
import shopee_api as api

ID = os.environ["SHOPEE_APP_ID"]
KEY = os.environ["SHOPEE_SECRET"]
cfg = json.load(open("presentes-buscas.json"))
try:
    velhos = json.load(open("presentes.json"))["produtos"]
except Exception:
    velhos = []
est = {"campos": list(api.FIELDS)}
novos, falhas = [], 0
for b in cfg["buscas"]:
    t = b["termo"]
    try:
        res = api.buscar(ID, KEY, t, 30, 2, est)
    except Exception as e:
        print("FALHOU", t, e)
        falhas += 1
        novos += [p for p in velhos if p.get("busca") == t]
        continue
    ok = []
    for r in res:
        try:
            d = int(r.get("priceDiscountRate") or 0)
            if int(r.get("sales") or 0) < 50 or d < 20:
                continue
            if float(r.get("ratingStar") or 0) < 4.5:
                continue
            ok.append({"nome": r["productName"],
                "preco": float(r["price"]), "foto": r["imageUrl"],
                "link": r["offerLink"], "desconto": d,
                "loja": r.get("shopName", "Shopee"),
                "categoria": b["categoria"], "busca": t})
        except Exception:
            continue
    ok.sort(key=lambda x: -x["desconto"])
    novos += ok[:4]
    time.sleep(1.5)
if novos:
    h = time.gmtime(time.time() - 10800)
    agora = time.strftime("%d/%m/%Y %H:%M", h)
    with open("presentes.json", "w", encoding="utf-8") as f:
        json.dump({"atualizado": agora, "produtos": novos},
                  f, ensure_ascii=False, indent=1)
print("presentes.json:", len(novos), "Falhas:", falhas)
