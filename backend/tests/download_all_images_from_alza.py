#!/usr/bin/env python3
"""
Stáhne hlavní produktové obrázky z Alzy pro produkty v DB
a uloží je do složky: ./img

- ukládá podle ID produktu: img/<product_id>.<ext>
- mezi produkty je náhodný delay (2.5–4.5 s)
- HTML fetch má retry při 403/5xx, používá jednu Session + rozumné hlavičky
- 404 a chyby HTML se logují jako WARN a produkt se přeskočí
- stahuje POUZE obrázky, které v img/ ještě nejsou
  (pokud nechceš skipovat, použij --overwrite)
"""

import os
import argparse
import time
import random
from pathlib import Path

import psycopg2
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests
import requests

# ---------------- Nastavení ----------------

DEFAULT_DSN = "postgresql://postgres:autodoprava@localhost:5432/pc_configurator"

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "img"          # <- tvoje složka s obrázky v backendu
IMG_DIR.mkdir(parents=True, exist_ok=True)

VALID_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

ALZA_REFERER = "https://www.alza.cz/"
COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

# jedna shared session (lepší proti 403 než spamovat nové spojení)
HTML_SESSION = crequests.Session(impersonate="chrome120")


# ---------------- Pomocné funkce ----------------

def fetch_html(url: str, max_retries: int = 3) -> str | None:
    """
    Stáhne HTML přes curl_cffi Session s retry logikou.
    - při 403/5xx zkouší znovu s delayem
    - při 404 vrátí rovnou None
    - při jiných chybách po max_retries vrátí None
    """
    for attempt in range(1, max_retries + 1):
        try:
            resp = HTML_SESSION.get(
                url,
                headers={**COMMON_HEADERS, "Referer": ALZA_REFERER},
                timeout=30,
            )
        except Exception as e:
            print(f"[WARN] HTML request chyba (pokus {attempt}/{max_retries}) → {e}")
            if attempt < max_retries:
                sleep_sec = random.uniform(3.0, 6.0)
                print(f"[INFO]   čekám {sleep_sec:.1f}s a zkouším znovu...")
                time.sleep(sleep_sec)
                continue
            return None

        status = resp.status_code

        if status == 404:
            print("[WARN] HTML 404 → produkt asi neexistuje / levná varianta")
            return None

        if status in (403, 429) or 500 <= status < 600:
            print(f"[WARN] HTML status {status} (pokus {attempt}/{max_retries})")
            if attempt < max_retries:
                sleep_sec = random.uniform(4.0, 8.0)
                print(f"[INFO]   čekám {sleep_sec:.1f}s a zkouším znovu...")
                time.sleep(sleep_sec)
                continue
            return None

        try:
            resp.raise_for_status()
        except Exception as e:
            print(f"[WARN] HTML raise_for_status (pokus {attempt}/{max_retries}) → {e}")
            if attempt < max_retries:
                sleep_sec = random.uniform(3.0, 6.0)
                print(f"[INFO]   čekám {sleep_sec:.1f}s a zkouším znovu...")
                time.sleep(sleep_sec)
                continue
            return None

        return resp.text

    return None


