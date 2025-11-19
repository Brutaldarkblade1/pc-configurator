#!/usr/bin/env python3
import psycopg2

# <<< UPRAV PODLE SEBE >>>
DSN = "dbname=pc_configurator user=postgres password=autodoprava host=localhost port=5432"

def main():
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM products;")
            total = cur.fetchone()[0]

            cur.execute("""
                SELECT count(*)
                FROM products
                WHERE url IS NOT NULL AND btrim(url) <> ''
            """)
            with_url = cur.fetchone()[0]

        print(f"Products celkem: {total}")
        print(f"Products s URL:  {with_url}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
