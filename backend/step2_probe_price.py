#!/usr/bin/env python3
# Krok 2: stáhne jednu URL a zkusí z ní vytáhnout cenu pomocí selektoru
import argparse, re, sys, requests
from bs4 import BeautifulSoup

def to_number(text: str):
    if not text: 
        return None
    t = re.sub(r"[^\d,.\s]", "", text).strip().replace(" ", "")
    t = t.replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return m.group(0) if m else None

def extract_price(html: str, selector: str | None):
    soup = BeautifulSoup(html, "lxml")

    # 1) pokud máme selektor, zkus ho
    if selector:
        el = soup.select_one(selector)
        if el:
            n = to_number(el.get_text(" ", strip=True))
            if n: 
                return n

    # 2) fallbacky: meta a schema.org
    meta = soup.find("meta", {"property": "product:price:amount"}) \
        or soup.find("meta", {"property": "og:price:amount"})
    if meta and meta.get("content"):
        n = to_number(meta["content"])
        if n:
            return n

    itemprop = soup.find(attrs={"itemprop": "price"})
    if itemprop:
        n = to_number(itemprop.get("content") or itemprop.get_text(" ", strip=True))
        if n:
            return n

    # 3) poslední pokus: jakýkoli element s "price" v class/id
    for el in soup.find_all(attrs={"class": re.compile("price", re.I)}):
        n = to_number(el.get_text(" ", strip=True))
        if n:
            return n
    for el in soup.find_all(id=re.compile("price", re.I)):
        n = to_number(el.get_text(" ", strip=True))
        if n:
            return n

    return None

def main():
    p = argparse.ArgumentParser(description="Vytáhne cenu z jedné URL")
    p.add_argument("--url", required=True, help="URL produktu")
    p.add_argument("--selector", help="CSS selektor ceny (např. .price-box__primary-price__value)")
    args = p.parse_args()

    r = requests.get(args.url, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })
    if r.status_code != 200 or not r.text:
        print(f"Chyba: HTTP {r.status_code}", file=sys.stderr)
        sys.exit(1)

    price = extract_price(r.text, args.selector)
    if not price:
        print("Cenu se nepodařilo najít.")
        sys.exit(2)

    print(f"Nalezená cena: {price}")

if __name__ == "__main__":
    main()
