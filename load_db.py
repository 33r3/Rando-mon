"""
Download the required PokeAPI CSV files and load them into a local SQLite database.
Run once before using champ_team_gen.py.

Usage:
    python load_db.py [--db pokemon.db]
"""
import argparse
import csv
import io
import os
import sqlite3

import requests

BASE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/"
)

# Only the tables we actually need
TABLES = [
    "pokemon",
    "pokemon_types",
    "types",
    "pokemon_species",
    "pokemon_forms",
]


def fetch_csv(filename: str) -> list:
    url = BASE_URL + filename
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return list(csv.reader(io.StringIO(resp.text)))


def load_table(cur: sqlite3.Cursor, table: str) -> int:
    print(f"  Fetching {table}.csv …", end=" ", flush=True)
    rows = fetch_csv(f"{table}.csv")
    headers, data = rows[0], rows[1:]

    cols = ", ".join(f'"{h}" TEXT' for h in headers)
    cur.execute(f'DROP TABLE IF EXISTS "{table}"')
    cur.execute(f'CREATE TABLE "{table}" ({cols})')

    placeholders = ", ".join("?" for _ in headers)
    cur.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', data)
    print(f"{len(data)} rows")
    return len(data)


def main():
    parser = argparse.ArgumentParser(description="Load PokeAPI CSVs into SQLite")
    parser.add_argument("--db", default="pokemon.db", help="Output database path")
    args = parser.parse_args()

    if os.path.exists(args.db):
        print(f"Removing existing {args.db}")
        os.remove(args.db)

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    total = 0
    for table in TABLES:
        total += load_table(cur, table)

    # Lightweight indexes for the queries champ_team_gen.py runs
    cur.execute('CREATE INDEX idx_pt_pokemon ON pokemon_types(pokemon_id)')
    cur.execute('CREATE INDEX idx_pf_pokemon ON pokemon_forms(pokemon_id)')

    con.commit()
    con.close()
    print(f"\nDone — {total} total rows written to {args.db}")


if __name__ == "__main__":
    main()
