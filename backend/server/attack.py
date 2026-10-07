"""Demo: an attacker steals the database file plus one user's ABE key. What can they read?

    python -m server.attack                         # key of a GREEN user (data science)
    python -m server.attack tier:AMBER tier:GREEN "agent:Priya Nair"
    python -m server.attack --none                  # the database alone

The authority mints the key here only to stand in for "a key stolen from such a user".
Nothing below uses the server's code path or its clearance checks: just the file and the key.
"""

import secrets
import sqlite3
import sys
from collections import Counter

from server import abe, store


def attempt(db_path: str, attrs: set[str] | None) -> Counter:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    key = {"id": f"attacker|{secrets.token_hex(4)}", **store.authority().keygen(attrs)} if attrs is not None else None
    out = Counter()
    for r in db.execute("SELECT call_id, tier FROM copies"):
        try:
            if key is None:
                raise abe.PolicyNotSatisfied("no key")
            store.open_copy(db, r["call_id"], r["tier"], key)
            out[(r["tier"], "opened")] += 1
        except abe.PolicyNotSatisfied:
            out[(r["tier"], "refused")] += 1
    return out


def main(argv: list[str]) -> None:
    attrs = None if argv == ["--none"] else set(argv or ["tier:GREEN"])
    res = attempt(store.DB_PATH, attrs)
    print(f"Stolen: {store.DB_PATH} + key for {sorted(attrs) if attrs is not None else 'nothing'}")
    for tier in ("RED", "AMBER", "GREEN"):
        print(f"  {tier:5}  opened {res[(tier, 'opened')]:3}   refused {res[(tier, 'refused')]:3}")


if __name__ == "__main__":
    main(sys.argv[1:])
