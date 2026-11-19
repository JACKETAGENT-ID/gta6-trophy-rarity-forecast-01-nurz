"""GTA VI trophy rarity forecast (nurz entry) -- dilution + progression model.

Forecasts each trophy's Exophase earn rate at the case target by working in
*counts*, not by extrapolating the rate itself:

    rate_target = 100 * E_target / P_target

where P is Exophase's players-tracked count and E is how many of them earned
the trophy.  Two forces move E and P in opposite directions:

  * Dilution: new players arrive (P grows) having earned almost nothing yet,
    which drags every rate down.
  * Progression: players already tracked keep playing and earn trophies at a
    per-trophy hazard, which pushes rates up -- fast for early-story trophies,
    slow for endgame grinds and the platinum.

Players projection.  From the case history, the daily growth factor over the
last 24h of reads is measured (log-linear on players-tracked) and carried
forward to the target, capped at 2x/day and 8x total.  When the history shows
no player growth at all (every read identical, as on launch night), one
refresh-scale jump is assumed: the first refresh the house recorded multiplied
tracked players by about 6x (638 -> 3,868), so P_target = 6.06 * P_last.

Earned-count projection.  For each trophy i, with horizon H hours:

    E_t = E_last
        + (P_last - E_last) * (1 - exp(-lam_i * max(0, H - lag_i)))
        + (P_t - P_last) * beta_i

  * The middle term is existing players progressing: lam_i is the hourly
    hazard that a not-yet-earner earns the trophy, after a lag_i (hours of
    play needed before the trophy is even reachable).
  * beta_i is the share of *new* players who have earned the trophy by the
    target: their arrival earn rate m_i plus their own progression over
    their average age H/2 at the target:
        beta_i = m_i + (1 - m_i) * (1 - exp(-lam_i * max(0, H/2 - lag_i)))
  * m_i is measured from the history when it shows refreshes: over each
    interval where players-tracked jumps, the marginal earn rate of the
    newcomers is dE_i / dP (earned-count growth attributed to the arrivals).
    With no such interval in the history, m_i falls back to a class prior.

Trophy classes (from tier + description keywords, deterministic):
  plat   platinum -- almost nobody in week one.
  grind  100% completion, big counters (250 stunts, 100 locations, 50
         challenges, card sets, gold medals, ...).
  late   the final mission / end of the story.
  mid    chapters 3-4 and stranger side-mission strands.
  early  chapters 1-2 and the opening missions.
  misc   everything else (one-off activities, shops, collectibles).

Each class carries (lam, lag, m0 arrival rate, ceiling on the median rate).
The 100% trophy (every tracked player has it, and it survived the first
6x refresh at exactly 100%) is forecast at ~100%.

Spread.  Quantiles sit on the logit scale around the median with
sigma = sqrt(0.25 * days + extra^2 + (0.15 * |logit move|)^2): a random-walk
term, an extra term for refresh risk (1.0 logit when the history never
showed a refresh, 0.45 once refreshes are observed), and a term that widens
the band the further the median moved from the last read.

Python 3.13, standard library only.  Deterministic: no network, no clock,
no randomness; the same input always yields the same bytes.
"""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# First refresh the house recorded: 638 -> 3,868 tracked players.
REFRESH_JUMP = 3868.0 / 638.0
MAX_DAILY_GROWTH = 2.0
MAX_PLAYER_MULT = 8.0

# class: (hourly hazard lam, lag hours, arrival earn rate m0, median ceiling %)
# Hazards are population-average rates: in week one only a small share of
# tracked players attempts (let alone finishes) grinds or the story's end,
# so late/grind/platinum hazards stay low even though a few hardcore
# players race ahead.
CLASSES = {
    "plat":  (0.0004, 72.0, 0.0005, 5.0),
    "grind": (0.0006, 48.0, 0.001, 25.0),
    "late":  (0.001, 24.0, 0.001, 35.0),
    "mid":   (0.003, 8.0, 0.002, 60.0),
    "early": (0.008, 2.0, 0.002, 90.0),
    "misc":  (0.005, 4.0, 0.005, 75.0),
}

GRIND_WORDS = (
    "100% completion", "250 stunts", "gold medal", "100 locations",
    "50 challenges", "collectible card", "20 different races",
    "every location", "every spot", "5 bank vaults", "100 vehicles",
    "purchase all garage",
)


def clamp_pct(x: float) -> float:
    return min(100.0, max(0.01, x))


def logit(pct: float) -> float:
    p = clamp_pct(pct)
    return math.log(p / (100.0 - p))


def inv_logit(lg: float) -> float:
    if lg >= 0:
        return 100.0 / (1.0 + math.exp(-lg))
    e = math.exp(lg)
    return 100.0 * e / (1.0 + e)


def round4(x: float):
    """Round to 4 decimals, half up (matches the kit starter's rounding)."""
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000.0
    return int(value) if value.is_integer() else value


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def classify(trophy: dict) -> str:
    if trophy["tier"] == "platinum":
        return "plat"
    hay = (trophy["name"] + " " + trophy["description"]).lower()
    if any(w in hay for w in GRIND_WORDS):
        return "grind"
    if "final mission" in hay and " for " not in hay:
        return "late"
    if "chapter 1" in hay or "chapter 2" in hay or "gone fishing" in hay \
            or "breakfast run" in hay:
        return "early"
    if "chapter 3" in hay or "chapter 4" in hay or "mission strands" in hay \
            or "final mission for" in hay:
        return "mid"
    return "misc"


