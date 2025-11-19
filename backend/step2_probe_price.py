#!/usr/bin/env python3
# Krok 2: stáhne jednu URL (Chrome fingerprint přes curl_cffi) a vytáhne cenu
# Použití:
#   python step2_probe_price.py --url "https://..." --selector ".price-box__primary-price__value"
#   python step2_probe_price.py --url "https://..." --debug

import argparse, re, sys, time, random, decimal
from typing import List, Optional
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests

# --- Pomocné: normalizace textu (řeší NBSP a spol.) -------------------------
def normalize_spaces(s: str) -> str:
    if not s:
        return ""
    return s.replace("\u00A0", " ").replace("\u202F", " ").replace("\u2009", " ")

# --- Extrakce kandidátů cen ---------------------------------------------------
PRICE_PATTERN = re.compile(
    r"""
    (?:
        \d{1,3}(?:[ \.\u00A0\u202F\u2009']\d{3})+(?:[.,]\d{1,2})?
      |
        \d+(?:[.,]\d{1,2})?
    )
    """,
    re.VERBOSE
)

def find_price_candidates(text: str) -> List[str]:
    if not text:
        return []
    t = normalize_spaces(text)
    # Zahodíme české ",-" (např. "2 590,-") a měny
    t = re.sub(r",\s*-\b", "", t)
    t = re.sub(r"\b(Kč|CZK|EUR|€|\$)\b", "", t, flags=re.IGNORECASE)
    return PRICE_PATTERN.findall(t)

def normalize_candidate(s: str) -> Optional[decimal.Decimal]:
    if not s:
        return None
    raw = normalize_spaces(s).strip()
    raw = re.sub(r",\s*-\b", "", raw)

    # Pozice poslední tečky/čárky – bereme ji jako desetinný oddělovač,
    # ostatní tečky/mezery/apos jsou tisícovky a smažeme je.
    last_dot = raw.rfind(".")
    last_comma = raw.rfind(",")
    dec_pos = max(last_dot, last_comma)

    if dec_pos != -1 and len(raw) - dec_pos - 1 in (1, 2):
        int_part = re.sub(r"[ \.\u00A0\u202F\u2009']", "", raw[:dec_pos])
        dec_part = re.sub(r"[^\d]", "", raw[dec_pos+1:])
        return decimal.Decimal(f"{int_part}.{dec_part}") if int_part else None
    else:
        int_only = re.sub(r"[ \.\u00A0\u202F\u2009',]", "", raw)
        return decimal.Decimal(int_only) if int_only else None

def pick_best_price_from_text(text: str, debug=False) -> Optional[decimal.Decimal]:
    tokens = find_price_candidates(text)
    values: List[decimal.Decimal] = []
    for tok in tokens:
        val = normalize_candidate(tok)
        if val is not None:
            values.append(val)

    if debug:
        print("DEBUG candidates:", tokens, file=sys.stderr)
        print("DEBUG normalized :", [str(v) for v in values], file=sys.stderr)

    if not values:
        return None
    big = [v for v in values if v >= 100]  # preferuj „reálné“ ceny
    return max(big) if big else max(values)

# --- HTML fetch přes curl_cffi (Chrome fingerprint) --------------------------
def get_html(url: str, referer: Optional[str] = None, retries: int = 3):
    sess = crequests.Session(impersonate="chrome")
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer

    last = None
    for i in range(retries):
        try:
            r = sess.get(url, headers=headers, timeout=25)
            last = r
            if r.status_code == 200 and r.text:
                return r.text
            if r.status_code in (403, 429):
                time.sleep(1.0 + i + random.random())
                continue
            r.raise_for_status()
        except Exception as e:
            last = e
            time.sleep(1.0 + i + random.random())
    print(f"Nezískal jsem HTML (poslední stav: {getattr(last, 'status_code', last)})", file=sys.stderr)
    return None

# --- Extrakce ceny z HTML -----------------------------------------------------
def extract_price(html: str, selector: Optional[str], debug=False) -> Optional[decimal.Decimal]:
    soup = BeautifulSoup(html, "lxml")

    # 1) pokud dáš selektor, použijeme ho jako první
    if selector:
        el = soup.select_one(selector)
        if el:
            price = pick_best_price_from_text(el.get_text(" ", strip=True), debug=debug)
            if price is not None:
                return price

    # 2) meta (og/product)
    meta = soup.find("meta", {"property": "product:price:amount"}) \
        or soup.find("meta", {"property": "og:price:amount"})
    if meta and meta.get("content"):
        price = pick_best_price_from_text(meta["content"], debug=debug)
        if price is not None:
            return price

    # 3) schema.org itemprop
    itemprop = soup.find(attrs={"itemprop": "price"})
    if itemprop:
        price = pick_best_price_from_text(itemprop.get("content") or itemprop.get_text(" ", strip=True), debug=debug)
        if price is not None:
            return price

    # 4) fallback: libovolný element s "price" v class/id
    texts = []
    for el in soup.find_all(attrs={"class": re.compile("price", re.I)}):
        texts.append(el.get_text(" ", strip=True))
    for el in soup.find_all(id=re.compile("price", re.I)):
        texts.append(el.get_text(" ", strip=True))

    best = None
    for t in texts:
        v = pick_best_price_from_text(t, debug=debug)
        if v is not None:
            best = v if best is None else max(best, v)
    return best

# --- CLI ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Vytáhne cenu z jedné URL (CZ formáty, Chrome fingerprint)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--selector", help="CSS selektor ceny (např. .price-box__primary-price__value)")
    ap.add_argument("--referer", help="Volitelná hlavička Referer (např. https://www.domena.cz/)")
    ap.add_argument("--debug", action="store_true", help="Vypíše kandidáty a normalizované hodnoty")
    args = ap.parse_args()

    html = get_html(args.url, referer=args.referer)
    if not html:
        print("Cenu se nepodařilo zjistit (nezískal jsem HTML).", file=sys.stderr)
        sys.exit(1)

    price = extract_price(html, args.selector, debug=args.debug)
    if price is None:
        print("Cenu se nepodařilo najít.", file=sys.stderr)
        sys.exit(2)

    # --- hezké vytištění bez vědecké notace a bez oříznutí celých čísel ---
    val = format(price, "f")  # např. "10690" nebo "10690.50"
    if "." in val:            # ořezávej nuly jen u desetinných čísel
        val = val.rstrip("0").rstrip(".")
    print(f"Nalezená cena: {val}")

if __name__ == "__main__":
    main()
