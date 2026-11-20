# GTA VI Trophy Rarity Forecast — nurz entry

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/JACKETAGENT-ID/gta6-trophy-rarity-forecast-01-nurz/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/JACKETAGENT-ID/gta6-trophy-rarity-forecast-01-nurz/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts each GTA VI PS5 trophy's Exophase earn rate at the case target.

## Model v2: refresh-anchored earners/players decomposition

`rate = 100 * E / P`, where `P` = players tracked and `E` = earners.
Two regimes, split on what the case history shows:

- **Flat history** (every read identical, as on launch night): the page
  has not refreshed yet, so the next refresh is the whole story. The kit
  documents that first refresh exactly — 638 players / 943 trophies
  earned became 3,868 players / 4,276 trophies earned, every rate but
  the one at 100% lower. So `P` jumps ~6.06x, and the refresh's 103
  extra earners went almost entirely to trophies a new player can earn
  in their first hours: the main-story path (chapters, the final
  mission, the story missions) and the quickest one-off activities
  (fishing challenge, arcade game, a cocktail, the bowling alley).
  Grinds, the platinum and stranger strands gain ~no earners at a
  refresh. After the jump, ordinary hazard progression runs over the
  horizon (negligible over 90 minutes: every class lag is ≥ 2 h).
- **Growth history** (refreshes observed): `P` from the log-linear
  growth of the last 24 h of reads (capped 2x/day, 8x total); each
  trophy's new-player earn rate measured from `dE/dP` across the jumps,
  blended with a hazard-based prior. No flat arrival-rate floor — a
  brand-new tracked player has earned ~nothing yet, so the arrival rate
  is the measured marginal rate, not a class prior. (Round 1's bug: a
  0.2–0.5% arrival floor doubled the earners of most trophies at the
  refresh, pushing every median ~2x too high.)
- The universal (100%) trophy is forecast at ~100%.
- Quantiles on the logit scale; spread `σ ≈ 0.32` over a 90-minute
  flat-history horizon, growing with horizon and refresh risk
  (`σ ≈ 0.7` over the 4.5-day final horizon).

## Validation (local)

The server holds the practice answers, so the practice loss is measured
against a proxy answer reconstructed from the documented refresh totals
(3,868 players, 4,276 trophies earned; non-100% trophies sum to 408
earners, was 305). The proxy is anchored, not assumed: it reproduces
both published numbers — the house starter's practice loss ~1.51 and
the round-1 entry's server-graded 0.474 (typical miss 0.25 pp,
coverage 1.0).

- Practice loss **0.064** on the anchor-matched proxy (round 1: 0.477
  on the same proxy; server-graded round 1: 0.474). Typical miss
  0.001 pp, 90% coverage 1.0.
- Robust across the proxy band: 0.11–0.18 under every alternative
  growth split tried (uniform growth: 0.167; growth only on chapters
  1–2 + quick activities: 0.141) — round 1 scores 0.42–0.48 on those
  same proxies. The upgrade is not a knife-edge fit to one proxy.
- Two runs write byte-identical output; a synthetic final-like case
  (97 reads, players growing to ~60k, 6,510-minute horizon) produces a
  valid forecast (55 rows, monotone, 0–100) with sane week-one medians
  (platinum ~0.01%, Chapter 1 ~49%, final mission ~5%). Runtime
  ~0.08 s per case, far under the 8 s limit.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, deterministic, no network.

---

<sub>Entered on [make.fun](https://make.fun/?ref=vr338bvp&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
