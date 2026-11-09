"""Test the Tessie climate platform."""

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, _Call, call, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.tessie.const import TessieClimateKeeper
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    STATE_OFF,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceNotSupported
from homeassistant.helpers import entity_registry as er

from .common import (
    COMMAND_OK,
    ERROR_CONNECTION,
    ERROR_UNKNOWN,
    TEST_RESPONSE,
    TEST_RESPONSE_ERROR,
    TEST_STATE_OF_ALL_VEHICLES,
    assert_entities,
    setup_platform,
)


def cop_entity_id(entity_registry: er.EntityRegistry) -> str:
    """Return the cabin overheat protection climate entity ID."""
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN,
        "tessie",
        "VINVINVIN-climate_state_cabin_overheat_protection",
    )
    assert entity_id
    return entity_id


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_climate(
    hass: HomeAssistant, snapshot: SnapshotAssertion, entity_registry: er.EntityRegistry
) -> None:
    """Tests that the climate entity is correct."""

    entry = await setup_platform(hass, [Platform.CLIMATE])

    assert_entities(hass, entry.entry_id, entity_registry, snapshot)

    entity_id = "climate.test_climate"

    # Test setting climate on
    with patch(
        "homeassistant.components.tessie.climate.start_climate_preconditioning",
        return_value=TEST_RESPONSE,
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
            blocking=True,
        )
        mock_set.assert_called_once()
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.HEAT_COOL

    # Test setting climate temp
    with (
        patch(
            "tesla_fleet_api.tessie.Vehicle.set_temps", return_value=COMMAND_OK
        ) as mock_set,
        patch(
            "homeassistant.components.tessie.climate.start_climate_preconditioning",
            return_value=TEST_RESPONSE,
        ) as mock_set2,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: [entity_id],
                ATTR_HVAC_MODE: HVACMode.HEAT_COOL,
                ATTR_TEMPERATURE: 20,
            },
            blocking=True,
        )
        mock_set.assert_called_once_with(driver_temp=20, passenger_temp=20)
        mock_set2.assert_called_once()
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 20

    # Test setting climate preset
    with patch(
        "homeassistant.components.tessie.climate.set_climate_keeper_mode",
        return_value=TEST_RESPONSE,
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_PRESET_MODE: TessieClimateKeeper.ON},
            blocking=True,
        )
        mock_set.assert_called_once()
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_PRESET_MODE] == TessieClimateKeeper.ON

    # Test setting climate off
    with patch(
        "homeassistant.components.tessie.climate.stop_climate",
        return_value=TEST_RESPONSE,
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.OFF},
            blocking=True,
        )
        mock_set.assert_called_once()
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_climate_cop(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test cabin overheat protection climate mode controls."""

    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = cop_entity_id(entity_registry)

    state = hass.states.get(entity_id)
    assert state
    assert state.state == HVACMode.COOL

    with patch(
        "homeassistant.components.tessie.climate.stop_cabin_overheat_protection",
        return_value=TEST_RESPONSE,
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.OFF},
            blocking=True,
        )
        mock_set.assert_called_once()
    state = hass.states.get(entity_id)
    assert state
    assert state.state == HVACMode.OFF

    with patch(
        "homeassistant.components.tessie.climate.start_cabin_overheat_protection",
        return_value=TEST_RESPONSE,
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.COOL},
            blocking=True,
        )
        mock_set.assert_called_once()
    state = hass.states.get(entity_id)
    assert state
    assert state.state == HVACMode.COOL

    with patch(
        "homeassistant.components.tessie.climate.start_cabin_overheat_protection",
        return_value=TEST_RESPONSE,
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
        mock_set.assert_called_once()
    state = hass.states.get(entity_id)
    assert state
    assert state.state == HVACMode.COOL

    with patch(
        "homeassistant.components.tessie.climate.stop_cabin_overheat_protection",
        return_value=TEST_RESPONSE,
    ) as mock_set:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
        mock_set.assert_called_once()
    state = hass.states.get(entity_id)
    assert state
    assert state.state == HVACMode.OFF


async def test_errors(hass: HomeAssistant) -> None:
    """Tests errors are handled."""

    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = "climate.test_climate"

    # Test setting climate on with unknown error
    with (
        patch(
            "homeassistant.components.tessie.climate.stop_climate",
            side_effect=ERROR_UNKNOWN,
        ) as mock_set,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
    mock_set.assert_called_once()
    assert error.value.__cause__ == ERROR_UNKNOWN
    assert error.value.translation_domain == "tessie"
    assert error.value.translation_key == "cannot_connect"

    # Test setting climate on with connection error
    with (
        patch(
            "homeassistant.components.tessie.climate.stop_climate",
            side_effect=ERROR_CONNECTION,
        ) as mock_set,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
    mock_set.assert_called_once()
    assert error.value.__cause__ == ERROR_CONNECTION
    assert error.value.translation_domain == "tessie"
    assert error.value.translation_key == "cannot_connect"

    # Test setting climate with child presence detection error
    with (
        patch(
            "homeassistant.components.tessie.climate.start_climate_preconditioning",
            return_value={"result": False, "reason": "cpd_enabled"},
        ) as mock_set,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
            blocking=True,
        )
    mock_set.assert_called_once()
    assert error.value.translation_domain == "tessie"
    assert error.value.translation_key == "cpd_enabled"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_climate_cop_errors(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test cabin overheat protection command errors are handled."""

    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = cop_entity_id(entity_registry)

    with (
        patch(
            "homeassistant.components.tessie.climate.stop_cabin_overheat_protection",
            side_effect=ERROR_UNKNOWN,
        ) as mock_set,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.OFF},
            blocking=True,
        )
    mock_set.assert_called_once()
    assert error.value.__cause__ == ERROR_UNKNOWN

    with (
        patch(
            "homeassistant.components.tessie.climate.start_cabin_overheat_protection",
            return_value=TEST_RESPONSE_ERROR,
        ) as mock_set,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.COOL},
            blocking=True,
        )
    mock_set.assert_called_once()
    assert error.value.translation_domain == "tessie"
    assert error.value.translation_key == "command_failed"


