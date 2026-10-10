"""Random search over the params.yaml ranges, using the research/backtest.py replay.

- Trial 0 is your current params.yaml (the baseline); trials 1..N are random.
- Ranked on IN-SAMPLE net P&L only, and only trials with >= MIN_TRADES in-sample trades.
- The top 5 are then reported with their OUT-OF-SAMPLE results.
- Writes results/report.md. Never changes params.yaml.

Env overrides: OPT_MAX_TRIALS (200), OPT_MIN_TRADES (30), OPT_BUDGET_MIN (300),
OPT_SEED (42), OPT_STEP (same as backtest.py).
"""
import os
import sys
import copy
import time
import random
import importlib
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'research'))

import pandas as pd

import backtest as bt  # research/backtest.py (also silences logging)
import src.utils.params as pm
import src.core.msnr_detector as msnr_mod
import src.methods.liquidity_msnr_method as m3mod
from src.methods.combined_method import CombinedMethod
from src.methods.monthly_daily_hourly_method import PercentageMethod

MAX_TRIALS = int(os.getenv('OPT_MAX_TRIALS', '200'))
MIN_TRADES = int(os.getenv('OPT_MIN_TRADES', '30'))
BUDGET_MIN = float(os.getenv('OPT_BUDGET_MIN', '300'))
SEED = int(os.getenv('OPT_SEED', '42'))
STEP = int(os.getenv('OPT_STEP', str(bt.STEP)))
TOP_N = 5

REPORT = ROOT / 'results' / 'report.md'

# (section, key): (low, high, is_int)  -- taken from the ranges in params.yaml
RANGES = {
    ('combined', 'mss_max_age_bars'): (8, 30, True),
    ('combined', 'weekly_pullback_bull'): (0.97, 0.995, False),
    ('combined', 'weekly_pullback_bear'): (1.005, 1.03, False),
    ('combined', 'sl_buffer_ob_mult'): (0.1, 0.5, False),
    ('combined', 'fallback_rr'): (1.5, 3.0, False),
    ('percentage', 'd1_min_pullback_pct'): (15, 40, False),
    ('percentage', 'h1_min_pullback_pct'): (25, 50, False),
    ('percentage', 'h1_zone_entry_fib'): (0.25, 0.5, False),
    ('percentage', 'm5_mss_max_age_bars'): (10, 40, True),
    ('percentage', 'sl_buffer_ob_mult'): (0.05, 0.3, False),
    ('percentage', 'monthly_lookback_candles'): (2, 6, True),
    ('liquidity_msnr', 'max_swing_sl_pips'): (30, 100, True),
    ('liquidity_msnr', 'fibo2_shallow_entry'): (0.10, 0.20, False),
    ('liquidity_msnr', 'fibo2_deep_entry'): (0.20, 0.35, False),
    ('liquidity_msnr', 'mss_max_age_bars'): (8, 30, True),
    ('liquidity_msnr', 'fibo_lookback'): (30, 100, True),
    ('liquidity_msnr', 'fallback_rr'): (2.0, 4.0, False),
    ('msnr_detector', 'qm_swing_lookback'): (3, 8, True),
    ('msnr_detector', 'qm_tolerance_pct'): (0.5, 3.0, False),
    ('order_block', 'displacement_avg_window'): (10, 30, True),
    ('order_block', 'displacement_range_mult'): (1.2, 2.5, False),
    ('order_block', 'displacement_body_ratio'): (0.5, 0.85, False),
    ('confluence', 'min_combined'): (4, 9, True),
    ('confluence', 'min_percentage'): (3, 8, True),
}

_ORIG_LOAD = pm.load_params
BASE = copy.deepcopy(_ORIG_LOAD())  # your current params.yaml


