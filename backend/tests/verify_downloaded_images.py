#!/usr/bin/env python3
"""
Kontrola stažených obrázků:

- ověří, kolik produktů z DB má svůj obrázek
- najde chybějící obrázky a vypíše ID, název i URL
- zkontroluje kolize názvů souborů (víc produktů -> stejný filename)
- najde soubory v images/products, které nepatří žádnému produktu
- zkontroluje duplikáty podle obsahu (hash)
- chybějící obrázky navíc uloží do CSV souboru missing_images.csv
"""

import os
import re
import unicodedata
import hashlib
import csv
from pathlib import Path

import psycopg2

# Stejný DSN jako ve skriptu na stahování
DEFAULT_DSN = "postgresql://postgres:autodoprava@localhost:5432/pc_configurator"

BASE_DIR = Path(__file__).resolve().parent
IMAGES_DIR = BASE_DIR / "main" / "static" / "images" / "products"
MISSING_CSV = BASE_DIR / "missing_images.csv"


def slugify(text: str) -> str:
    """
    Stejná funkce jako ve download_all_images_from_alza.py
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def hash_file(path: Path) -> str:
    """
    SHA256 hash souboru – pro hledání duplikátů podle obsahu.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not IMAGES_DIR.exists():
        print(f"[ERR] Složka s obrázky neexistuje: {IMAGES_DIR}")
        return

    print(f"[INFO] Obrázky kontroluji ve složce: {IMAGES_DIR}")

    conn = psycopg2.connect(DEFAULT_DSN)
    cur = conn.cursor()

    # TEĎ bereme i URL, aby šly vypsat odkazy
    cur.execute("""
        SELECT id, name, url
        FROM products
        WHERE url IS NOT NULL AND url <> ''
        ORDER BY id
    """)
    rows = cur.fetchall()

    total_products = len(rows)
    print(f"[INFO] Produktů s URL v DB: {total_products}")

    expected_files = {}
    slug_collisions = {}

    # missing = list of (id, name, url)
    missing = []

    for product_id, product_name, product_url in rows:
        slug = slugify(product_name)

        candidates = [
            IMAGES_DIR / f"{slug}.jpg",
            IMAGES_DIR / f"{slug}.jpeg",
            IMAGES_DIR / f"{slug}.png",
            IMAGES_DIR / f"{slug}.webp",
        ]

        found_file = None
        for c in candidates:
            if c.exists():
                found_file = c
                break

        if found_file:
            expected_files[found_file.name] = expected_files.get(found_file.name, []) + [
                (product_id, product_name, product_url)
            ]
        else:
            missing.append((product_id, product_name, product_url))

        slug_collisions.setdefault(slug, []).append((product_id, product_name, product_url))

    cur.close()
    conn.close()

    real_collisions = {s: v for s, v in slug_collisions.items() if len(v) > 1}

    all_files_on_disk = {p.name: p for p in IMAGES_DIR.iterdir() if p.is_file()}
    extra_files = [name for name in all_files_on_disk.keys() if name not in expected_files]

    hash_map = {}
    for name, path in all_files_on_disk.items():
        h = hash_file(path)
        hash_map.setdefault(h, []).append(name)
    content_dupes = {h: names for h, names in hash_map.items() if len(names) > 1}

    # --------- Výpis souhrnu ---------

    products_with_image = total_products - len(missing)
    print()
    print("===== SOUHRN =====")
    print(f"Produkty s alespoň jedním obrázkem: {products_with_image}/{total_products}")
    print(f"Chybějící obrázky: {len(missing)}")
    print(f"Kolize názvů (stejný slug pro víc produktů): {len(real_collisions)}")
    print(f"Soubory na disku (celkem): {len(all_files_on_disk)}")
    print(f"Soubory na disku, které DB nezná: {len(extra_files)}")
    print(f"Duplikáty podle obsahu (stejný hash): {len(content_dupes)}")
    print("==================")
    print()

    # ---- Detailní výpis chybějících (ID, název, URL) ----
    if missing:
        print("Chybějící obrázky (ID, název, URL) – max 50:")
        for product_id, product_name, product_url in missing[:50]:
            print(f"  - [{product_id}] {product_name}")
            print(f"      {product_url}")
        if len(missing) > 50:
            print(f"  ... a dalších {len(missing) - 50}")

        # Uložíme i do CSV
        print(f"\n[INFO] Ukládám chybějící obrázky do: {MISSING_CSV}")
        with MISSING_CSV.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["id", "name", "url"])
            for product_id, product_name, product_url in missing:
                writer.writerow([product_id, product_name, product_url])

    if real_collisions:
        print("\nKolize slugů (stejný název souboru pro víc produktů):")
        for slug, items in list(real_collisions.items())[:10]:
            print(f"  slug: {slug}")
            for product_id, product_name, product_url in items:
                print(f"    - [{product_id}] {product_name}")
        if len(real_collisions) > 10:
            print(f"  ... a dalších {len(real_collisions) - 10} kolizí")

    if extra_files:
        print("\nSoubory na disku, které neodpovídají žádnému produktu (max 20):")
        for name in extra_files[:20]:
            print(f"  - {name}")
        if len(extra_files) > 20:
            print(f"  ... a dalších {len(extra_files) - 20}")

    if content_dupes:
        print("\nDuplikáty podle obsahu (stejný obrázek, jiné soubory):")
        for h, names in list(content_dupes.items())[:10]:
            print("  Soubory:")
            for n in names:
                print(f"    - {n}")
        if len(content_dupes) > 10:
            print(f"  ... a dalších {len(content_dupes) - 10} hashů s duplikáty")


if __name__ == "__main__":
    main()
