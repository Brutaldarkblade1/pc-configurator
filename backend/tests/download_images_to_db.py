#!/usr/bin/env python3
"""
Stáhne obrázky produktů z jejich produktových URL a uloží je přímo do DB jako BYTEA.
"""

import argparse
import sys
import time
import random
from urllib.parse import urljoin
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2 import sql
from curl_cffi import requests as crequests
from bs4 import BeautifulSoup

# TADY BUDE TVŮJ COOKIE HEADER Z ALZY
# -------------------------------------------------
# 1) V prohlížeči v DevTools (Network -> Request -> Headers) zkopíruj hodnotu "Cookie"
# 2) Z ní vezmi jen část pro doménu .alza.cz (např. udid=...; VST=...; VZTX=...;)
# 3) Vlož ji sem do uvozovek jako jeden řádek

COOKIE_HEADER = "udid=0199fc51-394e-7945-8bab-760d5b7e9fc0@1763200361674; VST=b3b8920e-b3ff-48eb-a17c-8d303b209737; VZTX=11315287340;"
# -------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(description="Stáhne obrázky produktů a uloží je do DB (BYTEA)")
    p.add_argument(
        "--dsn",
        required=True,
        help='PostgreSQL DSN, např. "postgresql://user:pass@localhost:5432/pc_configurator"',
    )
    p.add_argument(
        "--table",
        default="products",
        help="Název tabulky s produkty (default: products)",
    )
    p.add_argument(
        "--id-column",
        dest="id_column",
        default="id",
        help="Sloupec s ID produktu (default: id)",
    )
    p.add_argument(
        "--url-column",
        dest="url_column",
        default="url",
        help="Sloupec s URL produktové stránky (default: url)",
    )
    p.add_argument(
        "--image-column",
        dest="image_column",
        default="image_data",
        help="Sloupec, kam se uloží binární obrázek (BYTEA) (default: image_data)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximální počet záznamů ke zpracování (default: vše)",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Základní delay mezi requesty v sekundách (default: 0.5)",
    )
    p.add_argument(
        "--delay-jitter",
        type=float,
        default=0.5,
        help="Náhodný jitter (0–X sekund) přidaný k delay (default: 0.5)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout HTTP požadavků v sekundách (default: 20)",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Přeskočí řádky, kde už image_column není NULL",
    )
    p.add_argument(
        "--img-selector",
        dest="img_selector",
        default=None,
        help=(
            "CSS selektor na element s obrázkem, např. "
            "'.c-product__image img' nebo '#detailPicture .detailGallery-alz-12 img'. "
            "Když není, použije se og:image / první <img>."
        ),
    )
    p.add_argument(
        "--img-attr",
        dest="img_attr",
        default="src",
        help="Atribut, ze kterého se vezme URL obrázku (default: src)",
    )
    return p.parse_args()


def smart_sleep(base_delay: float, jitter: float) -> None:
    """Usne base_delay + náhodný (0..jitter)."""
    if base_delay <= 0 and jitter <= 0:
        return
    extra = random.uniform(0, max(0.0, jitter))
    time.sleep(max(0.0, base_delay) + extra)


def get_image_url_from_soup(
    soup: BeautifulSoup,
    page_url: str,
    img_selector: Optional[str],
    img_attr: str,
) -> Optional[str]:
    """
    Vrátí absolutní URL obrázku podle tohoto pořadí:
    1) pokud je img_selector, použije se select_one(img_selector) a img_attr/src
    2) <meta property="og:image">
    3) <meta name="og:image">
    4) první <img>
    """
    # 1) Vlastní CSS selektor
    if img_selector:
        el = soup.select_one(img_selector)
        if el is not None:
            candidate = el.get(img_attr) or el.get("src")
            if candidate:
                return urljoin(page_url, candidate.strip())

    # 2) og:image (property)
    tag = soup.find("meta", property="og:image")
    if tag and tag.get("content"):
        return urljoin(page_url, tag["content"].strip())

    # 3) og:image (name)
    tag = soup.find("meta", attrs={"name": "og:image"})
    if tag and tag.get("content"):
        return urljoin(page_url, tag["content"].strip())

    # 4) první <img>
    img = soup.find("img")
    if img and img.get("src"):
        return urljoin(page_url, img["src"].strip())

    return None


