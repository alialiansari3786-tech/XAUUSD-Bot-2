# Optimization report

Generated: 2026-11-14 14:07 UTC

## Setup
- Random trials completed: 7 (max 200); time used: 324 min of 300 min budget - **stopped early on time budget**
- Minimum in-sample trades to qualify: 30
- Ranked on in-sample net P&L; out-of-sample shown only for the top 5
- In-sample before 2026-10-23 21:30:00+00:00; out-of-sample from 2026-10-23 21:30:00+00:00
- Costs: spread 0.3 + fee 0.1 per oz. P&L is $ per oz. Seed 42, replay step 4
- Trials that qualified (>= 30 in-sample trades): 5

## Current params.yaml (baseline)
| | trades | win | net | max DD |
|---|---|---|---|---|
| In-sample | 50 | 30% | -56.23 | 113.51 |
| Out-of-sample | 16 | 50% | 106.35 | 47.74 |

## Top 5 by in-sample net P&L
| Rank | Trial | IS trades | IS win | IS net | IS max DD | OOS trades | OOS win | OOS net | OOS max DD |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 7 | 39 | 46% | 133.52 | 28.96 | 18 | 50% | 77.15 | 43.81 |
| 2 | 1 | 45 | 38% | 105.84 | 52.17 | 16 | 50% | 110.29 | 43.81 |
| 3 | 2 | 33 | 30% | 22.36 | 57.16 | 16 | 44% | -3.80 | 68.84 |
| 4 | 6 | 58 | 36% | 15.05 | 67.27 | 18 | 56% | 128.21 | 43.81 |
| 5 | 4 | 36 | 36% | -49.31 | 50.26 | 13 | 38% | 123.84 | 48.05 |

## Parameters of the top trials
| Parameter | Current | #1 | #2 | #3 | #4 | #5 |
|---|---|---|---|---|---|---|
| combined.mss_max_age_bars | 15 | 23 | 28 | 12 | 11 | 20 |
| combined.weekly_pullback_bull | 0.985 | 0.9937 | 0.9728 | 0.9754 | 0.9918 | 0.9767 |
| combined.weekly_pullback_bear | 1.015 | 1.0091 | 1.0235 | 1.0241 | 1.0125 | 1.0103 |
| combined.sl_buffer_ob_mult | 0.2 | 0.3111 | 0.198 | 0.1409 | 0.3556 | 0.4772 |
| combined.fallback_rr | 2.0 | 2.4099 | 1.7093 | 2.0699 | 2.4135 | 2.8146 |
| percentage.d1_min_pullback_pct | 25.0 | 39.1091 | 17.5624 | 23.9745 | 18.821 | 22.8669 |
| percentage.h1_min_pullback_pct | 37.5 | 48.2228 | 43.5167 | 33.5989 | 44.0628 | 41.386 |
| percentage.h1_zone_entry_fib | 0.375 | 0.4388 | 0.3863 | 0.3161 | 0.3848 | 0.3489 |
| percentage.m5_mss_max_age_bars | 20 | 32 | 28 | 11 | 34 | 39 |
| percentage.sl_buffer_ob_mult | 0.1 | 0.1003 | 0.1555 | 0.2324 | 0.2806 | 0.2107 |
| percentage.monthly_lookback_candles | 3 | 4 | 2 | 6 | 2 | 3 |
| liquidity_msnr.max_swing_sl_pips | 50 | 81 | 41 | 45 | 71 | 63 |
| liquidity_msnr.fibo2_shallow_entry | 0.145 | 0.1995 | 0.1219 | 0.1973 | 0.1489 | 0.114 |
| liquidity_msnr.fibo2_deep_entry | 0.25 | 0.2975 | 0.2758 | 0.2568 | 0.2168 | 0.3117 |
| liquidity_msnr.mss_max_age_bars | 15 | 22 | 8 | 25 | 19 | 25 |
| liquidity_msnr.fibo_lookback | 50 | 96 | 55 | 67 | 69 | 63 |
| liquidity_msnr.fallback_rr | 3.0 | 2.903 | 3.432 | 3.6588 | 2.4789 | 3.494 |
| msnr_detector.qm_swing_lookback | 5 | 4 | 8 | 7 | 4 | 6 |
| msnr_detector.qm_tolerance_pct | 2.0 | 1.0617 | 1.8624 | 2.7136 | 2.695 | 2.7446 |
| order_block.displacement_avg_window | 14 | 20 | 17 | 21 | 12 | 22 |
| order_block.displacement_range_mult | 1.5 | 1.2273 | 1.784 | 1.9506 | 1.3113 | 1.6706 |
| order_block.displacement_body_ratio | 0.7 | 0.6939 | 0.5974 | 0.7466 | 0.6701 | 0.8491 |
| confluence.min_combined | 6 | 8 | 4 | 4 | 4 | 5 |
| confluence.min_percentage | 5 | 4 | 4 | 8 | 7 | 7 |
| liquidity_msnr.fibo2_shallow_sl | 0.109 | 0.14 | 0.1066 | 0.1494 | 0.1327 | 0.0939 |
| liquidity_msnr.fibo2_deep_sl | 0.214 | 0.2609 | 0.2165 | 0.1983 | 0.1587 | 0.2771 |

## How to read this
- 4 of the top 5 are also profitable out-of-sample.
- Few trades means noisy results; treat small gaps between trials as luck.
- Picking the best of many random trials overfits. Only trust a setting that also holds out-of-sample, and ideally re-test on newer data before using it.
- This report does not change params.yaml.
