"""Recording: take extracted deals and write deals + appearance events.

Counting semantics implemented here:
  - one appearance per distinct (firm, deal) pair  -> UNIQUE constraint
  - lead and participation both recorded, both count equally (role stored)
  - named individuals are skipped (firms only)
  - re-processing is a no-op (INSERT OR IGNORE)

Cross-source dedup: a deal's identity is hash(normalized_company + normalized_round),
deliberately WITHOUT the issue date or source. So the same round reported by
StrictlyVC, Pro Rata, and Term Sheet on different days collapses to one deal, and
a firm is counted once for it. First source to record it wins (its date/source).
Limitation: a heuristic — if two sources name a company differently
("Acme" vs "Acme AI"), it won't merge. Tunable like the firm aliases.
"""
import hashlib
import re

from .normalize import normalize_firm

_COMPANY_DROP = {"inc", "incorporated", "llc", "corp", "corporation", "co",
                 "ltd", "limited", "gmbh", "ag", "sa", "plc", "lp", "llp"}
_ROUND_DROP = {"funding", "round", "financing", "equity", "capital", "investment"}


def _norm_company(name: str) -> str:
    toks = re.findall(r"[a-z0-9]+", (name or "").lower())
    if toks and toks[0] == "the":
        toks = toks[1:]
    toks = [t for t in toks if t not in _COMPANY_DROP]
    return " ".join(toks)


def _norm_round(round_type: str | None) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", (round_type or "").lower())
            if t not in _ROUND_DROP]
    return " ".join(toks)


def _deal_id(company: str, round_type: str | None) -> str:
    raw = f"{_norm_company(company)}|{_norm_round(round_type)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def record_deals(conn, issue_id: str, issue_date: str, deals: list[dict],
                 source: str = "unknown") -> set[int]:
    """Persist deals/appearances. Return the set of firm_ids newly touched."""
    touched: set[int] = set()

    for deal in deals:
        company = (deal.get("company") or "").strip()
        if not company:
            continue
        round_type = deal.get("round_type")
        deal_id = _deal_id(company, round_type)

        # First source to report a deal sets its row; later duplicates are ignored.
        conn.execute(
            "INSERT OR IGNORE INTO deals(deal_id, issue_id, company, round_type, amount_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (deal_id, issue_id, company, round_type, deal.get("amount_usd")),
        )

        for inv in deal.get("investors", []):
            name = (inv.get("name") or "").strip()
            if not name:
                continue
            if inv.get("is_individual"):
                continue  # firms only
            role = inv.get("role", "participation")
            firm_id = normalize_firm(conn, name)
            cur = conn.execute(
                "INSERT OR IGNORE INTO appearances(firm_id, deal_id, role, issue_date, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (firm_id, deal_id, role, issue_date, source),
            )
            if cur.rowcount:  # genuinely new (firm, deal) pair
                touched.add(firm_id)

    return touched