def last_rates(history: list, n: int) -> list:
    """Last non-null rate per trophy (rates may be null in some reads)."""
    out = [None] * n
    for read in history:
        for i, r in enumerate(read["rates"]):
            if r is not None:
                out[i] = r
    return [0.0 if r is None else r for r in out]


def project_players(history: list, horizon_hours: float):
    """Return (P_target, flat_history). P_target from the last 24h growth."""
    times = [parse_time(r["at"]) for r in history]
    players = [float(r["players_tracked"]) for r in history]
    t0 = times[0]
    hours = [(t - t0).total_seconds() / 3600.0 for t in times]
    p_last = players[-1]
    if max(players) == min(players):
        # No refresh ever observed: assume one refresh-scale jump.
        if horizon_hours >= 1.0:
            return p_last * REFRESH_JUMP, True
        return p_last, True
    # Reference read ~24h before the last one (or the first read).
    t_last = hours[-1]
    ref = 0
    for j in range(len(hours) - 1, -1, -1):
        if t_last - hours[j] >= 24.0:
            ref = j
            break
    span = t_last - hours[ref]
    if span < 1.0 or players[ref] <= 0:
        return p_last, False
    daily = (p_last / players[ref]) ** (24.0 / span)
    daily = min(daily, MAX_DAILY_GROWTH)
    mult = daily ** (horizon_hours / 24.0)
    return p_last * min(mult, MAX_PLAYER_MULT), False


def newcomer_rates(history: list, trophies: list, classes: list) -> list:
    """Marginal earn rate of arriving players, per trophy.

    Measured from refresh intervals (players-tracked jumps): dE/dP, weighted
    by the size of each jump.  Falls back to the class prior where the
    history shows no usable jump.
    """
    n = len(trophies)
    prior = [CLASSES[c][2] for c in classes]
    if len(history) < 2:
        return prior
    num = [0.0] * n
    den = 0.0
    for a, b in zip(history, history[1:]):
        dp = b["players_tracked"] - a["players_tracked"]
        if dp <= max(10.0, 0.02 * a["players_tracked"]):
            continue
        den += dp
        for i in range(n):
            ra, rb = a["rates"][i], b["rates"][i]
            if ra is None or rb is None:
                continue
            ea = ra / 100.0 * a["players_tracked"]
            eb = rb / 100.0 * b["players_tracked"]
            num[i] += max(0.0, eb - ea)
    p_last = float(history[-1]["players_tracked"])
    if den < 0.1 * p_last:
        return prior
    out = []
    for i in range(n):
        measured = num[i] / den if den > 0 else 0.0
        blended = 0.7 * measured + 0.3 * prior[i]
        out.append(min(0.9, max(0.0, blended)))
    return out


def forecast_case(case: dict) -> dict:
    trophies = case["trophies"]
    history = case["history"]
    if not history:
        raise ValueError("case has no history")
    n = len(trophies)
    horizon_hours = case["horizon_minutes"] / 60.0
    days = case["horizon_minutes"] / 1440.0

    rates = last_rates(history, n)
    p_last = float(history[-1]["players_tracked"])
    p_target, flat = project_players(history, horizon_hours)
    new_players = max(0.0, p_target - p_last)
    classes = [classify(t) for t in trophies]
    arrivals = newcomer_rates(history, trophies, classes)

    extra = 1.0 if flat else 0.45
    rows = []
    for i, trophy in enumerate(trophies):
        r_last = rates[i]
        cls = classes[i]
        lam, lag, _m0, ceiling = CLASSES[cls]
        m_i = arrivals[i]

        if r_last >= 99.99:
            # Structurally universal trophy: stays at ~100%.
            rows.append({"id": trophy["id"],
                         "q": [99.9, 99.99, 100, 100, 100]})
            continue

        e_last = r_last / 100.0 * p_last
        prog_exist = (p_last - e_last) * (
            1.0 - math.exp(-lam * max(0.0, horizon_hours - lag)))
        prog_new = 1.0 - math.exp(
            -lam * max(0.0, horizon_hours / 2.0 - lag))
        beta = m_i + (1.0 - m_i) * prog_new
        e_target = e_last + prog_exist + new_players * beta
        median = 100.0 * e_target / p_target if p_target > 0 else r_last
        median = min(median, ceiling)
        median = clamp_pct(median)

        move = abs(logit(median) - logit(r_last))
        sigma = math.sqrt(0.25 * days + extra * extra + (0.15 * move) ** 2)
        centre = logit(median)
        qs = [round4(clamp_pct(inv_logit(centre + z * sigma))) for z in Z]
        # Keep the row non-decreasing after rounding.
        for k in range(1, 5):
            if qs[k] < qs[k - 1]:
                qs[k] = qs[k - 1]
        rows.append({"id": trophy["id"], "q": qs})
    return {"trophies": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out = OUTPUT_DIR / f"{path.stem}.out"
        out.write_text(json.dumps(forecast, separators=(",", ":")) + "\n",
                       encoding="utf-8")


if __name__ == "__main__":
    main()
