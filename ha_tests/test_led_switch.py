"""LED switch: schema guard, translations and command mapping."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from custom_components.philips_airplus import switch as switch_mod

PKG = Path(switch_mod.__file__).parent


def models():
    return yaml.safe_load((PKG / "models.yaml").read_text())["models"]


def test_every_model_with_led_switch_defines_both_led_properties():
    for key, model in models().items():
        if "led" in model.get("switches", []):
            props = model["properties"]
            assert props.get("led_on"), key
            assert props.get("led_off"), key


def test_led_is_only_enabled_for_verified_models():
    """Only AC1715/11 has captured D03104/D03105 traffic; others stay off."""
    enabled = sorted(m["name"] for m in models().values() if "led" in m.get("switches", []))
    assert enabled == ["Philips Air+ AC1715/11"]


@pytest.mark.parametrize("lang", ["en", "de", "fr"])
def test_led_name_is_translated(lang):
    data = json.loads((PKG / "translations" / f"{lang}.json").read_text())
    assert data["entity"]["switch"]["led"]["name"]


def make_switch(led_value):
    coordinator = Mock()
    coordinator.data = {"device_state": {"D03104": led_value}}
    coordinator._model_config = {"properties": {"led_on": "D03104", "led_off": "D03105"}}
    coordinator.set_property = AsyncMock(return_value=True)
    entry = Mock()
    entry.data = {"device_uuid": "u", "device_name": "n"}
    return switch_mod.PhilipsAirplusSwitch(coordinator, entry, switch_mod.ALL_SWITCH_DESCRIPTIONS["led"]), coordinator


@pytest.mark.asyncio
async def test_led_commands_and_icon():
    sw, coordinator = make_switch(100)
    assert sw.is_on is True and sw.icon == "mdi:led-on"
    await sw.async_turn_on()
    coordinator.set_property.assert_awaited_with("led_on", 100)
    await sw.async_turn_off()
    coordinator.set_property.assert_awaited_with("led_off", 0)
    off, _ = make_switch(0)
    assert off.is_on is False and off.icon == "mdi:led-off"
    unknown, _ = make_switch(None)
    assert unknown.is_on is None and unknown.icon == "mdi:led-off"
