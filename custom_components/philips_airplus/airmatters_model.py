"""Mappings observed in the Unicorn cloud shadow and its official app branch.

The AC2221 (cloud type \"Cobra\") uses the same register layout; this was reported
working on a real AC2221/13 in issue #16 and is not independently verified here.
"""
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


# cloud type -> (accepted model prefixes, device name). Type and model must match as a pair.
_SUPPORTED = {
    "Unicorn": (("AC3220/", "AC3221/"), "Philips PureProtect 3200i"),
    "Cobra": (("AC2221/",), "Philips PureProtect Quiet 2200 Series"),
}


def model_config(model: str, device_type: str) -> dict:
    supported = _SUPPORTED.get(device_type) if isinstance(device_type, str) else None
    if not supported or not isinstance(model, str) or not model.startswith(supported[0]):
        return {}
    config = deepcopy(_UNICORN)
    config["name"] = f"{supported[1]} ({model})"
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
