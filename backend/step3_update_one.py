import argparse, re, sys, time, random, decimal, math
from typing import List, Optional
import psycopg2
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests

DSN_DEFAULT = "dbname=pc_configurator user=postgres password=autodoprava host=localhost port=5432"

# ---------- text → kandidáti cen ---------------------------------------------
def normalize_spaces(s: str) -> str:
    if not s:
        return ""
    return s.replace("\u00A0", " ").replace("\u202F", " ").replace("\u2009", " ")

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
        dec_part = re.sub(r"[^\d]", "", raw[dec_pos+1:])
        if not int_part:
            return None
        return decimal.Decimal(f"{int_part}.{dec_part}")
    else:
        int_only = re.sub(r"[ \.\u00A0\u202F\u2009',]", "", raw)
        if not int_only:
            return None
        return decimal.Decimal(int_only)

def pick_best_price_from_text(text: str) -> Optional[decimal.Decimal]:
    tokens = find_price_candidates(text)
    values: List[decimal.Decimal] = []
    for tok in tokens:
        val = normalize_candidate(tok)
        if val is not None:
            values.append(val)
    if not values:
        return None
    big = [v for v in values if v >= 100]  # preferuj reálné ceny
    return max(big) if big else max(values)

# ---------- fetch HTML (curl_cffi s Chrome fingerprintem) ---------------------
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

# ---------- extrakce ceny z HTML ---------------------------------------------
def extract_price(html: str, selector: Optional[str]) -> Optional[decimal.Decimal]:
    soup = BeautifulSoup(html, "lxml")

    if selector:
        el = soup.select_one(selector)
        if el:
            price = pick_best_price_from_text(el.get_text(" ", strip=True))
            if price is not None:
                return price

    meta = soup.find("meta", {"property": "product:price:amount"}) \
        or soup.find("meta", {"property": "og:price:amount"})
    if meta and meta.get("content"):
        price = pick_best_price_from_text(meta["content"])
        if price is not None:
            return price

    itemprop = soup.find(attrs={"itemprop": "price"})
    if itemprop:
        price = pick_best_price_from_text(itemprop.get("content") or itemprop.get_text(" ", strip=True))
        if price is not None:
            return price

    texts = []
    for el in soup.find_all(attrs={"class": re.compile("price", re.I)}):
        texts.append(el.get_text(" ", strip=True))
    for el in soup.find_all(id=re.compile("price", re.I)):
        texts.append(el.get_text(" ", strip=True))

    best = None
    for t in texts:
        v = pick_best_price_from_text(t)
        if v is not None:
            best = v if best is None else max(best, v)
    return best

# ---------- CLI & DB update ---------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Update products.price (INT Kč) pro JEDNU URL")
    ap.add_argument("--url", required=True, help="URL existující v products.url")
    ap.add_argument("--selector", help="CSS selektor ceny (např. .price-box__primary-price__value)")
    ap.add_argument("--referer", help="Volitelná hlavička Referer (např. https://www.domena.cz/)")
    ap.add_argument("--dsn", default=DSN_DEFAULT, help="PostgreSQL DSN")
    ap.add_argument("--dry-run", action="store_true", help="Jen vypíše, nezapíše do DB")
    args = ap.parse_args()

    # 0) najdi řádek v DB podle URL
    try:
        conn = psycopg2.connect(args.dsn)
    except Exception as e:
        print("❌ Nelze se připojit do DB. Zkontroluj --dsn.", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, price
                FROM products
                WHERE url = %s
                LIMIT 1
            """, (args.url,))
            row = cur.fetchone()

        if not row:
            print("❌ V tabulce products neexistuje řádek s danou URL.")
            conn.close()
            sys.exit(2)

        prod_id, old_price = row
        print(f"Načteno: id={prod_id}, původní price={old_price}")

        # 1) stáhni HTML a vytáhni cenu
        html = get_html(args.url, referer=args.referer)
        if not html:
            print("❌ Cenu se nepodařilo zjistit (nezískal jsem HTML).", file=sys.stderr)
            conn.close()
            sys.exit(3)

        dec_price = extract_price(html, args.selector)
        if dec_price is None:
            print("❌ Cenu se nepodařilo najít v HTML.", file=sys.stderr)
            conn.close()
            sys.exit(4)

        # 2) převod na INTEGER Kč (zaokrouhlení na nejbližší celé)
        # např. 10_690.00 -> 10690, 10_690.49 -> 10690, 10_690.50 -> 10691
        new_price_int = int(decimal.Decimal(dec_price).to_integral_value(rounding=decimal.ROUND_HALF_UP))

        print(f"Zjištěná cena (Kč): {new_price_int}")

        # 3) porovnej a případně zapiš
        if old_price is not None and int(old_price) == new_price_int:
            print("🔹 Cena se nezměnila → žádný update.")
            conn.close()
            sys.exit(0)

        if args.dry_run:
            print("🧪 DRY-RUN: nezapisuji do DB.")
            conn.close()
            sys.exit(0)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE products SET price = %s WHERE id = %s",
                (new_price_int, prod_id)
            )
        conn.commit()
        print("✅ Zapsáno do DB.")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
