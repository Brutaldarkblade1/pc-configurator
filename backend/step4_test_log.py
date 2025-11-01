#!/usr/bin/env python3
# Testovací verze: projde produkty a zapíše zjištěné ceny do tabulky price_updates

import argparse, re, sys, time, random, decimal
from typing import List, Optional
from urllib.parse import urlparse
import psycopg2
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests

DSN_DEFAULT = "dbname=pc_configurator user=postgres password=TVE_HESLO host=localhost port=5432"

DOMAIN_SELECTORS = {
    "www.alza.cz": ".price-box__primary-price__value",
    "www.czc.cz": ".price-vatin, .price__price",
}

# --- pomocné funkce na parsování ceny ----------------------------------------
def normalize_spaces(s: str) -> str:
    if not s: return ""
    return s.replace("\u00A0", " ").replace("\u202F", " ").replace("\u2009", " ")

PRICE_PATTERN = re.compile(r"(?:\d{1,3}(?:[ \.\u00A0\u202F\u2009']\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)")

def find_price_candidates(text: str):
    if not text: return []
    t = normalize_spaces(text)
    t = re.sub(r",\s*-\b", "", t)
    t = re.sub(r"\b(Kč|CZK|EUR|€|\$)\b", "", t, flags=re.IGNORECASE)
    return PRICE_PATTERN.findall(t)

def normalize_candidate(s: str):
    if not s: return None
    raw = normalize_spaces(s).strip()
    raw = re.sub(r",\s*-\b", "", raw)
    last_dot = raw.rfind(".")
    last_comma = raw.rfind(",")
    dec_pos = max(last_dot, last_comma)
    if dec_pos != -1 and len(raw) - dec_pos - 1 in (1, 2):
        int_part = re.sub(r"[ \.\u00A0\u202F\u2009']", "", raw[:dec_pos])
        dec_part = re.sub(r"[^\d]", "", raw[dec_pos+1:])
        if not int_part: return None
        return decimal.Decimal(f"{int_part}.{dec_part}")
    else:
        int_only = re.sub(r"[ \.\u00A0\u202F\u2009',]", "", raw)
        if not int_only: return None
        return decimal.Decimal(int_only)

def pick_best_price_from_text(text: str):
    tokens = find_price_candidates(text)
    values = []
    for tok in tokens:
        val = normalize_candidate(tok)
        if val is not None:
            values.append(val)
    if not values: return None
    big = [v for v in values if v >= 100]
    return max(big) if big else max(values)

def get_html(url: str):
    sess = crequests.Session(impersonate="chrome")
    headers = {"Accept-Language": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7"}
    r = sess.get(url, headers=headers, timeout=20)
    if r.status_code != 200:
        print(f"[WARN] {url} -> HTTP {r.status_code}", file=sys.stderr)
        return None
    return r.text

def extract_price(html: str, selector: Optional[str]):
    soup = BeautifulSoup(html, "lxml")
    if selector:
        el = soup.select_one(selector)
        if el:
            p = pick_best_price_from_text(el.get_text(" ", strip=True))
            if p is not None: return p
    return None

def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

# --- hlavní část -------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Test logování cen do tabulky price_updates")
    ap.add_argument("--dsn", default=DSN_DEFAULT)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    conn = psycopg2.connect(args.dsn)
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute("SELECT id, url, price FROM products WHERE url IS NOT NULL AND btrim(url) <> '' LIMIT %s", (args.limit,))
        rows = cur.fetchall()

    print(f"Načteno {len(rows)} produktů k testu.")

    for pid, url, old_price in rows:
        dom = domain_of(url)
        selector = DOMAIN_SELECTORS.get(dom)
        print(f"[{dom}] {url}")

        html = get_html(url)
        if not html:
            print("  ⚠️ Nepodařilo se stáhnout stránku.")
            continue

        dec = extract_price(html, selector)
        if dec is None:
            print("  ⚠️ Nepodařilo se najít cenu.")
            continue

        new_price = int(dec.to_integral_value(rounding=decimal.ROUND_HALF_UP))
        print(f"  💰 Cena: {new_price} Kč (původně {old_price})")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO price_updates (product_id, url, old_price, new_price)
                VALUES (%s, %s, %s, %s)
            """, (pid, url, old_price, new_price))

        time.sleep(args.delay)

    conn.close()
    print("✅ Hotovo, záznamy jsou v tabulce price_updates")

if __name__ == "__main__":
    main()
