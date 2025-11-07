#!/usr/bin/env python3
# Hromadný update všech cen v products podle URL (INT Kč) s průběhovým indikátorem.
# Použití (PowerShell - jeden řádek):
#   python update_all_prices.py --dsn "dbname=pc_configurator user=postgres password=TVE_HESLO host=localhost port=5432" --delay 1.8
# Doporučený první test:
#   python update_all_prices.py --dsn "..." --only-domain "www.alza.cz" --limit 20 --delay 1.8 --dry-run

import argparse, re, sys, time, random, decimal
from typing import List, Optional
from urllib.parse import urlparse
import psycopg2
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests

DSN_DEFAULT = "dbname=pc_configurator user=postgres password=autodoprava host=localhost port=5432"

# Doména -> CSS selektor ceny (přidej si další dle potřeby)
DOMAIN_SELECTORS = {
    "www.alza.cz": ".price-box__primary-price__value",
    "www.czc.cz": ".price-vatin, .price__price",
    # "www.tsbohemia.cz": "...",
    # "www.mironet.cz":  "...",
}

# ---------- pomocné: parsování ceny (CZ formáty) -----------------------------
def normalize_spaces(s: str) -> str:
    if not s:
        return ""
    return s.replace("\u00A0", " ").replace("\u202F", " ").replace("\u2009", " ")

PRICE_PATTERN = re.compile(
    r"(?:\d{1,3}(?:[ \.\u00A0\u202F\u2009']\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
)

def find_price_candidates(text: str):
    if not text:
        return []
    t = normalize_spaces(text)
    t = re.sub(r",\s*-\b", "", t)  # "2 590,-" -> "2 590"
    t = re.sub(r"\b(Kč|CZK|EUR|€|\$)\b", "", t, flags=re.IGNORECASE)
    return PRICE_PATTERN.findall(t)

def normalize_candidate(s: str) -> Optional[decimal.Decimal]:
    if not s:
        return None
    raw = normalize_spaces(s).strip()
    raw = re.sub(r",\s*-\b", "", raw)
    last_dot = raw.rfind(".")
    last_comma = raw.rfind(",")
    dec_pos = max(last_dot, last_comma)
    if dec_pos != -1 and len(raw) - dec_pos - 1 in (1, 2):
        int_part = re.sub(r"[ \.\u00A0\u202F\u2009']", "", raw[:dec_pos])
        dec_part = re.sub(r"[^\d]", "", raw[dec_pos + 1:])
        if not int_part:
            return None
        return decimal.Decimal(f"{int_part}.{dec_part}")
    else:
        int_only = re.sub(r"[ \.\u00A0\u202F\u2009',]", "", raw)
        if not int_only:
            return None
        return decimal.Decimal(int_only)

def best_price_from_text(text: str) -> Optional[decimal.Decimal]:
    vals = []
    for tok in find_price_candidates(text):
        v = normalize_candidate(tok)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    big = [v for v in vals if v >= 100]  # odfiltruj splátky typu "139/měs."
    return max(big) if big else max(vals)

def as_kc_int(dec: decimal.Decimal) -> int:
    # Zaokrouhli na celé Kč (ROUND_HALF_UP)
    return int(dec.to_integral_value(rounding=decimal.ROUND_HALF_UP))

# ---------- HTTP fetch (Chrome fingerprint) ----------------------------------
def get_html(url: str, referer: Optional[str] = None, retries: int = 3, pause: float = 1.0):
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
                time.sleep(pause * (i + 1))
                continue
            r.raise_for_status()
        except Exception as e:
            last = e
            time.sleep(pause * (i + 1))
    print(f"[WARN] Nezískal jsem HTML (poslední: {getattr(last, 'status_code', last)})", file=sys.stderr)
    return None

