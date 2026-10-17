"""Optimize ONE method at a time inside a single run:
Combined -> Percentage -> Liquidity MSNR.

- Each method only tunes its own params (plus the shared order_block ones and its own confluence minimum).
- Each trial replays only that method, so a trial is about 3x faster.
- The time budget is split across the methods; unused time rolls forward.
- results/report.md is rewritten after every method, so a timeout keeps earlier results.
- Never changes params.yaml.

Env: OPT_MAX_TRIALS (60 per method), OPT_MIN_TRADES (10), OPT_BUDGET_MIN (300), OPT_SEED (42), OPT_STEP.
"""
import os
import sys
import copy
import time
import random
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'research'))

import pandas as pd

import optimize as op
import backtest as bt
from src.methods.combined_method import CombinedMethod
from src.methods.monthly_daily_hourly_method import MonthlyDailyHourlyMethod

MAX_TRIALS = int(os.getenv('OPT_MAX_TRIALS', '60'))
MIN_TRADES = int(os.getenv('OPT_MIN_TRADES', '10'))
BUDGET_MIN = float(os.getenv('OPT_BUDGET_MIN', '300'))
SEED = int(os.getenv('OPT_SEED', '42'))
STEP = op.STEP
TOP_N = 5

ORDER = ['Combined', 'Percentage', 'Liquidity MSNR']
SECTIONS = {
    'Combined': ['combined', 'order_block'],
    'Percentage': ['percentage', 'order_block'],
    'Liquidity MSNR': ['liquidity_msnr', 'msnr_detector', 'order_block'],
}
CONF_KEY = {'Combined': 'min_combined', 'Percentage': 'min_percentage'}


def keys_for(method):
    secs = SECTIONS[method]
    return [k for k in op.RANGES
            if k[0] in secs or (k[0] == 'confluence' and k[1] == CONF_KEY.get(method))]


def sample(rng, method):
    p = copy.deepcopy(op.BASE)
    for (sec, key) in keys_for(method):
        lo, hi, is_int = op.RANGES[(sec, key)]
        v = rng.randint(int(lo), int(hi)) if is_int else round(rng.uniform(lo, hi), 4)
        p.setdefault(sec, {})[key] = v
    if method == 'Liquidity MSNR':
        m3 = p.setdefault('liquidity_msnr', {})
        m3['fibo2_shallow_sl'] = round(m3['fibo2_shallow_entry'] * rng.uniform(0.7, 0.95), 4)
        m3['fibo2_deep_sl'] = round(m3['fibo2_deep_entry'] * rng.uniform(0.7, 0.95), 4)
    return p


def flat(params, method):
    out = {}
    for (sec, key) in keys_for(method):
        out[f'{sec}.{key}'] = params.get(sec, {}).get(key)
    if method == 'Liquidity MSNR':
        out['liquidity_msnr.fibo2_shallow_sl'] = params['liquidity_msnr'].get('fibo2_shallow_sl')
        out['liquidity_msnr.fibo2_deep_sl'] = params['liquidity_msnr'].get('fibo2_deep_sl')
    return out


def run_one(frames, params, times, method):
    op.set_params(params)
    rp = bt.Replay(frames)
    c, p = CombinedMethod(rp), MonthlyDailyHourlyMethod(rp)
    m = {
        'Combined': c,
        'Percentage': p,
        'Liquidity MSNR': op.m3mod.LiquidityMSNRMethod(rp, c, p),
    }[method]
    sim = frames.get('M5', frames['M15'])
    busy = times[0]
    seen, trades, errors = set(), [], 0

    for t in times:
        rp.t = t
        if t < busy:
            continue
        try:
            sig = m.analyze()
        except Exception:
            errors += 1
            continue
        if not sig:
            continue
        key = (sig.bias.value, str(sig.timestamp))
        if key in seen:
            continue
        seen.add(key)
        res = bt.simulate(sig, sim, t)
        if res:
            trades.append((method, t, res[0], res[1]))
            busy = res[0]
    return trades, errors


def evaluate(frames, params, times, cut, method):
    trades, errors = run_one(frames, params, times, method)
    ins = [x for x in trades if x[1] < cut]
    oos = [x for x in trades if x[1] >= cut]
    return {'params': params, 'is': op.summarize(ins), 'oos': op.summarize(oos), 'errors': errors}


