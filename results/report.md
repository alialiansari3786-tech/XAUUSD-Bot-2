# Optimization report

Generated: 2026-10-24 11:59 UTC

## Setup
- Random trials completed: 6 (max 200); time used: 301 min of 300 min budget - **stopped early on time budget**
- Minimum in-sample trades to qualify: 30
- Ranked on in-sample net P&L; out-of-sample shown only for the top 5
- In-sample before 2026-10-09 03:30:00+00:00; out-of-sample from 2026-10-09 03:30:00+00:00
- Costs: spread 0.3 + fee 0.1 per oz. P&L is $ per oz. Seed 42, replay step 4
- Trials that qualified (>= 30 in-sample trades): 1

## Current params.yaml (baseline)
| | trades | win | net | max DD |
|---|---|---|---|---|
| In-sample | 28 | 39% | 13.35 | 43.93 |
| Out-of-sample | 22 | 18% | -69.59 | 79.39 |

## Top 5 by in-sample net P&L
| Rank | Trial | IS trades | IS win | IS net | IS max DD | OOS trades | OOS win | OOS net | OOS max DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 6 | 32 | 41% | 18.22 | 48.83 | 26 | 31% | -3.17 | 30.16 |

## Parameters of the top trials
| Parameter | Current | #1 |
|---|---|---|
| combined.mss_max_age_bars | 15 | 11 |
| combined.weekly_pullback_bull | 0.985 | 0.9918 |
| combined.weekly_pullback_bear | 1.015 | 1.0125 |
| combined.sl_buffer_ob_mult | 0.2 | 0.3556 |
| combined.fallback_rr | 2.0 | 2.4135 |
| percentage.d1_min_pullback_pct | 25.0 | 18.821 |
| percentage.h1_min_pullback_pct | 37.5 | 44.0628 |
| percentage.h1_zone_entry_fib | 0.375 | 0.3848 |
| percentage.m5_mss_max_age_bars | 20 | 34 |
| percentage.sl_buffer_ob_mult | 0.1 | 0.2806 |
| percentage.monthly_lookback_candles | 3 | 2 |
| liquidity_msnr.max_swing_sl_pips | 50 | 71 |
| liquidity_msnr.fibo2_shallow_entry | 0.145 | 0.1489 |
| liquidity_msnr.fibo2_deep_entry | 0.25 | 0.2168 |
| liquidity_msnr.mss_max_age_bars | 15 | 19 |
| liquidity_msnr.fibo_lookback | 50 | 69 |
| liquidity_msnr.fallback_rr | 3.0 | 2.4789 |
| msnr_detector.qm_swing_lookback | 5 | 4 |
| msnr_detector.qm_tolerance_pct | 2.0 | 2.695 |
| order_block.displacement_avg_window | 14 | 12 |
| order_block.displacement_range_mult | 1.5 | 1.3113 |
| order_block.displacement_body_ratio | 0.7 | 0.6701 |
| confluence.min_combined | 6 | 4 |
| confluence.min_percentage | 5 | 7 |
| liquidity_msnr.fibo2_shallow_sl | 0.109 | 0.1327 |
| liquidity_msnr.fibo2_deep_sl | 0.214 | 0.1587 |

## How to read this
- 0 of the top 1 are also profitable out-of-sample.
- Few trades means noisy results; treat small gaps between trials as luck.
- Picking the best of many random trials overfits. Only trust a setting that also holds out-of-sample, and ideally re-test on newer data before using it.
- This report does not change params.yaml.