def sample(rng):
    """One random parameter set (everything not in RANGES keeps its params.yaml value)."""
    p = copy.deepcopy(BASE)
    for (sec, key), (lo, hi, is_int) in RANGES.items():
        v = rng.randint(int(lo), int(hi)) if is_int else round(rng.uniform(lo, hi), 4)
        p.setdefault(sec, {})[key] = v
    m3 = p['liquidity_msnr']
    # SL fractions must stay below their entry fractions
    m3['fibo2_shallow_sl'] = round(m3['fibo2_shallow_entry'] * rng.uniform(0.7, 0.95), 4)
    m3['fibo2_deep_sl'] = round(m3['fibo2_deep_entry'] * rng.uniform(0.7, 0.95), 4)
    return p


def set_params(p):
    """Make get_param() read p, and re-import the modules that read params at import time."""
    pm.load_params = lambda: p
    importlib.reload(msnr_mod)
    importlib.reload(m3mod)
    m3mod.get_shared_bias = bt.shared_bias  # same replay-safe bias as backtest.py


def run_replay(frames, params, times):
    set_params(params)
    rp = bt.Replay(frames)
    c, p = CombinedMethod(rp), PercentageMethod(rp)
    methods = {
        'Combined': c,
        'Percentage': p,
        'Liquidity MSNR': m3mod.LiquidityMSNRMethod(rp, c, p),
    }
    sim = frames.get('M5', frames['M15'])
    busy = {n: times[0] for n in methods}
    seen, trades, errors = set(), [], 0

    for t in times:
        rp.t = t
        for name, m in methods.items():
            if t < busy[name]:
                continue
            try:
                sig = m.analyze()
            except Exception:
                errors += 1
                continue
            if not sig:
                continue
            key = (name, sig.bias.value, str(sig.timestamp))
            if key in seen:
                continue
            seen.add(key)
            res = bt.simulate(sig, sim, t)
            if res:
                trades.append((name, t, res[0], res[1]))
                busy[name] = res[0]
    return trades, errors


def summarize(trades):
    if not trades:
        return {'n': 0, 'win': 0.0, 'net': 0.0, 'dd': 0.0}
    pnl = pd.Series([x[3] for x in sorted(trades, key=lambda x: x[2])])
    eq = pnl.cumsum()
    dd = float((eq.cummax().clip(lower=0) - eq).max())
    return {'n': len(pnl), 'win': float((pnl > 0).mean() * 100),
            'net': float(pnl.sum()), 'dd': dd}


def evaluate(frames, params, times, cut):
    trades, errors = run_replay(frames, params, times)
    ins = [x for x in trades if x[1] < cut]
    oos = [x for x in trades if x[1] >= cut]
    return {'params': params, 'is': summarize(ins), 'oos': summarize(oos), 'errors': errors}


def fmt(s):
    return f"{s['n']} | {s['win']:.0f}% | {s['net']:.2f} | {s['dd']:.2f}"


def flat(params):
    out = {}
    for (sec, key) in RANGES:
        out[f'{sec}.{key}'] = params[sec][key]
    out['liquidity_msnr.fibo2_shallow_sl'] = params['liquidity_msnr']['fibo2_shallow_sl']
    out['liquidity_msnr.fibo2_deep_sl'] = params['liquidity_msnr']['fibo2_deep_sl']
    return out


