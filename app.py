"""
Flask web server for Rando-mon.

Routes
------
GET  /                   → single-page UI
GET  /team/<token>       → same page; JS reads token from path and loads the team
GET  /api/team           → generate a new team (JSON)
GET  /api/team/<token>   → decode a token and return team info (JSON)

Query params for /api/team:
    trio=fgw|fds          lock the core trio
    legendary=true        include legendaries
    mythical=true         include mythicals
    seed=<int>            reproducible output
"""
import random
import sqlite3
import sys

from flask import Flask, abort, jsonify, render_template, request

from champ_team_gen import CORE_TRIOS, build_team
from team_link import decode, encode

app = Flask(__name__)
DB_PATH = "pokemon.db"


def _open_db() -> sqlite3.Connection:
    try:
        return sqlite3.connect(DB_PATH)
    except sqlite3.OperationalError:
        abort(503, f"Database '{DB_PATH}' not found — run load_db.py first.")


def _pokemon_row(cur: sqlite3.Cursor, pid: int, slot_index: int) -> dict:
    row = cur.execute(
        "SELECT identifier FROM pokemon WHERE id = ?", (pid,)
    ).fetchone()
    if not row:
        abort(404, f"Pokemon ID {pid} not found in database.")

    types = [
        r[0]
        for r in cur.execute(
            """SELECT t.identifier FROM pokemon_types pt
               JOIN types t ON pt.type_id = t.id
               WHERE pt.pokemon_id = ? ORDER BY pt.slot""",
            (pid,),
        ).fetchall()
    ]

    mega_capable = bool(
        cur.execute(
            """SELECT 1 FROM pokemon_forms pf
               JOIN pokemon p ON pf.pokemon_id = p.id
               WHERE p.species_id = (SELECT species_id FROM pokemon WHERE id = ?)
                 AND pf.is_mega = '1'
               LIMIT 1""",
            (pid,),
        ).fetchone()
    )

    return {
        "id": pid,
        "name": row[0].replace("-", " ").title(),
        "types": types,
        "is_mega_capable": mega_capable,
        "slot": "core" if slot_index < 3 else "free",
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
@app.route("/team/<token>")
def index(token=None):
    return render_template("index.html")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/team")
def api_generate():
    trio_key = request.args.get("trio") or random.choice(list(CORE_TRIOS))
    if trio_key not in CORE_TRIOS:
        abort(400, f"Unknown trio '{trio_key}'. Use 'fgw' or 'fds'.")

    seed = request.args.get("seed")
    if seed is not None:
        try:
            random.seed(int(seed))
        except ValueError:
            abort(400, "seed must be an integer.")

    allow_legendary = request.args.get("legendary", "").lower() == "true"
    allow_mythical = request.args.get("mythical", "").lower() == "true"

    con = _open_db()
    try:
        team = build_team(
            con.cursor(), CORE_TRIOS[trio_key], allow_legendary, allow_mythical
        )
    finally:
        con.close()

    token = encode([m["id"] for m in team])

    return jsonify(
        {
            "trio": CORE_TRIOS[trio_key],
            "team": [
                {
                    "id": m["id"],
                    "name": m["identifier"].replace("-", " ").title(),
                    "types": m["types"],
                    "is_mega_capable": m["is_mega_capable"],
                    "slot": "core" if i < 3 else "free",
                }
                for i, m in enumerate(team)
            ],
            "token": token,
        }
    )


@app.route("/api/team/<token>")
def api_decode(token):
    try:
        ids = decode(token)
    except ValueError as exc:
        abort(400, str(exc))

    con = _open_db()
    try:
        cur = con.cursor()
        team = [_pokemon_row(cur, pid, i) for i, pid in enumerate(ids)]
    finally:
        con.close()

    return jsonify({"team": team, "token": token})


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = 5000
    print(f"Starting Rando-mon on http://localhost:{port}")
    app.run(debug="--debug" in sys.argv, port=port)
