"""The PM2.5 sensor must use UnitOfDensity, not the deprecated HA constant."""
from homeassistant.const import UnitOfDensity

from custom_components.philips_airplus import sensor


def test_pm25_unit_is_density_enum():
    unit = sensor.ALL_SENSOR_DESCRIPTIONS["pm25"].native_unit_of_measurement
    assert unit == UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
    assert unit == "μg/m³"


def test_no_deprecated_constant_in_module():
    assert not hasattr(sensor, "CONCENTRATION_MICROGRAMS_PER_CUBIC_METER")
