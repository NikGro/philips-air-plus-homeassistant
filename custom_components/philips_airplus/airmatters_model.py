"""Mappings observed in the Unicorn cloud shadow and its official app branch."""
from __future__ import annotations

from copy import deepcopy
import math

_UNICORN = {
    "modes": {"Auto": 0, "Sleep": 17, "Turbo": 18, "Medium": 19,
              "Speed1": 1, "Speed2": 2, "Speed3": 3, "Speed4": 4, "Speed5": 5},
    "properties": {"power": "D03102", "mode": "D0310C", "fan_level": "D0310D",
                   "pm25": "D03221", "allergen_index": "D03120",
                   "filter_clean_nominal": "D05207", "filter_clean_remaining": "D0520D",
                   "filter_replace_nominal": "D05408", "filter_replace_remaining": "D0540E"},
    "sensors": ["pm25", "allergen_index", "fan_level", "filter_clean_percentage",
                "filter_clean_hours_remaining", "filter_replace_percentage",
                "filter_replace_hours_remaining"],
    # Reset commands are not verified for this backend; do not guess lifetimes.
    "buttons": [], "switches": [],
}


def model_config(model: str, device_type: str) -> dict:
    if device_type != "Unicorn" or not isinstance(model, str) or not model.startswith(("AC3220/", "AC3221/")):
        return {}
    config = deepcopy(_UNICORN)
    config["name"] = f"Philips PureProtect 3200i ({model})"
    return config


def filter_info(state: dict) -> dict:
    output = {}
    for kind, nominal, remaining in (("clean", "D05207", "D0520D"), ("replace", "D05408", "D0540E")):
        try:
            total, left = float(state[nominal]), float(state[remaining])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(total) or not math.isfinite(left) or total <= 0 or left < 0:
            continue
        output.update({f"{kind}_hours_total": total, f"{kind}_hours_remaining": left,
                       f"{kind}_percentage": round(min(100, left / total * 100), 1)})
    return output