def section(method, baseline, results, ranked, spent, stopped):
    top = ranked[:TOP_N]
    L = [f"## {method}", "",
         f"- Random trials: {len(results) - 1} (max {MAX_TRIALS}); {spent:.0f} min used"
         + (" - **stopped on time budget**" if stopped else ""),
         f"- Qualified (>= {MIN_TRADES} in-sample trades): {len(ranked)}", "",
         "| | trades | win | net | max DD |", "|---|---|---|---|---|",
         f"| Baseline in-sample | {op.fmt(baseline['is'])} |",
         f"| Baseline out-of-sample | {op.fmt(baseline['oos'])} |", ""]
    if not top:
        L += [f"No trial reached {MIN_TRADES} in-sample trades. Nothing to recommend.", ""]
        return L
    L += [f"### Top {len(top)} by in-sample net P&L",
          "| Rank | Trial | IS trades | IS win | IS net | IS max DD | OOS trades | OOS win | OOS net | OOS max DD |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(top, 1):
        L.append(f"| {i} | {r['id']} | {op.fmt(r['is'])} | {op.fmt(r['oos'])} |")
    L += ["", "### Parameters of the top trials",
          "| Parameter | Current | " + " | ".join(f"#{i}" for i in range(1, len(top) + 1)) + " |",
          "|---|---|" + "---|" * len(top)]
    base_flat = flat(op.BASE, method)
    flats = [flat(r['params'], method) for r in top]
    for k in flats[0]:
        L.append(f"| {k} | {base_flat.get(k)} | " + " | ".join(str(f[k]) for f in flats) + " |")
    positive = sum(1 for r in top if r['oos']['net'] > 0 and r['oos']['n'] > 0)
    L += ["", f"{positive} of the top {len(top)} are also profitable out-of-sample.", ""]
    return L


def write_report(sections, cut, elapsed_min):
    L = ["# Optimization report (one method at a time)", "",
         f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "",
         "## Setup",
         f"- Total time used: {elapsed_min:.0f} min of {BUDGET_MIN:.0f} min budget",
         f"- Minimum in-sample trades to qualify (per method): {MIN_TRADES}",
         f"- In-sample before {cut}; out-of-sample from {cut}",
         f"- Costs: spread {bt.SPREAD} + fee {bt.FEE} per oz. P&L is $ per oz. Seed {SEED}, replay step {STEP}",
         "- Each method is tuned alone; all other params stay at their params.yaml values",
         "- Few trades means noisy results. Only trust a setting that also holds out-of-sample.",
         "- This report does not change params.yaml.", ""]
    for s in sections:
        L += s
    op.REPORT.parent.mkdir(parents=True, exist_ok=True)
    op.REPORT.write_text("\n".join(L), encoding='utf-8')


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
    sections = []

    for mi, method in enumerate(ORDER):
        m_start = time.time()
        remaining = BUDGET_MIN - (m_start - start) / 60
        allowed = max(remaining, 0) / (len(ORDER) - mi)
        print(f"=== {method}: budget {allowed:.0f} min ===", flush=True)

        baseline = evaluate(frames, copy.deepcopy(op.BASE), times, cut, method)
        baseline['id'] = 0
        one_trial = (time.time() - m_start) / 60
        results, stopped = [baseline], False
        print(f"  baseline IS {op.fmt(baseline['is'])} ({one_trial:.0f} min)", flush=True)

        for i in range(1, MAX_TRIALS + 1):
            spent = (time.time() - m_start) / 60
            if spent + one_trial > allowed:
                stopped = True
                print("  time budget for this method reached", flush=True)
                break
            r = evaluate(frames, sample(rng, method), times, cut, method)
            r['id'] = i
            results.append(r)
            print(f"  trial {i} | IS {op.fmt(r['is'])} | {(time.time() - m_start) / 60:.0f} min", flush=True)

        ranked = sorted((r for r in results[1:] if r['is']['n'] >= MIN_TRADES),
                        key=lambda r: r['is']['net'], reverse=True)
        sections.append(section(method, baseline, results, ranked, (time.time() - m_start) / 60, stopped))
        write_report(sections, cut, (time.time() - start) / 60)
        print(f"  report updated after {method}", flush=True)

    op.set_params(copy.deepcopy(op.BASE))
    print(f"Report written to {op.REPORT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
