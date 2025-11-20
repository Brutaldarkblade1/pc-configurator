import os
import psycopg2
import re
import unicodedata
import difflib

# ---- 1. DB připojení (změň, pokud máš jiné) ----
DB_DSN = "postgresql://postgres:autodoprava@localhost:5432/pc_configurator"

# ---- 2. Složka s obrázky ----
IMG_DIR = "img"  # uvnitř backend/

# jak moc agresivní má být fuzzy match (0–1, čím víc, tím přísnější)
FUZZY_CUTOFF = 0.78


def strip_accents(s: str) -> str:
    """Odstraní diakritiku (černá -> cerna)."""
    return ''.join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def normalize_name(name: str) -> str:
    """
    Udělá z názvu něco, co vypadá podobně jako slug souboru:
    - lower
    - bez diakritiky
    - mezery -> '-'
    - vyhodí vše kromě [a-z0-9-]
    """
    n = name.strip().lower()
    n = strip_accents(n)
    n = n.replace(" ", "-")
    n = re.sub(r"[^a-z0-9\-]", "", n)
    return n


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    print("[INFO] Načítám produkty z databáze...")
    cur.execute("SELECT id, name FROM products;")
    rows = cur.fetchall()
    print(f"[INFO] Nalezeno {len(rows)} produktů.")

    files = os.listdir(IMG_DIR)

    # mapa -> normalizovaný název -> seznam souborů (kdyby náhodou víc stejných)
    normalized_map: dict[str, list[str]] = {}
    for f in files:
        base, ext = os.path.splitext(f)
        norm = normalize_name(base)
        normalized_map.setdefault(norm, []).append(f)

    used_files = set()  # aby jeden obrázek nepřiřadilo k deseti produktům
    missing_exact = []  # produkty bez přesné shody
    renamed_exact = 0
    renamed_fuzzy = 0

    # ---- 1. Krok: přesné shody ----
    print("\n[STEP 1] Přesné shody podle normalizovaného názvu")
    for product_id, name in rows:
        norm_name = normalize_name(name)

        if norm_name not in normalized_map:
            missing_exact.append((product_id, name, norm_name))
            continue

        # vezmeme první soubor se stejným norm názvem
        old_filename = None
        for candidate in normalized_map[norm_name]:
            if candidate not in used_files:
                old_filename = candidate
                break

        if not old_filename:
            # všechny soubory pro tenhle norm_název už byly přiřazeny
            missing_exact.append((product_id, name, norm_name))
            continue

        _, ext = os.path.splitext(old_filename)
        new_filename = f"{product_id}{ext}"

        old_path = os.path.join(IMG_DIR, old_filename)
        new_path = os.path.join(IMG_DIR, new_filename)

        if os.path.exists(new_path):
            print(f"[SKIP] {new_filename} už existuje, přeskočeno.")
            used_files.add(old_filename)
            continue

        if not os.path.exists(old_path):
            print(f"[WARN] Původní soubor {old_filename} neexistuje, přeskočeno.")
            used_files.add(old_filename)
            continue

        os.rename(old_path, new_path)
        used_files.add(old_filename)
        print(f"[OK] {old_filename} → {new_filename}")
        renamed_exact += 1

    # ---- 2. Krok: fuzzy shody pro to, co zbylo ----
    print("\n[STEP 2] Fuzzy shody (podobné názvy)")
    all_norm_keys = list(normalized_map.keys())

    still_missing = []
    for product_id, name, norm_name in missing_exact:
        if not all_norm_keys:
            still_missing.append((product_id, name))
            continue

        # najdeme nejbližší klíče podle podobnosti
        best_match = None
        best_ratio = 0.0

        for key in all_norm_keys:
            ratio = difflib.SequenceMatcher(None, norm_name, key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = key

        if not best_match or best_ratio < FUZZY_CUTOFF:
            # nic dostatečně podobného
            still_missing.append((product_id, name))
            print(f"[FUZZY-NO] {product_id} | {name} (norm='{norm_name}') -> žádná dost podobná shoda (max ratio={best_ratio:.2f})")
            continue

        # máme kandidáta
        candidate_files = normalized_map[best_match]
        old_filename = None
        for candidate in candidate_files:
            if candidate not in used_files:
                old_filename = candidate
                break

        if not old_filename:
            still_missing.append((product_id, name))
            print(f"[FUZZY-SKIP] {product_id} | {name} -> '{best_match}', ale všechny soubory už použity.")
            continue

        _, ext = os.path.splitext(old_filename)
        new_filename = f"{product_id}{ext}"

        old_path = os.path.join(IMG_DIR, old_filename)
        new_path = os.path.join(IMG_DIR, new_filename)

        if os.path.exists(new_path):
            print(f"[FUZZY-SKIP] {new_filename} už existuje, přeskočeno (match='{best_match}', ratio={best_ratio:.2f}).")
            used_files.add(old_filename)
            continue

        if not os.path.exists(old_path):
            print(f"[FUZZY-WARN] Původní soubor {old_filename} neexistuje, přeskočeno (match='{best_match}', ratio={best_ratio:.2f}).")
            used_files.add(old_filename)
            continue

        os.rename(old_path, new_path)
        used_files.add(old_filename)
        print(f"[FUZZY-OK] {old_filename} → {new_filename} (produkt {product_id} | '{name}', match='{best_match}', ratio={best_ratio:.2f})")
        renamed_fuzzy += 1

    print("\n[DONE] Přejmenovávání dokončeno!")
    print(f"  Přesné shody: {renamed_exact}")
    print(f"  Fuzzy shody:  {renamed_fuzzy}")

    if still_missing:
        print("\n[INFO] Produkty, které stále nemají přiřazený obrázek:")
        for pid, name in still_missing:
            print(f"  - {pid} | {name}")
    else:
        print("\n[INFO] Všechny produkty mají nějaký obrázek.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
