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
- **Variables (optional):** `STRICTLYVC_FEED_URL` — defaults to
  `https://newsletter.strictlyvc.com/`. You can leave it unset. Point it at the
  newsletter homepage OR an RSS feed URL; given the homepage, the code
  auto-discovers the feed (and falls back to scraping issue links off the page).

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

## Query from Slack (optional add-on)

The daily job and CLI work without this. To query from inside Slack with a
`/firms` command, run the small web service in `agent/server.py`. It reads the
database your GitHub Action already commits — no second copy, no migration.

It needs an always-on host (a slash command must answer within 3 seconds), so a
free/sleeping tier won't work. Steps:

1. **Deploy the service (Render).** New + → Blueprint → connect this repo; Render
   reads `render.yaml` and creates an always-on web service (~$7/mo). Set env vars:
   `SLACK_SIGNING_SECRET` (Slack app → Basic Information → Signing Secret),
   `GITHUB_REPO` (e.g. `eng-2048/agent_alex`), and `GITHUB_TOKEN` only if your repo
   is private. Note the service's public URL, e.g. `https://agent-slack-query.onrender.com`.
2. **Add the slash command (Slack).** api.slack.com → your app → Slash Commands →
   Create New Command. Command `/firms`, Request URL
   `https://<your-render-url>/slack/firms`, then Save. Reinstall the app if prompted.
3. **Use it:**
   - `/firms` — all firms, all-time
   - `/firms list 180` — last 180 days
   - `/firms prolific` — at/above threshold in the last 180 days
   - `/firms prolific 5 90` — ≥5 in the last 90 days

Responses are visible only to whoever runs the command (ephemeral); change
`response_type` to `in_channel` in `server.py` to post for the whole channel.

## Multiple newsletters + backfill

The agent ingests several newsletters through pluggable **source adapters** in
`agent/sources.py`: `strictlyvc`, `prorata` (Axios Pro Rata), and `termsheet`
(Fortune Term Sheet). Set which run via `AGENT_SOURCES` (default: all three).

**Cross-source dedup.** The same funding round is covered by all three
newsletters on different days. A deal's identity is `hash(normalized_company +
normalized_round)` — no date, no source — so the same round collapses to one
deal and each firm is counted once for it, no matter how many newsletters
reported it. Each appearance is tagged with the newsletter that first recorded
it. (Heuristic: if two sources name a company differently, e.g. "Acme" vs
"Acme AI", it won't merge — tune like firm aliases.)

**Backfill a date range.** Populate history (and test collection) with:

```bash
# 1-month test window across all sources, starting clean:
python -m agent.backfill --since 2026-05-22 --reset

# specific range / specific sources:
python -m agent.backfill --since 2026-01-01 --until 2026-06-22 --sources prorata,termsheet
```

Backfill crawls each source's archive (axios.com and fortune.com put the date in
the URL, so dates are read from links; StrictlyVC uses its feed/homepage and
reaches only recent weeks for now). It does **not** fire Slack alerts unless you
pass `--alerts`. Because the deal identity changed, run the first backfill with
`--reset` so counts rebuild cleanly.

> The Pro Rata and Term Sheet adapters are best-effort and may need first-run
> tuning (archive URL / which links to keep) — which is why we validate on a
> short window before backfilling the year. Fortune's web paywall may also limit
> what Term Sheet returns; we confirm on the first run.

