#!/usr/bin/env python3
"""
LIVE_SCANNER.PY - live-market Cubex-pattern scanner with Telegram alerts
=========================================================================
Runs on GitHub Actions (see .github/workflows/scanner.yml) or anywhere else.
Uses yfinance only. During market hours the forming daily bar is included and
today's volume is time-scaled so morning scans aren't penalised.

Modes:
  python3 live_scanner.py                # auto: intraday scan (and EOD digest after close)
  python3 live_scanner.py --digest       # force EOD-style digest message
  python3 live_scanner.py --dry-run      # print messages instead of sending
  python3 live_scanner.py --max 200      # smaller universe (quick test)
  python3 live_scanner.py --min-score 55 # custom alert threshold

Env:  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (add as GitHub repo Secrets)
NOT investment advice. Micro-cap patterns fail often - verify before acting.
"""
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import scanner_core as core
import telegram_bot as tg

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_CFG = dict(
    universe_max=900,
    threads=8,
    min_score=50,              # instant-alert threshold
    alert_verdicts=("PRE-EXPLOSION SETUP", "WARMING UP - WATCH"),
    digest_top=10,             # EOD digest size
    state=Path(__file__).parent / "state" / "alerts_state.json",
)

def volume_time_scale(now_ist):
    """Expected fraction of the day's volume done by time-of-day (NSE curve),
    returns multiplier to blow today's partial volume up to full-day equivalent.
    After 15:30 -> 1.0 (bar complete)."""
    t = now_ist.hour * 60 + now_ist.minute
    open_m, close_m = 9 * 60 + 15, 15 * 60 + 30
    if t >= close_m or now_ist.weekday() >= 5: return 1.0
    if t < open_m: return 1.0
    elapsed = t - open_m
    # front-loaded curve approx: frac = sqrt(elapsed / 375)
    frac = max((elapsed / 375.0) ** 0.5, 0.08)
    return min(1.0 / frac, 10.0)

def fmt_alert(r):
    tv = f"https://in.tradingview.com/chart/?symbol=NSE:{r['symbol'].replace('.NS','')}"
    icon = "🚨" if r["verdict"] == "PRE-EXPLOSION SETUP" else "⚡"
    return (
        f"{icon} <b>{r['verdict']}</b>\n"
        f"<b>{r['symbol'].replace('.NS','')}</b>  <a href='{tv}'>chart</a>\n\n"
        f"💰 ₹{r['close']}  ({r['day_ret']:+.1f}% today)\n"
        f"📊 Score: <b>{r['score']}/100</b>   MC ₹{r['mcap_cr']:.0f} Cr\n"
        f"📈 {r['consec_up']} green days | 5d vol {r['vol_ratio']}x | "
        f"{r['dd52']}% off 52wH | tight {r['tight']}\n\n"
        f"<i>{'; '.join(r.get('why', [])[:5])}</i>\n\n"
        f"🔎 Verify BSE/NSE filings (fund-raise/news) before acting. "
        f"Micro-cap = illiquid & high risk.\n"
        f"🕐 {datetime.now(IST).strftime('%d-%b %H:%M IST')}"
    )

def fmt_digest(df, bar_date):
    lines = [f"📋 <b>Scanner EOD Digest — {bar_date}</b>",
             f"NSE small/micro caps, fingerprint ranking:\n"]
    for i, (_, r) in enumerate(df.iterrows(), 1):
        tag = "🔥" if r["verdict"] == "PRE-EXPLOSION SETUP" else ("⚡" if "WARMING" in r["verdict"] else "•")
        lines.append(f"{i}. {tag} <b>{r['symbol'].replace('.NS','')}</b> {r['score']}  "
                     f"₹{r['close']} ({r['day_ret']:+.1f}%) vol{r['vol_ratio']}x {r['dd52']}%offH")
    lines.append("\n⚠️ Research alerts, not advice. Check filings & liquidity first.")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=DEFAULT_CFG["universe_max"])
    ap.add_argument("--symbols", nargs="+", help="scan only these (e.g. CUBEXTUB.NS)")
    ap.add_argument("--threads", type=int, default=DEFAULT_CFG["threads"])
    ap.add_argument("--min-score", type=int, default=DEFAULT_CFG["min_score"])
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--top-print", type=int, default=15)
    a = ap.parse_args()
    if a.dry_run:
        import os
        os.environ.pop("TELEGRAM_BOT_TOKEN", None); os.environ.pop("TELEGRAM_CHAT_ID", None)

    now = datetime.now(IST)
    scale = volume_time_scale(now)
    print(f"[{now.strftime('%Y-%m-%d %H:%M IST')}] universe max={a.max} vol-scale={scale:.2f}")

    if a.symbols:
        uni = [(s.upper(), 0) for s in a.symbols]
    else:
        uni = core.get_universe(a.max)
    print(f"universe: {len(uni)} symbols")
    mcaps = dict(uni)

    rows = []
    def work(sym, mc):
        df = core.fetch_history(sym)
        if df is None: return None
        if not mc:
            try:
                import yfinance as yf
                fi = yf.Ticker(sym).fast_info
                mc = (getattr(fi, "market_cap", None) or 0) / 1  # rupees
            except Exception:
                mc = 0
        f = core.compute_features(df, mc, today_vol_scale=scale)
        sc, verdict, why = core.score_symbol(f, core.CFG["thr"])
        return dict(symbol=sym, score=sc, verdict=verdict, why=why, **f)

    done = 0
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        futs = {ex.submit(work, s, m): s for s, m in uni}
        for fut in as_completed(futs):
            done += 1
            if done % 200 == 0: print(f"  {done}/{len(uni)} ...")
            try:
                r = fut.result()
                if r: rows.append(r)
            except Exception:
                pass
    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    out = Path(__file__).parent / "output"; out.mkdir(exist_ok=True)
    df.drop(columns=["why"], errors="ignore").to_csv(out / f"live_{now.strftime('%Y%m%d_%H%M')}.csv", index=False)

    bar_date = df["last_bar"].mode().iat[0] if len(df) else str(now.date())
    print(f"scan done: {len(df)} symbols | latest bar: {bar_date}")
    cols = ["symbol", "score", "verdict", "close", "day_ret", "consec_up", "vol_ratio", "dd52", "tight"]
    print(df.head(a.top_print)[cols].to_string(index=False))

    # ---------------- alerts ----------------
    state = tg.load_state()
    sent = 0
    cand = df[(df.score >= a.min_score) & (df.verdict.isin(DEFAULT_CFG["alert_verdicts"]))]
    for _, r in cand.iterrows():
        if tg.already_alerted(state, r["symbol"], bar_date, r["score"]):
            continue
        if tg.send(fmt_alert(r)) or a.dry_run:
            tg.mark_alerted(state, r["symbol"], bar_date, r["score"])
            sent += 1
    # EOD digest: after close, or on demand
    after_close = now.weekday() < 5 and (now.hour * 60 + now.minute) >= 15 * 60 + 25
    if (a.digest or after_close) and not a.dry_run or (a.digest and a.dry_run):
        key = f"_digest_{bar_date}"
        if not state.get(key):
            top = df[df.verdict != "IGNORE"].head(DEFAULT_CFG["digest_top"])
            if len(top):
                tg.send(fmt_digest(top, bar_date))
                state[key] = True
    tg.save_state(state)
    print(f"alerts sent: {sent} (+ digest {'yes' if (a.digest or after_close) else 'no'})")

if __name__ == "__main__":
    main()
