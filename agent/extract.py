"""Extraction: turn newsletter prose into structured funding deals.

This is the only "AI" step. We force a single tool call whose input schema is
the structure we want, which makes parsing deterministic. Scope is locked to
equity funding rounds INTO operating companies — fund launches, M&A, debt, and
firms merely quoted are excluded by the prompt.
"""
from anthropic import Anthropic

from . import config

_SYSTEM = """You extract venture funding rounds from the StrictlyVC newsletter.

Return ONLY funding rounds where investors put equity capital INTO an operating
company (seed, Series A/B/C, growth, strategic equity rounds, etc.).

EXCLUDE, and do not emit, any of the following:
- A firm launching or closing a new fund (that is not funding a company).
- Mergers, acquisitions, buyouts, or exits.
- Debt-only facilities, grants, secondaries, tender offers, IPOs.
- Firms or investors merely quoted, interviewed, or mentioned in a story with no
  associated round.

For each qualifying round, list every investor named:
- role: "lead" if described as leading/co-leading; otherwise "participation".
- is_individual: true for named human angels (e.g. "Elad Gil"), false for funds,
  firms, or corporate venture arms (e.g. "a16z", "Google Ventures", "Nvidia").
Use the investor's name exactly as written; do not normalize or expand it.
If amount is unclear, use null. If no qualifying rounds exist, return an empty list.
"""

_TOOL = {
    "name": "record_deals",
    "description": "Record the funding rounds found in the newsletter.",
    "input_schema": {
        "type": "object",
        "properties": {
            "deals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "round_type": {"type": ["string", "null"]},
                        "amount_usd": {"type": ["integer", "null"]},
                        "investors": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "role": {"type": "string",
                                             "enum": ["lead", "participation"]},
                                    "is_individual": {"type": "boolean"},
                                },
                                "required": ["name", "role", "is_individual"],
                            },
                        },
                    },
                    "required": ["company", "investors"],
                },
            }
        },
        "required": ["deals"],
    },
}


def extract_deals(issue_text: str) -> list[dict]:
    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.EXTRACT_MODEL,
        max_tokens=4096,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "record_deals"},
        messages=[{"role": "user", "content": issue_text[:120_000]}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_deals":
            return block.input.get("deals", [])
    return []
