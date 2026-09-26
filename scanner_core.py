#!/usr/bin/env python3
"""
scanner_core.py - shared engine: universe, data, features, Explosion Score.
The "Cubex fingerprint": base + stealth accumulation + (optional) event trigger.
No look-ahead, works with a partial live bar (volume time-scaled upstream).
"""
import sys, time
import pandas as pd

CFG = dict(
    mcap_min=20e7, mcap_max=3000e7,      # ~Rs 20 Cr .. 3,000 Cr
    px_min=5.0, px_max=5000.0,
    min_vol20=20_000,
    thr=dict(consec_up=3, upvol_skew=1.4, vol_ratio_5_60=1.25, dd52_min=22,
             low52_max=15, tightness=0.85, single_day_cap=6.5,
             explode_days=9.5, explode_ret10=45),
)

def get_universe(max_n=900):
    """NSE micro/small caps via yfinance screener (paginated)."""
    from yfinance.screener import screen, EquityQuery
    q = EquityQuery("and", [EquityQuery("eq", ["exchange", "NSI"]),
                            EquityQuery("gt", ["intradaymarketcap", CFG["mcap_min"]]),
                            EquityQuery("lt", ["intradaymarketcap", CFG["mcap_max"]])])
    out, off = [], 0
    while len(out) < max_n:
        try:
            r = screen(q, offset=off, size=min(250, max_n - len(out)),
                       sortField="dayvolume", sortAsc=False)
        except Exception as e:
            print(f"[universe] page err @{off}: {e}", file=sys.stderr); break
        qs = r.get("quotes", [])
        if not qs: break
        for x in qs:
            s = x.get("symbol")
            if s and s.endswith(".NS"):
                out.append((s, x.get("marketCap") or 0))
        off += len(qs)
        if len(qs) < 250: break
    return out

def fetch_history(sym, retries=2):
    import yfinance as yf
    for _ in range(retries + 1):
        try:
            df = yf.Ticker(sym).history(period="1y", interval="1d", auto_adjust=True)
            if df is not None and len(df) >= 130:
                return df.dropna(subset=["Close"]).tail(400)
        except Exception:
            time.sleep(0.4)
    return None

def compute_features(df, mcap=0, today_vol_scale=1.0):
    """today_vol_scale: >1 inflates today's partial intraday volume to a full-day
    expectation so morning volume isn't unfairly penalised."""
    c = df["Close"].astype(float)
    v = df["Volume"].reindex(df.index).fillna(0).astype(float).copy()
    if today_vol_scale > 1.0:
        v.iloc[-1] = v.iloc[-1] * today_vol_scale
    ret = c.pct_change() * 100
    last = c.iloc[-1]
    hi52, lo52 = c.max(), c.min()
    up = 0
    for r in ret.iloc[-10:][::-1]:
        if r > 0.05: up += 1
        else: break
    r5, prev60 = v.iloc[-5:].mean(), v.iloc[-65:-5].mean()
    vol5_60 = r5 / prev60 if prev60 > 0 else 0
    vol20 = v.iloc[-20:].mean()
    upv = v[ret > 0.05].iloc[-10:].mean() if (ret.iloc[-10:] > 0.05).any() else 0
    dnv = v[ret < -0.05].iloc[-10:].mean() if (ret.iloc[-10:] < -0.05).any() else 0
    skew = upv / dnv if dnv > 0 else (2.0 if upv > 0 else 0)
    r20 = ret.iloc[-20:].std(); r120 = ret.iloc[-120:].std()
    tight = r20 / r120 if r120 and r120 > 0 else 9
    ma20, ma50 = c.rolling(20).mean().iloc[-1], c.rolling(50).mean().iloc[-1]
    return dict(
        close=round(float(last), 2), day_ret=round(float(ret.iloc[-1]), 2),
        mcap_cr=round(mcap / 1e7, 1), consec_up=up,
        ret5=round(float(c.iloc[-1] / c.iloc[-6] - 1) * 100, 1),
        ret10=round(float(c.iloc[-1] / c.iloc[-11] - 1) * 100, 1),
        max_up10=round(float(ret.iloc[-10:].max()), 1),
        n_explode=int((ret.iloc[-10:] >= CFG["thr"]["explode_days"]).sum()),
        vol_ratio=round(float(vol5_60), 2), skew=round(float(skew), 2), vol20=int(vol20),
        dd52=round(float((last / hi52 - 1) * 100), 1),
        low52=round(float((last / lo52 - 1) * 100), 1),
        tight=round(float(tight), 2),
        above20=bool(last > ma20), above50=bool(last > ma50),
        last_bar=str(df.index[-1].date()))

def score_symbol(f, thr=None, event=False):
    thr = thr or CFG["thr"]
    why, s = [], 0
    if f["vol20"] < CFG["min_vol20"] or not (CFG["px_min"] <= f["close"] <= CFG["px_max"]):
        return 0, "ILLIQUID", why
    exploded = f["n_explode"] >= 3 or f["ret10"] > thr["explode_ret10"]
    if f["consec_up"] >= thr["consec_up"]:
        pts = min(14, 6 + 2 * f["consec_up"]); s += pts
        why.append(f"{f['consec_up']} straight green closes (+{pts})")
    if f["skew"] >= thr["upvol_skew"]:
        s += 8; why.append(f"up-day vol skew {f['skew']}x (+8)")
    if f["vol_ratio"] >= thr["vol_ratio_5_60"]:
        pts = 7 if f["vol_ratio"] <= 4 else 3; s += pts
        why.append(f"5d vol {f['vol_ratio']}x 60d (+{pts})")
    if f["above20"]:
        s += 4; why.append("back above 20-DMA (+4)")
    if f["dd52"] <= -thr["dd52_min"]:
        s += 8; why.append(f"{f['dd52']}% off 52w high (+8)")
    if f["low52"] <= thr["low52_max"]:
        s += 8; why.append(f"only +{f['low52']}% above 52w low (+8)")
    if f["tight"] <= thr["tightness"]:
        s += 7; why.append(f"volatility compressed {f['tight']} (+7)")
    if 2 <= f["ret5"] <= 20:
        s += 7; why.append(f"quiet +{f['ret5']}% wk (+7)")
    if event:
        s += 30; why.append("EVENT: fund-raise/preferential filing (+30)")
    if f["mcap_cr"] and f["mcap_cr"] <= 350:
        s += 5; why.append(f"micro-cap Rs{f['mcap_cr']}Cr (+5)")
    elif f["mcap_cr"] and f["mcap_cr"] <= 1500:
        s += 2
    if exploded:
        s = min(s, 44)
        verdict = "EXPLODED - DO NOT CHASE"
        why.append(f"WARNING: {f['n_explode']} circuit-like days / 10d +{f['ret10']}% - late")
    elif f["max_up10"] > thr["single_day_cap"] and f["n_explode"] >= 1:
        s = int(s * 0.8); verdict = "HEATING - LATE?"
        why.append(f"one day already +{f['max_up10']}% - possibly late")
    else:
        verdict = ("PRE-EXPLOSION SETUP" if s >= 70 else
                   "WARMING UP - WATCH" if s >= 50 else
                   "EARLY NOISE" if s >= 35 else "IGNORE")
    return s, verdict, why
