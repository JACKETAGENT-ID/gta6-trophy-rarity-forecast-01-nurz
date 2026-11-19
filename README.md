# GTA VI Trophy Rarity Forecast — nurz entry

Forecasts each GTA VI PS5 trophy's Exophase earn rate at the case target.

## Model: dilution + progression (in counts)

`rate = 100 * E / P`, where `P` = players tracked and `E` = earners.

- **Players**: daily growth factor from the last 24h of reads, carried to the
  target (capped 2x/day, 8x total). If history shows no growth at all, one
  refresh-scale jump is assumed (638 → 3,868 players, ~6.06x, as recorded on
  launch night).
- **Earned counts**: existing players progress at a per-trophy hourly hazard
  (after a reachability lag); new players arrive nearly empty-handed and
  progress over their average age. Hazard/lag/arrival-rate priors come from
  a trophy class (platinum / grind / late-story / mid-story / early-story /
  misc) read off tier + description keywords. Where history shows refreshes,
  the newcomers' arrival earn rate is measured from `dE/dP` across jumps.
- The universal (100%) trophy is forecast at ~100%.
- Quantiles on the logit scale; spread widens with horizon, refresh risk,
  and how far the median moved from the last read.

## Run

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, deterministic, no network.
