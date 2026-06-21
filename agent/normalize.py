"""Name normalization: collapse "a16z" / "Andreessen Horowitz", "Sequoia" /
"Sequoia Capital" to one firm. Counts are meaningless without this.

Three tiers, all of which write back into firm_aliases so the mapping stays
fast and human-curatable:
  1. exact alias hit (lowercased)
  2. match-key hit against existing canonical names (strip common suffixes)
  3. otherwise create a new firm and record the alias
"""
import re

from .db import _get_or_create_firm, now_iso

_SUFFIXES = {
    "capital", "ventures", "venture", "partners", "partner", "management",
    "group", "fund", "funds", "holdings", "labs", "lab", "co", "inc", "llc",
    "lp", "llp", "ltd", "advisors", "associates",
}


def _match_key(name: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    kept = [t for t in tokens if t not in _SUFFIXES]
    return " ".join(kept or tokens)


def normalize_firm(conn, raw_name: str, is_individual: bool = False) -> int:
    """Return the firm_id for raw_name, creating it if needed."""
    name = raw_name.strip()
    key = name.lower()

    # Tier 1: exact alias.
    row = conn.execute(
        "SELECT firm_id FROM firm_aliases WHERE alias = ?", (key,)
    ).fetchone()
    if row:
        _touch(conn, row["firm_id"])
        return row["firm_id"]

    # Tier 2: match-key against existing canonical names.
    target = _match_key(name)
    for frow in conn.execute("SELECT firm_id, canonical_name FROM firms"):
        if _match_key(frow["canonical_name"]) == target:
            conn.execute(
                "INSERT OR IGNORE INTO firm_aliases(alias, firm_id) VALUES (?, ?)",
                (key, frow["firm_id"]),
            )
            _touch(conn, frow["firm_id"])
            return frow["firm_id"]

    # Tier 3: brand-new firm.
    firm_id = _get_or_create_firm(conn, name, is_individual=is_individual)
    conn.execute(
        "INSERT OR IGNORE INTO firm_aliases(alias, firm_id) VALUES (?, ?)",
        (key, firm_id),
    )
    return firm_id


def _touch(conn, firm_id: int) -> None:
    conn.execute("UPDATE firms SET last_seen = ? WHERE firm_id = ?",
                 (now_iso(), firm_id))
