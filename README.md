# 🚨 Cubex-Pattern Live Scanner → Telegram

Live NSE small/micro-cap scanner that detects the **"Cubex Tubings" pre-explosion
fingerprint** (stealth accumulation near beaten-down bases + quiet consecutive gains +
rising volume) using **yfinance only**, runs free on **GitHub Actions** during market
hours, and pushes alerts to your **Telegram**.

- Intraday scans every 15 min (09:30–15:30 IST) + end-of-day digest
- Volume is **time-scaled** intraday so morning scans aren't unfairly weak
- De-duplicated alerts (state committed back to repo) — no spam
- "EXPLODED — DO NOT CHASE" logic stops late alerts on circuit stocks
- Research tool — **not investment advice**. Micro-caps are highly risky.

## Repo layout
```
live_scanner.py    ← main: scan -> alert (runs in Actions or locally)
scanner_core.py    ← universe / data / features / Explosion Score
telegram_bot.py    ← Telegram sender + dedupe state (dry-run if no creds)
state/alerts_state.json   ← alert memory (auto-committed by the workflow)
.github/workflows/scanner.yml
requirements.txt
```

## 1-2-3 Setup

### 1) Create your Telegram bot (2 min)
1. In Telegram open **@BotFather** → `/newbot` → copy the **token**
2. Send any message to your new bot, then open:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   and copy your **`chat_id`** (the number inside `"chat":{"id":...}`)
   *(want group alerts? add the bot to the group and use the group's negative chat id)*

### 2) Push this folder to GitHub
```bash
git init && git add -A && git commit -m "live scanner"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 3) Add secrets & enable
Repo → **Settings → Secrets and variables → Actions → New repository secret**:
- `TELEGRAM_BOT_TOKEN` = your bot token
- `TELEGRAM_CHAT_ID` = your chat id

Then the **Actions** tab → enable workflows → run once manually via
*Run workflow* to confirm the first Telegram ping. Done — it now runs itself.

## Local use (laptop)
```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=123
python3 live_scanner.py                # live scan + alerts
python3 live_scanner.py --dry-run      # prints messages without sending
python3 live_scanner.py --digest       # force EOD digest now
python3 live_scanner.py --max 200 --min-score 45   # quick test
```

## Tuning (top of live_scanner.py)
- `min_score` (default **50**) — raise to 60–70 for fewer, stronger alerts
- `DEFAULT_CFG["universe_max"]` — 900 stocks ≈ 30–50 s per run
- Alert re-fire: same symbol same day re-alerts only if score **+10** higher
- **Private repos**: free Actions = 2,000 min/month — switch cron to `*/30` or EOD-only

## Universe filters (top of scanner_core.py)
- Market cap **₹20 Cr – ₹3,000 Cr**, NSE only, yfinance screener
- **Price ≥ ₹50** (`px_min`) — penny/operator quotes are auto-filtered (rating: ILLIQUID)
- 20-day avg volume ≥ 20,000 shares (liquidity floor); NaN-bar tails dropped

## Notes & honest caveats
- GitHub cron can be delayed a few minutes at peak; for true 15-min punctuality run
  the same script on a ₹0–400 VPS/Railway/Oracle-free-tier cron instead.
- Intraday volume scaling assumes a sqrt intraday volume curve; first 30–45 min of the
  session is unavoidably noisy — scores firm up after ~10:30 IST.
- This is a **radar, not a buy machine**: verify the corporate filing (BSE/NSE
  announcements) and the order book before every idea. Expect many duds.