def write_report(baseline, results, ranked, cut, elapsed_min, stopped_early):
    top = ranked[:TOP_N]
    L = []
    L.append("# Optimization report")
    L.append("")
    L.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    L.append("")
    L.append("## Setup")
    L.append(f"- Random trials completed: {len(results) - 1} (max {MAX_TRIALS}); "
             f"time used: {elapsed_min:.0f} min of {BUDGET_MIN:.0f} min budget"
             + (" - **stopped early on time budget**" if stopped_early else ""))
    L.append(f"- Minimum in-sample trades to qualify: {MIN_TRADES}")
    L.append(f"- Ranked on in-sample net P&L; out-of-sample shown only for the top {TOP_N}")
    L.append(f"- In-sample before {cut}; out-of-sample from {cut}")
    L.append(f"- Costs: spread {bt.SPREAD} + fee {bt.FEE} per oz. P&L is $ per oz. Seed {SEED}, replay step {STEP}")
    L.append(f"- Trials that qualified (>= {MIN_TRADES} in-sample trades): {len(ranked)}")
    L.append("")
    L.append("## Current params.yaml (baseline)")
    L.append("| | trades | win | net | max DD |")
    L.append("|---|---|---|---|---|")
    L.append(f"| In-sample | {fmt(baseline['is'])} |")
    L.append(f"| Out-of-sample | {fmt(baseline['oos'])} |")
    L.append("")
    L.append(f"## Top {TOP_N} by in-sample net P&L")
    if not top:
        L.append("")
        L.append(f"No trial reached {MIN_TRADES} in-sample trades. Nothing to recommend.")
    else:
        L.append("| Rank | Trial | IS trades | IS win | IS net | IS max DD | OOS trades | OOS win | OOS net | OOS max DD |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(top, 1):
            L.append(f"| {i} | {r['id']} | {fmt(r['is'])} | {fmt(r['oos'])} |")
        L.append("")
        L.append("## Parameters of the top trials")
        keys = list(flat(top[0]['params']).keys())
        L.append("| Parameter | Current | " + " | ".join(f"#{i}" for i in range(1, len(top) + 1)) + " |")
        L.append("|---|---|" + "---|" * len(top))
        base_flat = flat(BASE)
        flats = [flat(r['params']) for r in top]
        for k in keys:
            L.append(f"| {k} | {base_flat.get(k)} | " + " | ".join(str(f[k]) for f in flats) + " |")
        L.append("")
        L.append("## How to read this")
        positive = sum(1 for r in top if r['oos']['net'] > 0 and r['oos']['n'] > 0)
        L.append(f"- {positive} of the top {len(top)} are also profitable out-of-sample.")
        L.append("- Few trades means noisy results; treat small gaps between trials as luck.")
        L.append("- Picking the best of many random trials overfits. Only trust a setting that "
                 "also holds out-of-sample, and ideally re-test on newer data before using it.")
        L.append("- This report does not change params.yaml.")
    L.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding='utf-8')


def main():
    frames = bt.load()
    if 'M15' not in frames:
        print(f"No XAUUSD_M15.csv found in {bt.DATA}")
        return 1

    times = (frames['M15'].index[bt.WARMUP:] + pd.Timedelta(minutes=15))[::STEP]
    if len(times) == 0:
        print("Not enough M15 data to replay")
        return 1
    cut = times[int(len(times) * bt.IS_SHARE)]

    rng = random.Random(SEED)
    start = time.time()
    results, stopped_early = [], False

    print("Trial 0 (baseline = current params.yaml)", flush=True)
    baseline = evaluate(frames, copy.deepcopy(BASE), times, cut)
    baseline['id'] = 0
    results.append(baseline)
    print(f"  IS {fmt(baseline['is'])}", flush=True)

    for i in range(1, MAX_TRIALS + 1):
        if (time.time() - start) / 60 >= BUDGET_MIN:
            stopped_early = True
            print("Time budget reached - stopping", flush=True)
            break
        r = evaluate(frames, sample(rng), times, cut)
        r['id'] = i
        results.append(r)
        print(f"Trial {i}/{MAX_TRIALS} | IS {fmt(r['is'])} | "
              f"{(time.time() - start) / 60:.0f} min elapsed", flush=True)

    ranked = sorted((r for r in results[1:] if r['is']['n'] >= MIN_TRADES),
                    key=lambda r: r['is']['net'], reverse=True)

    set_params(copy.deepcopy(BASE))
    write_report(baseline, results, ranked, cut, (time.time() - start) / 60, stopped_early)
    print(f"Report written to {REPORT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
