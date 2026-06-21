# Agent

Tracks prolific VC firms from the [StrictlyVC](https://newsletter.strictlyvc.com)
newsletter. Each weekday it reads the latest issue, extracts the firms that
funded companies, counts how often each appears in a rolling window, and posts a
Slack alert the moment a firm crosses the threshold.

**Design principle:** the LLM does only the fuzzy work (reading prose, flagging
individuals); all counting, thresholds, and alert state live in plain,
auditable code.

## How it works

```
RSS feed ──▶ fetch issue text ──▶ LLM extract deals ──▶ normalize firm names
   │                                                          │
   └────────────────────────────────────────────────────────▼
                              appearances event log (SQLite)
                                          │
                        ┌─────────────────┴─────────────────┐
                   alert (Slack)                       query (CLI)
```

The database (`data/agent.db`) is committed back to the repo after each run —
that's the persistence layer, since GitHub Actions runners are ephemeral.

## Counting semantics

- One appearance per distinct **(firm, deal)** pair — a firm in three rounds in one
  issue counts three times.
- **Lead** and **participation** both stored, both count equally for the threshold.
- Named **individuals** (angels) are excluded; firms/funds only.
- Only **equity funding rounds into companies** — fund launches, M&A, debt, and
  quoted mentions are excluded by the extraction prompt.
- The alert fires **once on crossing** `THRESHOLD` (default 5) within
  `WINDOW_DAYS` (default 90) and **re-arms** if the count later drops below.

## Create the repo

```bash
# from the unzipped folder
git init
git add .
git commit -m "Initial commit: Agent"
git branch -M main
git remote add origin git@github.com:<you>/agent.git
git push -u origin main
```

## Configure (3 things)

In your repo's **Settings → Secrets and variables → Actions**:

- **Secrets:** `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`
- **Variables:** `STRICTLYVC_FEED_URL` — the beehiiv RSS feed URL. To find it,
  open the newsletter homepage, view source, and copy the
  `<link rel="alternate" type="application/rss+xml" href="...">` value.
  (A placeholder default is set in `config.py`; replace it.)

The schedule is in `.github/workflows/daily.yml` (weekdays, 18:00 UTC). Trigger a
first run manually from the **Actions** tab → **agent-daily** → **Run workflow**.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your keys + feed URL
python -m agent.run       # ingest + extract + alert
```

## Query

```bash
python -m agent.query list                  # all firms, all-time
python -m agent.query list --window 180     # last 6 months
python -m agent.query prolific --min 5 --window 180
```

## Tuning notes

- **Extraction accuracy is the real bottleneck.** Hand-check the first few days of
  output and label a handful of past issues as a tiny eval set before trusting
  counts. Swap `AGENT_MODEL` to a stronger/cheaper model as needed.
- **Aliases** are your main lever: edit `seeds/aliases.json`, or rows accumulate in
  the `firm_aliases` table as the system runs. Fixing a mis-merge there reshapes
  counts without re-ingesting.
- The alert window and any query window are independent.
