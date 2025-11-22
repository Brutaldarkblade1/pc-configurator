#!/usr/bin/env python3
import argparse
from typing import List

import psycopg2
from psycopg2.extras import DictCursor


def find_duplicate_names(cur):
    """
    Vrátí seznam jmen, která se v products vyskytují víc než jednou.
    """
    cur.execute(
        """
        SELECT name, COUNT(*) AS cnt
        FROM products
        GROUP BY name
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC, name ASC;
        """
    )
    return cur.fetchall()


def get_products_by_name(cur, name: str):
    """
    Vrátí všechny produkty se zadaným jménem.
    """
    cur.execute(
        """
        SELECT id, name, category, brand, price, source, url
        FROM products
        WHERE name = %s
        ORDER BY id ASC;
        """,
        (name,),
    )
    return cur.fetchall()


def print_group(name: str, rows):
    print("\n========================================")
    print(f"Jméno produktu: {name}")
    print("Duplicity:")
    for row in rows:
        print(
            f"  ID={row['id']} | cat={row['category']} | brand={row['brand']} | "
            f"price={row['price']} | source={row['source']} | url={row['url']}"
        )


def ask_ids_to_delete(rows) -> List[int]:
    """
    Zeptá se uživatele, která ID chce smazat.
    Vrací seznam ID ke smazání.
    """
    all_ids = [str(r["id"]) for r in rows]

    while True:
        print("\nCo chceš udělat?")
        print("  - zadej ID, která chceš SMAZAT (oddělené čárkou nebo mezerou)")
        print("  - nebo 'k' = smazat všechny kromě nejmenšího ID")
        print("  - nebo Enter = přeskočit tuto skupinu")

        answer = input("Volba: ").strip()

        if answer == "":
            # přeskočit
            return []

        if answer.lower() == "k":
            # keep lowest ID, ostatní smazat
            sorted_rows = sorted(rows, key=lambda r: r["id"])
            keep_id = sorted_rows[0]["id"]
            delete_ids = [r["id"] for r in sorted_rows[1:]]
            print(f"  → Zachovám ID={keep_id}, smažu: {delete_ids}")
            confirm = input("Potvrdit? [y/N]: ").strip().lower()
            if confirm == "y":
                return delete_ids
            else:
                continue

        # ruční zadání ID
        parts = answer.replace(",", " ").split()
        if not parts:
            print("Nic jsi nezadal, zkus to znovu.")
            continue

        # kontrola, že jsou to validní ID z této skupiny
        invalid = [p for p in parts if p not in all_ids]
        if invalid:
            print(f"Neplatná ID pro tuto skupinu: {invalid}")
            print(f"Platná ID jsou: {', '.join(all_ids)}")
            continue

        delete_ids = [int(p) for p in parts]
        print(f"  → Smažu ID: {delete_ids}")
        confirm = input("Potvrdit? [y/N]: ").strip().lower()
        if confirm == "y":
            return delete_ids
        # jinak znova


def delete_products(cur, ids_to_delete: List[int], dry_run: bool):
    if not ids_to_delete:
        return

    if dry_run:
        print(f"[DRY-RUN] Nesmažu nic, ale smazal bych ID: {ids_to_delete}")
        return

    cur.execute(
        "DELETE FROM products WHERE id = ANY(%s);",
        (ids_to_delete,),
    )
    print(f"[OK] Smazaná ID: {ids_to_delete}")


def main():
    parser = argparse.ArgumentParser(
        description="Najde a smaže duplicitní produkty se stejným jménem."
    )
    parser.add_argument(
        "--dsn",
        default="postgresql://postgres:autodoprava@localhost:5432/pc_configurator",
        help="DSN pro připojení k PostgreSQL (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Jen ukáže, co by se mazalo, ale nic neodstraní.",
    )

    args = parser.parse_args()

    print(f"[INFO] Připojuju se k DB: {args.dsn}")
    conn = psycopg2.connect(args.dsn)
    conn.autocommit = False  # chceme transakci

    try:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            duplicates = find_duplicate_names(cur)
            if not duplicates:
                print("Nebyly nalezeny žádné duplicity podle jména. 🎉")
                return

            print(f"[INFO] Nalezeno {len(duplicates)} různých duplicitních jmen.")

            all_ids_to_delete: List[int] = []

            for row in duplicates:
                name = row["name"]
                count = row["cnt"]
                print(f"\n----------------------------------------")
                print(f"Jméno '{name}' má {count} záznamů:")

                rows = get_products_by_name(cur, name)
                print_group(name, rows)

                ids_to_delete = ask_ids_to_delete(rows)
                all_ids_to_delete.extend(ids_to_delete)
                delete_products(cur, ids_to_delete, dry_run=args.dry_run)

            if args.dry_run:
                print("\n[DRY-RUN] Změny NEBYLY uloženy (rollback).")
                conn.rollback()
            else:
                print("\nShrnutí:")
                print(f"  Celkem k odstranění: {len(all_ids_to_delete)} záznamů.")
                confirm_all = input("Zapsat změny do DB (COMMIT)? [y/N]: ").strip().lower()
                if confirm_all == "y":
                    conn.commit()
                    print("[OK] Změny uloženy.")
                else:
                    conn.rollback()
                    print("[INFO] Změny vráceny (ROLLBACK). Nic se neuložilo.")

    finally:
        conn.close()
        print("[INFO] Připojení k DB uzavřeno.")


if __name__ == "__main__":
    main()