def extract_image_url(html: str) -> str | None:
    """
    Z HTML vytáhne URL produktového obrázku.

    1) Zkusí hlavní obrázek na Alze:
       - <img ... alt="... Hlavní obrázek">
       - <img> s class obsahující "detailGallery"
    2) Fallback: cokoliv na image.alza.cz s '/products/'.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1) Hlavní obrázek podle ALT (obsahuje "Hlavní obrázek")
    img = soup.select_one('img[alt$="Hlavní obrázek"], img[alt*="Hlavní obrázek"]')
    if not img:
        # 2) Hlavní obrázek podle class detailGallery
        img = soup.find("img", class_=lambda c: c and "detailGallery" in " ".join(c.split()) if isinstance(c, str) else False)

    if img:
        url = img.get("src") or img.get("data-src")
        if url:
            if url.startswith("//"):
                url = "https:" + url
            # často má Alza parametry width/height, ale to nám nevadí
            if "image.alza.cz" in url:
                return url

        # fallback přes srcset (vezmeme největší variantu)
        srcset = img.get("srcset")
        if srcset:
            candidates = []
            for part in srcset.split(","):
                part = part.strip()
                if not part:
                    continue
                pieces = part.split()
                url_part = pieces[0]
                if url_part.startswith("//"):
                    url_part = "https:" + url_part
                if "image.alza.cz" in url_part:
                    weight = 0
                    if len(pieces) > 1 and pieces[1].endswith("w"):
                        try:
                            weight = int(pieces[1][:-1])
                        except ValueError:
                            weight = 0
                    candidates.append((weight, url_part))
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                return candidates[0][1]

    # 3) Obecný fallback – cokoliv z image.alza.cz/products
    for tag in soup.find_all(["meta", "img", "link"]):
        url = tag.get("content") or tag.get("src") or tag.get("href")
        if not url:
            continue
        if url.startswith("//"):
            url = "https:" + url
        if "image.alza.cz" in url and "/products/" in url:
            return url

    return None


def guess_ext(url: str) -> str:
    _, ext = os.path.splitext(url)
    ext = ext.lower()
    if ext in VALID_EXTS:
        return ext
    return ".jpg"


def existing_image_for_id(product_id: int) -> Path | None:
    """
    Vrátí cestu k existujícímu obrázku pro dané ID (pokud nějaký existuje),
    kontroluje všechny povolené přípony.
    """
    for ext in VALID_EXTS:
        p = IMG_DIR / f"{product_id}{ext}"
        if p.exists():
            return p
    return None


def save_image(image_url: str, product_id: int, overwrite: bool = False):
    """
    Stáhne obrázek podle URL a uloží ho jako <id>.<ext> do IMG_DIR.
    """
    ext = guess_ext(image_url)
    filename = IMG_DIR / f"{product_id}{ext}"

    if filename.exists() and not overwrite:
        print(f"[SKIP] id={product_id} → {filename.name} už existuje")
        return

    try:
        img_delay = random.uniform(0.5, 1.2)
        print(f"[INFO]   (img) čekám {img_delay:.1f}s před stažením obrázku...")
        time.sleep(img_delay)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36",
            "Referer": ALZA_REFERER,
        }
        resp = requests.get(image_url, headers=headers, timeout=30)
        resp.raise_for_status()

        with open(filename, "wb") as f:
            f.write(resp.content)

        print(f"[OK]   id={product_id} stažen → {filename.name}")
    except Exception as e:
        print(f"[ERR]  id={product_id} download {image_url} → {e}")


# ---------------- Hlavní logika ----------------

def main():
    parser = argparse.ArgumentParser(
        description="Stáhne chybějící obrázky z Alzy a uloží je jako img/<id>.<ext>."
    )
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--limit", type=int, default=None, help="max počet produktů")
    parser.add_argument("--overwrite", action="store_true", help="přepsat existující obrázky")
    args = parser.parse_args()

    print(f"[INFO] Připojuji se k DB: {args.dsn}")
    conn = psycopg2.connect(args.dsn)
    cur = conn.cursor()

    # jen Alza URL, ať to nedělá bordel na jiných eshopech
    query = """
        SELECT id, name, url
        FROM products
        WHERE url IS NOT NULL
          AND btrim(url) <> ''
          AND position('www.alza.cz' in url) > 0
        ORDER BY id
    """
    if args.limit:
        query += f" LIMIT {int(args.limit)}"

    cur.execute(query)
    rows = cur.fetchall()

    print(f"[INFO] Nalezeno {len(rows)} produktů s URL (Alza)")

    for product_id, product_name, product_url in rows:
        # nejdřív zkontrolujeme, jestli už obrázek pro tohle ID máme
        existing = existing_image_for_id(product_id)
        if existing and not args.overwrite:
            print(f"[SKIP] id={product_id} ({product_name}) → obrázek už existuje ({existing.name})")
            continue

        delay = random.uniform(2.5, 4.5)
        print(f"\n[INFO] Čekám {delay:.1f}s před produktem {product_name} (id={product_id})...")
        time.sleep(delay)

        print(f"[INFO] {product_name} → {product_url}")

        html = fetch_html(product_url)
        if not html:
            print(f"[WARN] {product_name} → nepodařilo se získat HTML, přeskočeno.")
            continue

        image_url = extract_image_url(html)
        if not image_url:
            print(f"[WARN] {product_name} → nenašel jsem produktový obrázek")
            continue

        print(f"[INFO] {product_name} image URL → {image_url}")

        save_image(image_url, product_id, overwrite=args.overwrite)

    cur.close()
    conn.close()
    print("\n[DONE] Hotovo.")


if __name__ == "__main__":
    main()
