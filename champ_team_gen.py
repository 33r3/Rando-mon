"""
Generate a semi-random Pokemon champion team.

Rules
-----
* Core trio  — one of two fixed type combos (chosen randomly unless --trio is given):
    fgw  →  Fire / Grass / Water
    fds  →  Fairy / Dragon / Steel
* Free-fill  — 3 additional slots drawn with type-spread weighting so new types are
  preferred over already-covered ones.
* Mega guarantee — mega-capable pokemon receive a draw bonus (MEGA_WEIGHT). The
  final free-fill slot is restricted to mega-capable only if the team has none yet.

Usage
-----
    python champ_team_gen.py
    python champ_team_gen.py --trio fds --legendary
"""
import argparse
import random
import sqlite3
import sys

from team_link import encode

DB_PATH = "pokemon.db"

CORE_TRIOS = {
    "fgw": ["fire", "grass", "water"],
    "fds": ["fairy", "dragon", "steel"],
}

MEGA_WEIGHT = 4  # draw multiplier for mega-capable pokemon


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _mega_capable_species(cur: sqlite3.Cursor) -> set:
    """Return set of species_ids that have at least one mega form."""
    rows = cur.execute("""
        SELECT DISTINCT CAST(p.species_id AS INTEGER)
        FROM pokemon_forms pf
        JOIN pokemon p ON pf.pokemon_id = p.id
        WHERE pf.is_mega = '1'
    """).fetchall()
    return {r[0] for r in rows}


def get_candidates(cur: sqlite3.Cursor, allow_legendary: bool, allow_mythical: bool) -> list:
    """
    Return all eligible pokemon as dicts with keys:
        id, identifier, species_id, types (list), is_mega_capable (bool)
    """
    extra = []
    if not allow_legendary:
        extra.append("AND ps.is_legendary = '0'")
    if not allow_mythical:
        extra.append("AND ps.is_mythical = '0'")

    mega_species = _mega_capable_species(cur)

    rows = cur.execute(f"""
        SELECT p.id, p.identifier, p.species_id
        FROM pokemon p
        JOIN pokemon_species ps ON p.species_id = ps.id
        WHERE p.is_default = '1'
          AND ps.id IS NOT NULL
          {" ".join(extra)}
        ORDER BY CAST(p.id AS INTEGER)
    """).fetchall()

    candidates = []
    for pid, ident, species_id in rows:
        type_rows = cur.execute("""
            SELECT t.identifier
            FROM pokemon_types pt
            JOIN types t ON pt.type_id = t.id
            WHERE pt.pokemon_id = ?
            ORDER BY pt.slot
        """, (pid,)).fetchall()
        candidates.append({
            "id": int(pid),
            "identifier": ident,
            "species_id": int(species_id),
            "types": [r[0] for r in type_rows],
            "is_mega_capable": int(species_id) in mega_species,
        })

    return candidates


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _draw_weight(mon: dict, covered: set, mega_boost: bool) -> float:
    new_types = sum(1 for t in mon["types"] if t not in covered)
    type_score = max(new_types, 0.5)  # floor keeps every candidate drawable
    mega_score = MEGA_WEIGHT if (mega_boost and mon["is_mega_capable"]) else 1
    return type_score * mega_score


def weighted_draw(pool: list, covered: set, mega_boost: bool) -> dict:
    weights = [_draw_weight(m, covered, mega_boost) for m in pool]
    return random.choices(pool, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Team building
# ---------------------------------------------------------------------------

def build_team(
    cur: sqlite3.Cursor,
    trio_types: list,
    allow_legendary: bool,
    allow_mythical: bool,
) -> list:
    candidates = get_candidates(cur, allow_legendary, allow_mythical)

    by_type: dict = {}
    for c in candidates:
        for t in c["types"]:
            by_type.setdefault(t, []).append(c)

    team: list = []
    used_ids: set = set()
    covered: set = set()

    # — Core trio: one pokemon per required type, mega-weighted —
    for type_name in trio_types:
        pool = [c for c in by_type.get(type_name, []) if c["id"] not in used_ids]
        if not pool:
            sys.exit(f"No candidates found for required type '{type_name}'. "
                     "Try --legendary or --mythical to widen the pool.")
        weights = [MEGA_WEIGHT if c["is_mega_capable"] else 1 for c in pool]
        pick = random.choices(pool, weights=weights, k=1)[0]
        team.append(pick)
        used_ids.add(pick["id"])
        covered.update(pick["types"])

    # — Free-fill: 3 slots, type-spread + mega-weighted —
    remaining = [c for c in candidates if c["id"] not in used_ids]

    for slot_idx in range(3):
        if not remaining:
            break

        has_mega = any(m["is_mega_capable"] for m in team)
        is_last_slot = (slot_idx == 2)

        # Guarantee ≥1 mega-capable by constraining the last free slot if needed
        pool = remaining
        if is_last_slot and not has_mega:
            mega_pool = [c for c in remaining if c["is_mega_capable"]]
            if mega_pool:
                pool = mega_pool

        pick = weighted_draw(pool, covered, mega_boost=not has_mega)
        team.append(pick)
        used_ids.add(pick["id"])
        covered.update(pick["types"])
        remaining = [c for c in remaining if c["id"] not in used_ids]

    return team


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate a champion Pokemon team")
    parser.add_argument("--trio", choices=list(CORE_TRIOS), default=None,
                        help="Core trio: fgw=Fire/Grass/Water, fds=Fairy/Dragon/Steel "
                             "(default: random)")
    parser.add_argument("--legendary", action="store_true",
                        help="Include legendary pokemon in the pool")
    parser.add_argument("--mythical", action="store_true",
                        help="Include mythical pokemon in the pool")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    trio_key = args.trio or random.choice(list(CORE_TRIOS))
    trio_types = CORE_TRIOS[trio_key]

    try:
        con = sqlite3.connect(DB_PATH)
    except sqlite3.OperationalError:
        sys.exit(f"Cannot open database '{DB_PATH}'. Run load_db.py first.")

    team = build_team(con.cursor(), trio_types, args.legendary, args.mythical)
    con.close()

    # — Display —
    trio_label = " / ".join(t.capitalize() for t in trio_types)
    print(f"\nCore trio  : {trio_label}")
    print(f"Legendaries: {'yes' if args.legendary else 'no'}   "
          f"Mythicals: {'yes' if args.mythical else 'no'}\n")

    type_width = max(
        len("/".join(t.capitalize() for t in m["types"])) for m in team
    )

    mega_count = 0
    for i, mon in enumerate(team, 1):
        name = mon["identifier"].replace("-", " ").title()
        types = "/".join(t.capitalize() for t in mon["types"])
        mega_tag = " ★" if mon["is_mega_capable"] else "  "
        slot_tag = "[core]" if i <= 3 else "[free]"
        print(f"  {i}. {name:<22} {types:<{type_width}}{mega_tag}  {slot_tag}")
        if mon["is_mega_capable"]:
            mega_count += 1

    ids = [m["id"] for m in team]
    token = encode(ids)

    print(f"\n  Mega-capable: {mega_count}/6  (★)")
    print(f"  Token       : {token}")
    print(f"  Share       : /team/{token}")


if __name__ == "__main__":
    main()
