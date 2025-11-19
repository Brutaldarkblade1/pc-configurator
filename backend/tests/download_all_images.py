#!/usr/bin/env python3
import os
import argparse
import psycopg2
import requests
from urllib.parse import urlparse
from pathlib import Path

# Výchozí DSN – uprav podle sebe nebo předej přes argument
DEFAULT_DSN = "postgresql://user:password@localhost:5432/pc_configurator"

# Kam ukládat obrázky (relativně vůči tomuto souboru)
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "main" / "static" / "images" / "products"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def guess_extension_from_url(url: str) -> str:
    """
    Zkusí odhadnout příponu souboru z URL (jpg/png), jinak vrátí .jpg
    """
    path = urlparse(url).path  # např. /products/BD740h11b/BD740h11b.jpg
    ext = os.path.splitext(path)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        return ext
    return ".jpg"


def download_image(product_id: int, url: str, overwrite: bool = False):
    ext = guess_extension_from_url(url)
    filename = DOWNLOAD_DIR / f"{product_id}{ext}"

    if filename.exists() and not overwrite:
        print(f"[SKIP] {product_id} → {filename.name} už existuje")
        return

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PC-Configurator/1.0)"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        with open(filename, "wb") as f:
            f.write(resp.content)

        print(f"[OK]   {product_id} stažen → {filename.name}")
    except Exception as e:
        print(f"[ERR]  {product_id} {url} → {e}")


def main():
    parser = argparse.ArgumentParser(description="Stáhne všechny produktové obrázky z DB.")
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="Postgres DSN string")
    parser.add_argument("--limit", type=int, default=None, help="Max počet produktů pro stažení")
    parser.add_argument("--overwrite", action="store_true", help="Přepsat existující soubory")
    args = parser.parse_args()

    print(f"[INFO] Připojuji se k DB: {args.dsn}")
    conn = psycopg2.connect(args.dsn)
    cur = conn.cursor()

    query = """
        SELECT id, image_url
        FROM products
        WHERE image_url IS NOT NULL AND image_url <> ''
        ORDER BY id
    """
    if args.limit:
        query += f" LIMIT {int(args.limit)}"

    cur.execute(query)
    rows = cur.fetchall()
    print(f"[INFO] Nalezeno {len(rows)} produktů s image_url")

    for product_id, url in rows:
        if not url:
            continue
        download_image(product_id, url, overwrite=args.overwrite)

    cur.close()
    conn.close()
    print("[DONE] Hotovo.")


if __name__ == "__main__":
    main()
