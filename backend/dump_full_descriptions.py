#!/usr/bin/env python3
import psycopg2
import json

# Tohle JE přesně ta konfigurace co používáš
DSN = "dbname=pc_configurator user=postgres password=autodoprava host=localhost port=5432"

def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, category, name, description
        FROM products
        ORDER BY id
    """)

    rows = cur.fetchall()

    data = [
        {
            "id": r[0],
            "category": r[1],
            "name": r[2],
            "description": r[3]
        }
        for r in rows
    ]

    with open("full_descriptions.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("Hotovo! Soubor full_descriptions.json byl vytvořen.")

if __name__ == "__main__":
    main()
