"""GTA VI trophy rarity forecast (nurz entry) v2 -- refresh-anchored
earners/players decomposition.

Forecasts each trophy's Exophase earn rate at the case target by working in
*counts*:  rate_target = 100 * E_target / P_target.

Two regimes, split on what the case history shows:

  * FLAT history (every read identical, as on launch night): the page has
    not refreshed yet, so the next refresh is the whole story. The kit
    documents that first refresh exactly: 638 players tracked and 943
    trophies earned became 3,868 players and 4,276 trophies earned, every
    rate but the one at 100% lower. So P jumps ~6.06x, and the 103 extra
    earners (4,276-3,868 minus 943-638) went almost entirely to trophies a
    new player can earn in their first hours -- the main-story path
    (chapters, the final mission, the story missions) and the quickest
    one-off activities (fishing challenge, arcade game, a cocktail, the
    bowling alley). Grinds, the platinum and late-story strands gain ~no
    earners at a refresh: nobody finishes 250 stunts or 100% completion
    in their first hours. The extra earners are spread over the
    early-earnable trophies in proportion to their current earners.
    After the jump, ordinary hazard progression runs over the horizon
    (negligible over 90 minutes: every class lag is >= 2h).

  * GROWTH history (refreshes observed): P_target from the log-linear
    growth of the last 24h of reads (capped 2x/day, 8x total), and each
    trophy's new-player earn rate measured from dE/dP across the jumps,
    blended with a hazard-based prior (players progress at a per-trophy
    hourly hazard after a reachability lag). No flat arrival-rate floor:
    a brand-new tracked player has earned ~nothing yet, so the arrival
    rate is the measured marginal rate, not a class prior.

The 100% trophy (every tracked player has it, and it survived the first
6x refresh at exactly 100%) is forecast at ~100%.

Spread. Quantiles sit on the logit scale around the median with
sigma = sqrt(0.05 + 0.10 * days + refresh_var + (0.05 * |logit move|)^2):
a small base term, a random-walk term that grows with the horizon, a
refresh-risk term (0.04 when the history never showed a refresh, 0.01
once refreshes are observed), and a term for how far the median moved.
Over a 90-minute horizon with a flat history sigma is ~0.32 -- wide
enough to be honest about which trophies the refresh lifts, narrow
enough not to pay for width the forecast does not need.

Python 3.13, standard library only. Deterministic: no network, no clock,
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

# The first refresh, as the kit documents it (competition.yaml / RULES):
# launch night 638 players tracked, 943 trophies earned; refreshed to
# 3,868 players, 4,276 trophies earned.
FIRST_P = 638.0
FIRST_EARNED = 943.0
REFRESH_P = 3868.0
REFRESH_EARNED = 4276.0
REFRESH_JUMP = REFRESH_P / FIRST_P  # ~6.06x players at a refresh
# Extra earners the refresh brought to non-100% trophies, per new player:
# (4276-3868) - (943-638) = 103 earners over 3868-638 = 3230 new players.
REFRESH_EXTRA_PER_NEW = ((REFRESH_EARNED - REFRESH_P)
                         - (FIRST_EARNED - FIRST_P)) / (REFRESH_P - FIRST_P)

MAX_DAILY_GROWTH = 2.0
MAX_PLAYER_MULT = 8.0

# class: (hourly hazard lam, lag hours, median ceiling %)
# Hazards are population-average rates. The platinum is gated by the
# slowest trophy (100% completion), so its hazard is ~nil in week one;
# grinds need dozens of hours of play, so theirs stays low too.
CLASSES = {
    "plat":  (0.00002, 120.0, 5.0),
    "grind": (0.0003, 72.0, 25.0),
    "late":  (0.001, 24.0, 35.0),
    "mid":   (0.003, 8.0, 60.0),
    "early": (0.008, 2.0, 90.0),
    "misc":  (0.005, 4.0, 75.0),
}

GRIND_WORDS = (
    "100% completion", "250 stunts", "gold medal", "100 locations",
    "50 challenges", "collectible card", "20 different races",
    "every location", "every spot", "5 bank vaults", "100 vehicles",
    "purchase all garage",
)

# One-off activities a player can do within minutes of starting.
QUICK_WORDS = (
    "fishing challenge", "arcade game", "cocktail", "bowling alley",
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


def early_earnable(trophy: dict) -> bool:
    """True when a new player can earn this trophy in their first hours.

    The main-story path (chapters, the final mission, the story missions)
    plus the quickest one-off activities. Grinds, stranger strands and
    late-story trophies are excluded: they need hours-to-days of play.
    """
    if trophy["tier"] == "platinum":
        return False
    hay = (trophy["name"] + " " + trophy["description"]).lower()
    if any(w in hay for w in GRIND_WORDS):
        return False
    if any(w in hay for w in QUICK_WORDS):
        return True
    # The story path lives in the DESCRIPTION ("Complete Chapter 1.",
    # "Complete the final mission.", "Complete Breakfast Run.", ...):
    # the name comes first in the combined text, so test the
    # description on its own. "for ..." (a stranger's final mission)
    # and "strands" need a longer play session, so they stay out.
    desc = trophy["description"].lower()
    if desc.startswith("complete ") and " for " not in desc \
            and "strands" not in desc:
        return True
    return False


def last_rates(history: list, n: int) -> list:
    """Last non-null rate per trophy (rates may be null in some reads)."""
    out = [None] * n
    for read in history:
        for i, r in enumerate(read["rates"]):
            if r is not None:
                out[i] = r
    return [0.0 if r is None else r for r in out]


def project_players_growth(history: list, horizon_hours: float) -> float:
    """P_target from the log-linear growth of the last 24h of reads."""
    times = [parse_time(r["at"]) for r in history]
    players = [float(r["players_tracked"]) for r in history]
    t0 = times[0]
    hours = [(t - t0).total_seconds() / 3600.0 for t in times]
    p_last = players[-1]
    t_last = hours[-1]
    ref = 0
    for j in range(len(hours) - 1, -1, -1):
        if t_last - hours[j] >= 24.0:
            ref = j
            break
    span = t_last - hours[ref]
    if span < 1.0 or players[ref] <= 0:
        return p_last
    daily = (p_last / players[ref]) ** (24.0 / span)
    daily = min(daily, MAX_DAILY_GROWTH)
    mult = daily ** (horizon_hours / 24.0)
    return p_last * min(mult, MAX_PLAYER_MULT)


def newcomer_rates(history: list, trophies: list, classes: list,
                   horizon_hours: float) -> list:
    """Marginal earn rate of arriving players, per trophy.

    Measured from refresh intervals (players-tracked jumps): dE/dP,
    weighted by jump size, blended with a hazard-based prior (a new
    player earns by the target only if they progress past the trophy's
    lag in their average age, horizon/2). With no usable jump the prior
    alone is used -- and the prior has no flat arrival floor: brand-new
    tracked players have earned ~nothing yet.
    """
    n = len(trophies)
    prior = []
    for c in classes:
        lam, lag, _ceil = CLASSES[c]
        prior.append(1.0 - math.exp(
            -lam * max(0.0, horizon_hours / 2.0 - lag)))
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
    players = [float(r["players_tracked"]) for r in history]
    flat = max(players) == min(players)
    classes = [classify(t) for t in trophies]

    if flat:
        # One refresh-scale jump, then hazard progression over the horizon.
        p_target = p_last * REFRESH_JUMP
        # A later refresh after a long flat stretch adds a little more.
        p_target *= min(2.0, 1.0 + 0.1 * days)
        new_players = max(0.0, p_target - p_last)
        # The refresh's extra earners go to early-earnable trophies,
        # in proportion to their current earners.
        early = [early_earnable(t) for t in trophies]
        earners = [rates[i] / 100.0 * p_last for i in range(n)]
        early_sum = sum(earners[i] for i in range(n)
                        if early[i] and rates[i] < 99.99)
        extra_total = REFRESH_EXTRA_PER_NEW * new_players
        k = extra_total / early_sum if early_sum > 0 else 0.0
        refresh_var = 0.04
        arrivals = None
    else:
        p_target = project_players_growth(history, horizon_hours)
        new_players = max(0.0, p_target - p_last)
        arrivals = newcomer_rates(history, trophies, classes, horizon_hours)
        refresh_var = 0.01

    rows = []
    for i, trophy in enumerate(trophies):
        r_last = rates[i]
        cls = classes[i]
        lam, lag, ceiling = CLASSES[cls]

        if r_last >= 99.99:
            # Structurally universal trophy: stays at ~100%.
            rows.append({"id": trophy["id"],
                         "q": [99.99, 99.99, 100, 100, 100]})
            continue

        e_last = r_last / 100.0 * p_last
        if flat:
            # Refresh jump (tilted earners), then hazard progression of
            # the whole post-refresh population over the horizon.
            g = 1.0 + k if early[i] else 1.0
            e_base = e_last * g
            prog = (p_target - e_base) * (
                1.0 - math.exp(-lam * max(0.0, horizon_hours - lag)))
            e_target = e_base + prog
        else:
            m_i = arrivals[i]
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
        sigma = math.sqrt(0.05 + 0.10 * days + refresh_var
                          + (0.05 * move) ** 2)
        centre = logit(median)
        qs = [round4(clamp_pct(inv_logit(centre + z * sigma))) for z in Z]
        # Keep the row non-decreasing after rounding.
        for j in range(1, 5):
            if qs[j] < qs[j - 1]:
                qs[j] = qs[j - 1]
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
