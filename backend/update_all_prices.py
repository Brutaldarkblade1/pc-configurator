#!/usr/bin/env python3
# Hromadný update všech cen v products podle URL (INT Kč) s průběhovým indikátorem.
#  - bere HTML přes curl_cffi (impersonate="chrome")
#  - vytáhne cenu podle CSS selektoru/domény
#  - HTTP 404 => produkt skončil => price = 1
#  - text "Prodej skončil" v HTML => taky price = 1
#
# Použití (PowerShell - jeden řádek):
#   python update_all_prices.py --only-domain "www.alza.cz" --delay 1.8
#
# DSN je defaultně nastavené na:
#   postgresql://postgres:autodoprava@localhost:5432/pc_configurator

import argparse, re, sys, time, decimal
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import psycopg2
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests

# DSN podle tvojí DB
DSN_DEFAULT = "postgresql://postgres:autodoprava@localhost:5432/pc_configurator"

# Doména -> CSS selektor ceny
DOMAIN_SELECTORS = {
    "www.alza.cz": ".price-box__primary-price__value",
    "www.czc.cz": ".price-vatin, .price__price",
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
def get_html(
    url: str,
    referer: Optional[str] = None,
    retries: int = 3,
    pause: float = 1.0,
) -> Tuple[Optional[str], Optional[int]]:
    """
    Vrátí (html, status_code).
    - 200 + text -> (html, 200)
    - 404        -> (None, 404)
    - 403/429    -> retry až retries
    - jiná chyba -> (None, poslední_status nebo None)
    """
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
    last_status = None
    for i in range(retries):
        try:
            r = sess.get(url, headers=headers, timeout=25)
            last = r
            last_status = r.status_code

            if r.status_code == 200 and r.text:
                return r.text, r.status_code

            if r.status_code == 404:
                return None, 404

            if r.status_code in (403, 429):
                time.sleep(pause * (i + 1))
                continue

            r.raise_for_status()
        except Exception as e:
            last = e
            last_status = getattr(getattr(last, "response", None), "status_code", None)
            time.sleep(pause * (i + 1))

    # 403 a 404 nebudeme spamovat, ostatní ano
    if last_status not in (403, 404):
        print(
            f"[WARN] Nezískal jsem HTML (poslední: {getattr(last, 'status_code', last)})",
            file=sys.stderr,
        )
    return None, last_status

# ---------- detekce "Prodej skončil" ----------------------------------------
def is_discontinued(html: str) -> bool:
    """
    Vrátí True, pokud je v HTML text 'Prodej skončil'
    (např. <span class="...">Prodej skončil</span>).
    """
    if not html:
        return False
    return "Prodej skončil" in html

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

# ---------- DB helper --------------------------------------------------------
def update_price(conn, prod_id: int, new_price: int, prev_price: Optional[int] = None):
    """
    Udělá UPDATE a vypíše, kolik řádků se změnilo.
    Když rowcount = 0 -> víme, že v DB se nic neupdatuje.
    """
    with conn.cursor() as cur:
        if prev_price is not None:
            cur.execute(
                "UPDATE products SET price = %s, old_price = %s, updated_at = NOW() WHERE id = %s",
                (new_price, int(prev_price), prod_id),
            )
        else:
            cur.execute(
                "UPDATE products SET price = %s, updated_at = NOW() WHERE id = %s",
                (new_price, prod_id),
            )
        if cur.rowcount == 0:
            print(f"    [DB WARN] UPDATE nic nezměnil (id={prod_id})", file=sys.stderr)
        else:
            print(f"    [DB OK]  UPDATE id={prod_id} -> price={new_price}", flush=True)

# ---------- main --------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Hromadný update products.price (INT Kč) podle URL s průběhem")
    ap.add_argument("--dsn", default=DSN_DEFAULT)
    ap.add_argument("--delay", type=float, default=1.8, help="pauza mezi požadavky [s]")
    ap.add_argument("--limit", type=int, help="max počet záznamů ke zpracování")
    ap.add_argument("--only-domain", help="zpracuj jen danou doménu (např. www.alza.cz)")
    ap.add_argument("--referer", help="globální Referer hlavička (např. https://www.alza.cz/)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    start_ts = time.time()

    try:
        print(f"[INFO] Připojuji se k DB: {args.dsn}")
        conn = psycopg2.connect(args.dsn)
        # každý UPDATE se hned zapíše
        conn.autocommit = True
    except Exception as e:
        print("❌ Nelze se připojit do DB. Zkontroluj --dsn.", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)

    total = changed = errors = processed = 0
    errors_403 = 0

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

            base_sql += " ORDER BY id"

            cur.execute(base_sql, tuple(params))
            rows = cur.fetchall()

        if args.limit:
            rows = rows[:args.limit]

        total = len(rows)
        print(f"Načteno produktů: {total}")

        for prod_id, url, old_price in rows:
            processed += 1

            percent = (processed / total) * 100 if total else 0
            print(f"[{processed}/{total}] ({percent:.1f}%) ", end="", flush=True)

            dom = domain_of(url)
            selector = DOMAIN_SELECTORS.get(dom)

            try:
                # používáme stejný delay i pro retry v get_html
                html, status = get_html(url, referer=args.referer, pause=args.delay)

                # 🔥 1) HTTP 404 -> produkt skončil → price = 1
                if status == 404:
                    new_price = 1
                    if old_price is not None and int(old_price) == new_price:
                        print(f"{dom} → 404, beze změny (price už {new_price})", flush=True)
                    else:
                        if args.dry_run:
                            print(f"{dom} → 404, nastavím price = 1 (old={old_price}) [DRY]", flush=True)
                        else:
                            print(f"{dom} → 404, UPDATE {old_price} ➜ {new_price}", flush=True)
                            update_price(conn, prod_id, new_price, old_price)
                            changed += 1

                    time.sleep(args.delay)
                    continue

                # 🔥 2) HTML existuje a obsahuje 'Prodej skončil' -> taky price = 1
                if html and is_discontinued(html):
                    new_price = 1
                    if old_price is not None and int(old_price) == new_price:
                        print(f"{dom} → Prodej skončil, beze změny (price už {new_price})", flush=True)
                    else:
                        if args.dry_run:
                            print(f"{dom} → Prodej skončil, nastavím price = 1 (old={old_price}) [DRY]", flush=True)
                        else:
                            print(f"{dom} → Prodej skončil, UPDATE {old_price} ➜ {new_price}", flush=True)
                            update_price(conn, prod_id, new_price, old_price)
                            changed += 1

                    time.sleep(args.delay)
                    continue

                # 3) když nemáme HTML
                if not html:
                    # speciálně 403 (server blokuje)
                    if status == 403:
                        errors_403 += 1
                        if errors_403 <= 5:
                            print(
                                f"[WARN] {dom} HTTP 403 – server blokuje, přeskočeno",
                                file=sys.stderr,
                            )
                        elif errors_403 == 6:
                            print(
                                "[WARN] ...další HTTP 403 už nevypisuju, jen je počítám",
                                file=sys.stderr,
                            )
                    else:
                        errors += 1
                        print(
                            f"[WARN] {dom} HTML none / status={status}",
                            file=sys.stderr,
                        )

                    time.sleep(args.delay)
                    continue

                # 4) normální extrakce ceny
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
                    print(f"{dom} → UPDATE {old_price} ➜ {new_price}", flush=True)
                    update_price(conn, prod_id, new_price, old_price)
                    changed += 1

                time.sleep(args.delay)

            except Exception as e:
                errors += 1
                print(f"[ERR] id={prod_id} {url} -> {e}", file=sys.stderr)
                time.sleep(args.delay)

        elapsed = time.time() - start_ts
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)

        print("-" * 56)
        print(f"Zpracováno: {processed}/{total}")
        print(f"Změněno:   {changed}")
        print(f"Chyby:     {errors}")
        print(f"HTTP 403:  {errors_403}")
        print(f"Trvání:    {mins} min {secs} s")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
