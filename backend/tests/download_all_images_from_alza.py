#!/usr/bin/env python3
"""
Stáhne hlavní produktové obrázky z Alzy pro všechny produkty v DB
a uloží je jako: main/static/images/products/<product-name>.jpg

- mezi produkty je náhodný delay (2.5–4.5 s)
- HTML fetch má retry při 403/5xx
- chyby HTML se logují jako WARN a produkt se přeskočí
"""

import os
import argparse
import time
import random
import unicodedata
import re
from pathlib import Path

import psycopg2
from bs4 import BeautifulSoup
from curl_cffi import requests as crequests
import requests


# ---------------- Nastavení ----------------

DEFAULT_DSN = "postgresql://postgres:autodoprava@localhost:5432/pc_configurator"

BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "main" / "static" / "images" / "products"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------- Pomocné funkce ----------------

def slugify(text: str) -> str:
    """
    Převod názvu produktu na bezpečný název souboru.
    - odstraní diakritiku
    - malé znaky
    - mezery a nesmysly -> pomlčky
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def fetch_html(url: str, max_retries: int = 3) -> str | None:
    """
    Stáhne HTML přes curl_cffi s retry logikou.
    - při 403/5xx zkouší znovu s delayem
    - při 404 vrátí rovnou None
    - při jiných chybách po max_retries vrátí None
    """
    for attempt in range(1, max_retries + 1):
        try:
            resp = crequests.get(
                url,
                impersonate="chrome120",
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

        # 404 = produkt už není, rovnou přeskočíme
        if status == 404:
            print("[WARN] HTML 404 → produkt asi neexistuje / levne varianta")
            return None

        # 403 nebo 5xx = zkusíme párkrát znova
        if status == 403 or 500 <= status < 600:
            print(f"[WARN] HTML status {status} (pokus {attempt}/{max_retries})")
            if attempt < max_retries:
                sleep_sec = random.uniform(3.0, 6.0)
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

        # OK
        return resp.text

    return None


def extract_image_url(html: str) -> str | None:
    """
    Z HTML vytáhne URL produktového obrázku:
    hledá cokoliv na image.alza.cz s '/products/'.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["meta", "img", "link"]):
        url = (
            tag.get("content")
            or tag.get("src")
            or tag.get("href")
        )
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
    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        return ext
    return ".jpg"


def save_image(image_url: str, product_name: str, overwrite: bool = False):
    """
    Stáhne obrázek podle URL a uloží ho jako <slug-name>.<ext>.
    """
    ext = guess_ext(image_url)
    safe_name = slugify(product_name)
    filename = IMAGES_DIR / f"{safe_name}{ext}"

    if filename.exists() and not overwrite:
        print(f"[SKIP] {product_name} → {filename.name} už existuje")
        return

    try:
        # lehký delay i před stahováním obrázku (nechováme se jak bot)
        img_delay = random.uniform(0.5, 1.2)
        print(f"[INFO]   (img) čekám {img_delay:.1f}s před stažením obrázku...")
        time.sleep(img_delay)

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PC-Configurator/1.0)"
        }
        resp = requests.get(image_url, headers=headers, timeout=30)
        resp.raise_for_status()

        with open(filename, "wb") as f:
            f.write(resp.content)

        print(f"[OK]   {product_name} stažen → {filename.name}")
    except Exception as e:
        print(f"[ERR]  {product_name} download {image_url} → {e}")


# ---------------- Hlavní logika ----------------

def main():
    parser = argparse.ArgumentParser(
        description="Stáhne obrázky z Alzy a uloží je podle názvu produktů."
    )
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    print(f"[INFO] Připojuji se k DB: {args.dsn}")
    conn = psycopg2.connect(args.dsn)
    cur = conn.cursor()

    # POTŘEBUJEME name, url
    query = """
        SELECT id, name, url
        FROM products
        WHERE url IS NOT NULL AND url <> ''
        ORDER BY id
    """
    if args.limit:
        query += f" LIMIT {int(args.limit)}"

    cur.execute(query)
    rows = cur.fetchall()

    print(f"[INFO] Nalezeno {len(rows)} produktů s URL")

    for product_id, product_name, product_url in rows:
        # větší delay mezi produkty
        delay = random.uniform(2.5, 4.5)
        print(f"[INFO] Čekám {delay:.1f}s před produktem {product_name}...")
        time.sleep(delay)

        print(f"[INFO] {product_name} → {product_url}")

        # HTML s retry
        html = fetch_html(product_url)
        if not html:
            print(f"[WARN] {product_name} → nepodařilo se získat HTML, přeskočeno.")
            continue

        # obrázek
        image_url = extract_image_url(html)
        if not image_url:
            print(f"[WARN] {product_name} → nenašel jsem produktový obrázek")
            continue

        print(f"[INFO] {product_name} image URL → {image_url}")

        # save
        save_image(image_url, product_name, overwrite=args.overwrite)

    cur.close()
    conn.close()
    print("[DONE] Hotovo.")


if __name__ == "__main__":
    main()
