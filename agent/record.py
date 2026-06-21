"""Recording: take extracted deals and write deals + appearance events.

Counting semantics implemented here:
  - one appearance per distinct (firm, deal) pair  -> UNIQUE constraint
  - lead and participation both recorded, both count equally (role stored)
  - named individuals are skipped (firms only)
  - re-processing is a no-op (INSERT OR IGNORE)
"""
import hashlib

from .normalize import normalize_firm


def _deal_id(company: str, round_type: str | None, issue_date: str) -> str:
    raw = f"{company.strip().lower()}|{(round_type or '').strip().lower()}|{issue_date}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def record_deals(conn, issue_id: str, issue_date: str, deals: list[dict]) -> set[int]:
    """Persist deals/appearances. Return the set of firm_ids touched this run."""
    touched: set[int] = set()

    for deal in deals:
        company = (deal.get("company") or "").strip()
        if not company:
            continue
        round_type = deal.get("round_type")
        deal_id = _deal_id(company, round_type, issue_date)

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
                "INSERT OR IGNORE INTO appearances(firm_id, deal_id, role, issue_date) "
                "VALUES (?, ?, ?, ?)",
                (firm_id, deal_id, role, issue_date),
            )
            if cur.rowcount:  # genuinely new appearance
                touched.add(firm_id)

    return touched