# ---------- extrakce ceny z HTML ---------------------------------------------
def extract_price(html: str, selector: Optional[str]) -> Optional[decimal.Decimal]:
    soup = BeautifulSoup(html, "lxml")

    # 1) preferuj selektor dle domény
    if selector:
        el = soup.select_one(selector)
        if el:
            p = best_price_from_text(el.get_text(" ", strip=True))
            if p is not None:
                return p

    # 2) meta (og/product)
    meta = soup.find("meta", {"property": "product:price:amount"}) \
        or soup.find("meta", {"property": "og:price:amount"})
    if meta and meta.get("content"):
        p = best_price_from_text(meta["content"])
        if p is not None:
            return p

    # 3) schema.org itemprop
    itemprop = soup.find(attrs={"itemprop": "price"})
    if itemprop:
        p = best_price_from_text(itemprop.get("content") or itemprop.get_text(" ", strip=True))
        if p is not None:
            return p

    # 4) fallback: libovolný element s "price" v class/id
    texts = []
    for el in soup.find_all(attrs={"class": re.compile("price", re.I)}):
        texts.append(el.get_text(" ", strip=True))
    for el in soup.find_all(id=re.compile("price", re.I)):
        texts.append(el.get_text(" ", strip=True))

    best = None
    for t in texts:
        v = best_price_from_text(t)
        if v is not None:
            best = v if best is None else max(best, v)
    return best

# ---------- utility -----------------------------------------------------------
def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

# ---------- main --------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Hromadný update products.price (INT Kč) podle URL s průběhem")
    ap.add_argument("--dsn", default=DSN_DEFAULT)
    ap.add_argument("--delay", type=float, default=1.8, help="pauza mezi požadavky [s]")
    ap.add_argument("--batch-size", type=int, default=25, help="commit po N změnách")
    ap.add_argument("--limit", type=int, help="max počet záznamů ke zpracování")
    ap.add_argument("--only-domain", help="zpracuj jen danou doménu (např. www.alza.cz)")
    ap.add_argument("--referer", help="globální Referer hlavička (např. https://www.alza.cz/)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    start_ts = time.time()

    try:
        conn = psycopg2.connect(args.dsn)
        conn.autocommit = False
    except Exception as e:
        print("❌ Nelze se připojit do DB. Zkontroluj --dsn.", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)

    total = changed = errors = processed = 0
    pending_commits = 0

    try:
        with conn.cursor() as cur:
            base_sql = """
                SELECT id, url, price
                FROM products
                WHERE url IS NOT NULL AND btrim(url) <> ''
            """
            params = []
            if args.only_domain:
                base_sql += " AND position(%s in url) > 0"
                params.append(args.only_domain)

            # deterministické pořadí pro čitelný log
            base_sql += " ORDER BY id"

            cur.execute(base_sql, tuple(params))
            rows = cur.fetchall()

        if args.limit:
            rows = rows[:args.limit]

        total = len(rows)
        print(f"Načteno produktů: {total}")

        for prod_id, url, old_price in rows:
            processed += 1

            # --- indikátor průběhu ---
            percent = (processed / total) * 100 if total else 0
            print(f"[{processed}/{total}] ({percent:.1f}%) ", end="", flush=True)

            dom = domain_of(url)
            selector = DOMAIN_SELECTORS.get(dom)

            try:
                html = get_html(url, referer=args.referer)
                if not html:
                    errors += 1
                    print(f"[WARN] {dom} HTML none", flush=True)
                    time.sleep(args.delay)
                    continue

                dec = extract_price(html, selector)
                if dec is None:
                    errors += 1
                    print(f"[WARN] {dom} price none", flush=True)
                    time.sleep(args.delay)
                    continue

                new_price = as_kc_int(dec)

                if old_price is not None and int(old_price) == new_price:
                    print(f"{dom} → beze změny ({new_price})", flush=True)
                    time.sleep(args.delay)
                    continue

                if args.dry_run:
                    print(f"{dom} → {new_price} (old={old_price}) [DRY]", flush=True)
                else:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE products SET price = %s WHERE id = %s", (new_price, prod_id))
                    changed += 1
                    print(f"{dom} → UPDATE {old_price} ➜ {new_price}", flush=True)

                    pending_commits += 1
                    if pending_commits >= args.batch_size:
                        conn.commit()
                        pending_commits = 0

                time.sleep(args.delay)

            except Exception as e:
                errors += 1
                print(f"[ERR] id={prod_id} {url} -> {e}", file=sys.stderr)
                time.sleep(args.delay)

        if not args.dry_run and pending_commits > 0:
            conn.commit()

        elapsed = time.time() - start_ts
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)

        print("-" * 56)
        print(f"Zpracováno: {processed}/{total}")
        print(f"Změněno:   {changed}")
        print(f"Chyby:     {errors}")
        print(f"Trvání:    {mins} min {secs} s")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