PASSENGER_ENTITY_ID = "climate.test_passenger_climate"
PASSENGER_SYNC_FEATURES = (
    ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.PRESET_MODE
)
PASSENGER_SPLIT_FEATURES = (
    PASSENGER_SYNC_FEATURES | ClimateEntityFeature.TARGET_TEMPERATURE
)


def set_points(driver: float | None, passenger: float | None) -> dict[str, Any]:
    """Return the vehicle list with the front set points replaced."""
    data = deepcopy(TEST_STATE_OF_ALL_VEHICLES)
    climate_state = data["results"][0]["last_state"]["climate_state"]
    climate_state["driver_temp_setting"] = driver
    climate_state["passenger_temp_setting"] = passenger
    return data


@pytest.mark.parametrize(
    ("driver", "passenger", "preset_mode", "supported_features", "temperature"),
    [
        pytest.param(22, 22, "sync", PASSENGER_SYNC_FEATURES, None, id="sync"),
        pytest.param(22, 24, "split", PASSENGER_SPLIT_FEATURES, 24, id="split"),
        pytest.param(
            None, 24, None, PASSENGER_SYNC_FEATURES, None, id="driver_unknown"
        ),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_preset(
    hass: HomeAssistant,
    mock_get_state_of_all_vehicles: AsyncMock,
    driver: float | None,
    passenger: float,
    preset_mode: str | None,
    supported_features: ClimateEntityFeature,
    temperature: float | None,
) -> None:
    """Test the passenger preset follows the set points and gates the temperature."""
    mock_get_state_of_all_vehicles.return_value = set_points(driver, passenger)
    await setup_platform(hass, [Platform.CLIMATE])

    state = hass.states.get(PASSENGER_ENTITY_ID)
    assert state.attributes[ATTR_PRESET_MODE] == preset_mode
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == supported_features
    assert state.attributes.get(ATTR_TEMPERATURE) == temperature


@pytest.mark.parametrize(
    ("temperature", "preset_mode"),
    [
        pytest.param(20, "split", id="split"),
        pytest.param(22, "sync", id="sync"),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_temperature(
    hass: HomeAssistant,
    mock_get_state_of_all_vehicles: AsyncMock,
    temperature: float,
    preset_mode: str,
) -> None:
    """Test a split passenger temperature is sent with the driver temperature kept."""
    mock_get_state_of_all_vehicles.return_value = set_points(22, 24)
    await setup_platform(hass, [Platform.CLIMATE])

    with (
        patch(
            "tesla_fleet_api.tessie.Vehicle.set_temps", return_value=COMMAND_OK
        ) as mock_set_temps,
        patch(
            "homeassistant.components.tessie.climate.start_climate_preconditioning",
            return_value=TEST_RESPONSE,
        ) as mock_start,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID],
                ATTR_HVAC_MODE: HVACMode.HEAT_COOL,
                ATTR_TEMPERATURE: temperature,
            },
            blocking=True,
        )
    mock_set_temps.assert_called_once_with(driver_temp=22, passenger_temp=temperature)
    mock_start.assert_called_once()

    state = hass.states.get(PASSENGER_ENTITY_ID)
    assert state.state == HVACMode.HEAT_COOL
    assert state.attributes[ATTR_PRESET_MODE] == preset_mode


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_temperature_sync(
    hass: HomeAssistant,
    mock_get_state_of_all_vehicles: AsyncMock,
) -> None:
    """Test a synced passenger temperature cannot be set."""
    mock_get_state_of_all_vehicles.return_value = set_points(22, 22)
    await setup_platform(hass, [Platform.CLIMATE])

    with (
        patch("tesla_fleet_api.tessie.Vehicle.set_temps") as mock_set_temps,
        pytest.raises(ServiceNotSupported),
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID], ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    mock_set_temps.assert_not_called()


@pytest.mark.parametrize(
    (
        "passenger",
        "preset_mode",
        "expected_calls",
        "supported_features",
        "temperature",
    ),
    [
        pytest.param(
            24,
            "sync",
            [call(driver_temp=22, passenger_temp=22)],
            PASSENGER_SYNC_FEATURES,
            None,
            id="sync",
        ),
        pytest.param(22, "split", [], PASSENGER_SPLIT_FEATURES, 22, id="split"),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_preset_mode(
    hass: HomeAssistant,
    mock_get_state_of_all_vehicles: AsyncMock,
    passenger: float,
    preset_mode: str,
    expected_calls: list[_Call],
    supported_features: ClimateEntityFeature,
    temperature: float | None,
) -> None:
    """Test sync sends the driver temperature to both seats and split unlocks the temperature."""
    mock_get_state_of_all_vehicles.return_value = set_points(22, passenger)
    await setup_platform(hass, [Platform.CLIMATE])

    with patch(
        "tesla_fleet_api.tessie.Vehicle.set_temps", return_value=COMMAND_OK
    ) as mock_set_temps:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID], ATTR_PRESET_MODE: preset_mode},
            blocking=True,
        )
    assert mock_set_temps.call_args_list == expected_calls

    state = hass.states.get(PASSENGER_ENTITY_ID)
    assert state.attributes[ATTR_PRESET_MODE] == preset_mode
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == supported_features
    assert state.attributes.get(ATTR_TEMPERATURE) == temperature


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_set_preset_mode_driver_unknown(
    hass: HomeAssistant,
    mock_get_state_of_all_vehicles: AsyncMock,
) -> None:
    """Test the preset cannot change before the driver set point is known."""
    mock_get_state_of_all_vehicles.return_value = set_points(None, 22)
    await setup_platform(hass, [Platform.CLIMATE])

    with (
        patch("tesla_fleet_api.tessie.Vehicle.set_temps") as mock_set_temps,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID], ATTR_PRESET_MODE: "sync"},
            blocking=True,
        )
    assert error.value.translation_key == "driver_temperature_unknown"
    mock_set_temps.assert_not_called()


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_passenger_climate_turn_on_off(hass: HomeAssistant) -> None:
    """Test the passenger climate turns the cabin climate on and off."""
    await setup_platform(hass, [Platform.CLIMATE])

    with patch(
        "homeassistant.components.tessie.climate.start_climate_preconditioning",
        return_value=TEST_RESPONSE,
    ) as mock_start:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID]},
            blocking=True,
        )
    mock_start.assert_called_once()
    assert hass.states.get(PASSENGER_ENTITY_ID).state == HVACMode.HEAT_COOL

    with patch(
        "homeassistant.components.tessie.climate.stop_climate",
        return_value=TEST_RESPONSE,
    ) as mock_stop:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: [PASSENGER_ENTITY_ID]},
            blocking=True,
        )
    mock_stop.assert_called_once()
    assert hass.states.get(PASSENGER_ENTITY_ID).state == STATE_OFF


@pytest.mark.parametrize(
    ("passenger", "passenger_temp"),
    [
        pytest.param(24, 24, id="split"),
        pytest.param(22, 20, id="sync"),
        pytest.param(None, 20, id="passenger_unknown"),
    ],
)
async def test_climate_set_temperature_passenger(
    hass: HomeAssistant,
    mock_get_state_of_all_vehicles: AsyncMock,
    passenger: float | None,
    passenger_temp: float,
) -> None:
    """Test the driver temperature keeps a split passenger temperature."""
    mock_get_state_of_all_vehicles.return_value = set_points(22, passenger)
    await setup_platform(hass, [Platform.CLIMATE])

    with patch(
        "tesla_fleet_api.tessie.Vehicle.set_temps", return_value=COMMAND_OK
    ) as mock_set_temps:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ["climate.test_climate"], ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    mock_set_temps.assert_called_once_with(
        driver_temp=20, passenger_temp=passenger_temp
    )