def download_image_bytes(img_url: str, timeout: float) -> Optional[bytes]:
    """
    Stáhne obrázek a vrátí bytes, nebo None při chybě.
    Používá curl_cffi s impersonate="chrome120".
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
        }
        if COOKIE_HEADER:
            headers["Cookie"] = COOKIE_HEADER

        resp = crequests.get(
            img_url,
            headers=headers,
            timeout=timeout,
            impersonate="chrome120",
        )
        if resp.status_code != 200:
            print(f"  [WARN] Stahování obrázku selhalo, status {resp.status_code}")
            return None
        return resp.content
    except Exception as e:
        print(f"  [ERROR] Výjimka při stahování obrázku {img_url}: {e}")
        return None


def main():
    args = parse_args()

    # Připojení k DB
    try:
        conn = psycopg2.connect(args.dsn)
    except Exception as e:
        print(f"[FATAL] Nepodařilo se připojit k DB: {e}")
        sys.exit(1)

    conn.autocommit = False

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            where_clauses = [
                sql.SQL("{url_col} IS NOT NULL").format(
                    url_col=sql.Identifier(args.url_column)
                )
            ]

            if args.skip_existing:
                where_clauses.append(
                    sql.SQL("{img_col} IS NULL").format(
                        img_col=sql.Identifier(args.image_column)
                    )
                )

            where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_clauses)

            limit_sql = sql.SQL("")
            if args.limit:
                limit_sql = sql.SQL(" LIMIT {}").format(sql.Literal(args.limit))

            query = (
                sql.SQL("SELECT {id_col}, {url_col} FROM {table}")
                .format(
                    id_col=sql.Identifier(args.id_column),
                    url_col=sql.Identifier(args.url_column),
                    table=sql.Identifier(args.table),
                )
                + where_sql
                + limit_sql
            )

            print("[INFO] Spouštím dotaz na produkty...")
            cur.execute(query)
            rows = cur.fetchall()

            total = len(rows)
            print(f"[INFO] Nalezeno {total} produktů ke zpracování")

            processed = 0
            for row in rows:
                product_id = row[args.id_column]
                product_url = row[args.url_column]
                processed += 1

                print(f"\n[{processed}/{total}] ID={product_id} URL={product_url}")

                # 1) stáhnout HTML
                try:
                    headers = {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                    }
                    if COOKIE_HEADER:
                        headers["Cookie"] = COOKIE_HEADER

                    resp = crequests.get(
                        product_url,
                        headers=headers,
                        timeout=args.timeout,
                        impersonate="chrome120",
                    )
                    if resp.status_code != 200:
                        print(f"  [WARN] Neúspěšný HTTP status {resp.status_code}")
                        smart_sleep(args.delay, args.delay_jitter)
                        continue
                    html = resp.text
                except Exception as e:
                    print(f"  [ERROR] Chyba při stahování stránky: {e}")
                    smart_sleep(args.delay, args.delay_jitter)
                    continue

                soup = BeautifulSoup(html, "html.parser")

                # 2) najít URL obrázku
                img_url = get_image_url_from_soup(
                    soup, product_url, args.img_selector, args.img_attr
                )
                if not img_url:
                    print("  [WARN] Nepodařilo se najít URL obrázku")
                    smart_sleep(args.delay, args.delay_jitter)
                    continue

                print(f"  [INFO] Nalezená URL obrázku: {img_url}")

                # 3) stáhnout obrázek
                img_bytes = download_image_bytes(img_url, timeout=args.timeout)
                if not img_bytes:
                    print("  [WARN] Obrázek se nepodařilo stáhnout")
                    smart_sleep(args.delay, args.delay_jitter)
                    continue

                print(f"  [OK] Obrázek stažen ({len(img_bytes)} bajtů)")

                # 4) uložit do DB
                try:
                    update_sql = sql.SQL(
                        "UPDATE {table} SET {img_col} = %s WHERE {id_col} = %s"
                    ).format(
                        table=sql.Identifier(args.table),
                        img_col=sql.Identifier(args.image_column),
                        id_col=sql.Identifier(args.id_column),
                    )
                    cur.execute(update_sql, (psycopg2.Binary(img_bytes), product_id))
                    conn.commit()
                    print("  [DB] Obrázek uložen do DB")
                except Exception as e:
                    conn.rollback()
                    print(f"  [ERROR] Chyba při UPDATE DB: {e}")

                # 5) delay s jitterem
                smart_sleep(args.delay, args.delay_jitter)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
