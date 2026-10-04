"""Replay Methods 1-3 on data/collected CSVs with costs; 70/30 in/out-of-sample."""
import sys
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

import pandas as pd

from src.utils.timeframe_utils import TIMEFRAME_MINUTES
import src.methods.liquidity_msnr_method as m3mod
from src.methods.combined_method import CombinedMethod
from src.methods.percentage_method import PercentageMethod
from src.methods.liquidity_msnr_method import LiquidityMSNRMethod

DATA = ROOT / 'data' / 'collected'
TFS = ['M5', 'M15', 'H1', 'H4', 'D1', 'W1', 'MN']
TAIL = {'M5': 600, 'M15': 500, 'H1': 500, 'H4': 400, 'D1': 400, 'W1': 150}
SPREAD = 0.30      # dollars per oz, paid once per trade
FEE = 0.10         # dollars per oz, round-turn commission
STEP = 4           # analyse every 4th M15 bar (hourly)
WARMUP = 300       # M15 bars skipped at the start
MAX_WAIT = 48      # sim bars a limit entry may wait for a fill
MAX_HOLD = 600     # sim bars a filled trade may stay open
IS_SHARE = 0.70    # first 70% in-sample, last 30% out-of-sample


class Replay:
    """Stands in for DataFetcher: serves only bars fully closed at self.t."""

    def __init__(self, frames):
        self.frames = frames
        self.t = None

    def fetch_multiple_timeframes(self, tfs, force_refresh=False):
        out = {}
        for tf in tfs:
            df = self.frames.get(tf)
            if df is None:
                continue
            dur = pd.Timedelta(minutes=TIMEFRAME_MINUTES[tf])
            done = df.loc[:self.t - dur]
            if not done.empty:
                out[tf] = done.tail(TAIL[tf]) if tf in TAIL else done
        return out


def load():
    frames = {}
    for tf in TFS:
        p = DATA / f'XAUUSD_{tf}.csv'
        if p.exists():
            df = pd.read_csv(p, index_col=0)
            df.index = pd.to_datetime(df.index, utc=True)
            frames[tf] = df.sort_index()
    return frames


def shared_bias(combined, percentage, data):
    """Replay version of Method 3's bias: agreement, no 01:00/17:45 caching."""
    data = {**data, **combined.data_fetcher.fetch_multiple_timeframes(['D1'])}
    a, b = combined.get_current_bias(data), percentage.get_current_bias(data)
    return a if a is not None and a == b else None


def simulate(sig, sim, t):
    """Limit entry at sig.entry_price. Returns (exit_time, net_pnl) or None."""
    long = sig.bias.value == 'Bullish'
    e, sl, tp = sig.entry_price, sig.stop_loss, sig.take_profit
    if not ((long and sl < e < tp) or (not long and tp < e < sl)):
        return None
    bars = sim[sim.index >= t].head(MAX_WAIT + MAX_HOLD)
    filled, last = False, None
    for i, (ts, r) in enumerate(bars.iterrows()):
        last = (ts, r)
        if not filled:
            if i >= MAX_WAIT:
                return None
            if not (r.Low <= e <= r.High):
                continue
            filled = True
        hit_sl = r.Low <= sl if long else r.High >= sl
        hit_tp = r.High >= tp if long else r.Low <= tp
        if hit_sl or hit_tp:  # SL wins if both hit in one bar (conservative)
            px = sl if hit_sl else tp
            return ts, (px - e) * (1 if long else -1) - SPREAD - FEE
    if filled and last:
        ts, r = last
        return ts, (r.Close - e) * (1 if long else -1) - SPREAD - FEE
    return None


def stats(trades):
    if not trades:
        return "trades 0"
    pnl = pd.Series([x[3] for x in sorted(trades, key=lambda x: x[2])])
    eq = pnl.cumsum()
    dd = (eq.cummax().clip(lower=0) - eq).max()
    return (f"trades {len(pnl):3d} | win {(pnl > 0).mean() * 100:3.0f}% | "
            f"max DD {dd:8.2f} | net {pnl.sum():8.2f}")


def main():
    frames = load()
    if 'M15' not in frames:
        print(f"No XAUUSD_M15.csv found in {DATA}")
        return
    sim = frames.get('M5', frames['M15'])
    rp = Replay(frames)
    c, p = CombinedMethod(rp), PercentageMethod(rp)
    methods = {'Combined': c, 'Percentage': p,
               'Liquidity MSNR': LiquidityMSNRMethod(rp, c, p)}
    m3mod.get_shared_bias = shared_bias  # no state files, no wall-clock use

    times = (frames['M15'].index[WARMUP:] + pd.Timedelta(minutes=15))[::STEP]
    if len(times) == 0:
        print("Not enough M15 data to replay")
        return
    cut = times[int(len(times) * IS_SHARE)]
    busy = {n: times[0] for n in methods}
    seen, trades = set(), []
    errs, found = {}, {}

    for k, t in enumerate(times):
        rp.t = t
        for name, m in methods.items():
            if t < busy[name]:
                continue
            try:
                sig = m.analyze()
            except Exception as ex:
                errs.setdefault(name, []).append(repr(ex))
                continue
            if sig:
                found[name] = found.get(name, 0) + 1
            if not sig:
                continue
            key = (name, sig.bias.value, str(sig.timestamp))
            if key in seen:
                continue
            seen.add(key)
            if len(seen) <= 5:
                print(f"  SIGNAL {name} {sig.bias.value} entry {sig.entry_price:.2f} sl {sig.stop_loss:.2f} tp {sig.take_profit:.2f} price {sim.loc[:t].Close.iloc[-1]:.2f}")
            res = simulate(sig, sim, t)
            if res:
                trades.append((name, t, res[0], res[1]))
                busy[name] = res[0]
        if k % 200 == 0:
            print(f"  replay {k}/{len(times)}", flush=True)

    for n in methods:
        e = errs.get(n, [])
        print(f"{n}: signals {found.get(n, 0)}, errors {len(e)}", e[:1])
    print(f"\nIn-sample: before {cut} | Out-of-sample: from {cut}")
    print(f"Costs: spread {SPREAD} + fee {FEE} per oz | P&L in $ per oz\n")
    for label, pick in (("IN-SAMPLE", lambda x: x[1] < cut),
                        ("OUT-OF-SAMPLE", lambda x: x[1] >= cut)):
        print(label)
        for name in list(methods) + ['All']:
            sel = [x for x in trades if pick(x) and (name == 'All' or x[0] == name)]
            print(f"  {name:15s} {stats(sel)}")
        print()


if __name__ == '__main__':
    main()
