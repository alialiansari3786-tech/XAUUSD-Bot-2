# Optimization report

Generated: 2026-10-31 13:19 UTC

## Setup
- Random trials completed: 5 (max 200); time used: 312 min of 300 min budget - **stopped early on time budget**
- Minimum in-sample trades to qualify: 30
- Ranked on in-sample net P&L; out-of-sample shown only for the top 5
- In-sample before 2026-10-14 01:30:00+00:00; out-of-sample from 2026-10-14 01:30:00+00:00
- Costs: spread 0.3 + fee 0.1 per oz. P&L is $ per oz. Seed 42, replay step 4
- Trials that qualified (>= 30 in-sample trades): 2

## Current params.yaml (baseline)
| | trades | win | net | max DD |
|---|---|---|---|---|
| In-sample | 34 | 32% | -3.45 | 60.72 |
| Out-of-sample | 25 | 36% | -3.57 | 84.78 |

## Top 5 by in-sample net P&L
| Rank | Trial | IS trades | IS win | IS net | IS max DD | OOS trades | OOS win | OOS net | OOS max DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 30 | 37% | 98.85 | 46.37 | 25 | 44% | 55.30 | 39.48 |
| 2 | 4 | 30 | 37% | -23.05 | 49.01 | 13 | 31% | -50.29 | 62.81 |

## Parameters of the top trials
| Parameter | Current | #1 | #2 |
|---|---|---|---|
| combined.mss_max_age_bars | 15 | 28 | 20 |
| combined.weekly_pullback_bull | 0.985 | 0.9728 | 0.9767 |
| combined.weekly_pullback_bear | 1.015 | 1.0235 | 1.0103 |
| combined.sl_buffer_ob_mult | 0.2 | 0.198 | 0.4772 |
| combined.fallback_rr | 2.0 | 1.7093 | 2.8146 |
| percentage.d1_min_pullback_pct | 25.0 | 17.5624 | 22.8669 |
| percentage.h1_min_pullback_pct | 37.5 | 43.5167 | 41.386 |
| percentage.h1_zone_entry_fib | 0.375 | 0.3863 | 0.3489 |
| percentage.m5_mss_max_age_bars | 20 | 28 | 39 |
| percentage.sl_buffer_ob_mult | 0.1 | 0.1555 | 0.2107 |
| percentage.monthly_lookback_candles | 3 | 2 | 3 |
| liquidity_msnr.max_swing_sl_pips | 50 | 41 | 63 |
| liquidity_msnr.fibo2_shallow_entry | 0.145 | 0.1219 | 0.114 |
| liquidity_msnr.fibo2_deep_entry | 0.25 | 0.2758 | 0.3117 |
| liquidity_msnr.mss_max_age_bars | 15 | 8 | 25 |
| liquidity_msnr.fibo_lookback | 50 | 55 | 63 |
| liquidity_msnr.fallback_rr | 3.0 | 3.432 | 3.494 |
| msnr_detector.qm_swing_lookback | 5 | 8 | 6 |
| msnr_detector.qm_tolerance_pct | 2.0 | 1.8624 | 2.7446 |
| order_block.displacement_avg_window | 14 | 17 | 22 |
| order_block.displacement_range_mult | 1.5 | 1.784 | 1.6706 |
| order_block.displacement_body_ratio | 0.7 | 0.5974 | 0.8491 |
| confluence.min_combined | 6 | 4 | 5 |
| confluence.min_percentage | 5 | 4 | 7 |
| liquidity_msnr.fibo2_shallow_sl | 0.109 | 0.1066 | 0.0939 |
| liquidity_msnr.fibo2_deep_sl | 0.214 | 0.2165 | 0.2771 |

## How to read this
- 1 of the top 2 are also profitable out-of-sample.
- Few trades means noisy results; treat small gaps between trials as luck.
- Picking the best of many random trials overfits. Only trust a setting that also holds out-of-sample, and ideally re-test on newer data before using it.
- This report does not change params.yaml.
