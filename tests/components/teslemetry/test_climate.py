"""Test the Teslemetry climate platform."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion
from tesla_fleet_api.const import CabinOverheatProtectionTemp
from tesla_fleet_api.exceptions import InvalidCommand
from teslemetry_stream import Signal

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
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
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from . import assert_entities, reload_platform, setup_platform
from .const import (
    COMMAND_ERRORS,
    COMMAND_IGNORED_REASON,
    COMMAND_OK,
    METADATA,
    METADATA_NOSCOPE,
    VEHICLE_DATA_ALT,
)

VIN = "LRW3F7EK4NC700000"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_climate(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the climate entity is correct."""

    entry = await setup_platform(hass, [Platform.CLIMATE])

    assert_entities(hass, entry.entry_id, entity_registry, snapshot)

    entity_id = "climate.test_climate"

    # Turn On and Set Temp
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 20,
            ATTR_HVAC_MODE: HVACMode.HEAT_COOL,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 20
    assert state.state == HVACMode.HEAT_COOL

    # Set Temp
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 21,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 21

    # Set Preset
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: [entity_id], ATTR_PRESET_MODE: "keep"},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_PRESET_MODE] == "keep"

    # Set Preset
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: [entity_id], ATTR_PRESET_MODE: "off"},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_PRESET_MODE] == "off"

    # Turn Off
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF

    entity_id = "climate.test_cabin_overheat_protection"

    # Turn On and Set Low
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 30,
            ATTR_HVAC_MODE: HVACMode.FAN_ONLY,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 30
    assert state.state == HVACMode.FAN_ONLY

    # Set Temp Medium
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 35,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 35

    # Set Temp High
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: [entity_id],
            ATTR_TEMPERATURE: 40,
        },
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 40

    # Turn Off
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: [entity_id]},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.OFF

    # Turn On
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: [entity_id]},
        blocking=True,
    )
    state = hass.states.get(entity_id)
    assert state.state == HVACMode.COOL

    state = hass.states.get(entity_id)
    assert state.attributes[ATTR_TEMPERATURE] == 40
    assert state.state == HVACMode.COOL

    # pytest raises ServiceValidationError
    with pytest.raises(
        ServiceValidationError,
        match="Cabin overheat protection does not support that temperature",
    ):
        # Invalid Temp
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_TEMPERATURE: 34},
            blocking=True,
        )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_climate_alt(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_vehicle_data: AsyncMock,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the climate entity is correct."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entry = await setup_platform(hass, [Platform.CLIMATE])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


async def test_climate_state_unknown(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_vehicle_data: AsyncMock,
) -> None:
    """Test that a missing climate_state_is_climate_on reports unknown, not off."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"]["LRW3F7EK4NC700000"]["polling"] = True
    mock_metadata.return_value = metadata

    data = deepcopy(VEHICLE_DATA_ALT)
    data["response"]["climate_state"]["is_climate_on"] = None
    mock_vehicle_data.return_value = data

    await setup_platform(hass, [Platform.CLIMATE])

    assert hass.states.get("climate.test_climate").state == STATE_UNKNOWN


async def test_invalid_error(hass: HomeAssistant, snapshot: SnapshotAssertion) -> None:
    """Tests service error is handled."""

    await setup_platform(hass, platforms=[Platform.CLIMATE])
    entity_id = "climate.test_climate"

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
            side_effect=InvalidCommand,
        ) as mock_on,
        pytest.raises(HomeAssistantError) as error,
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
    mock_on.assert_called_once()
    assert str(error.value) == snapshot(name="error")


@pytest.mark.parametrize("response", COMMAND_ERRORS)
async def test_errors(hass: HomeAssistant, response: str) -> None:
    """Tests service reason is handled."""

    await setup_platform(hass, platforms=[Platform.CLIMATE])
    entity_id = "climate.test_climate"

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
            return_value=response,
        ) as mock_on,
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
    mock_on.assert_called_once()


async def test_ignored_error(
    hass: HomeAssistant,
) -> None:
    """Tests ignored error is handled."""

    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = "climate.test_climate"
    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
        return_value=COMMAND_IGNORED_REASON,
    ) as mock_on:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: [entity_id]},
            blocking=True,
        )
        mock_on.assert_called_once()


async def test_climate_noscope(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_metadata: AsyncMock,
) -> None:
    """Tests that the climate entity is correct."""
    mock_metadata.return_value = METADATA_NOSCOPE

    entry = await setup_platform(hass, [Platform.CLIMATE])

    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    assert entity_entries
    for entity_entry in entity_entries:
        assert entity_entry == snapshot(name=f"{entity_entry.entity_id}-entry")

    entity_id = "climate.test_climate"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
            blocking=True,
        )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_TEMPERATURE: 20},
            blocking=True,
        )


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_select_streaming(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the select entities with streaming are correct."""

    entry = await setup_platform(hass, [Platform.CLIMATE])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.INSIDE_TEMP: 26,
                Signal.HVAC_POWER: "HvacPowerStateOn",
                Signal.CLIMATE_KEEPER_MODE: "ClimateKeeperModeOn",
                Signal.RIGHT_HAND_DRIVE: True,
                Signal.HVAC_LEFT_TEMPERATURE_REQUEST: 22,
                Signal.HVAC_RIGHT_TEMPERATURE_REQUEST: 21,
                Signal.CABIN_OVERHEAT_PROTECTION_MODE: (
                    "CabinOverheatProtectionModeStateOn"
                ),
                Signal.CABIN_OVERHEAT_PROTECTION_TEMPERATURE_LIMIT: 35,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    assert hass.states.get("climate.test_climate") == snapshot(
        name="climate.test_climate LHD"
    )

    await reload_platform(hass, entry, [Platform.CLIMATE])

    # Assert the entities restored their values
    for entity_id in (
        "climate.test_climate",
        "climate.test_cabin_overheat_protection",
    ):
        assert hass.states.get(entity_id) == snapshot(name=entity_id)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("config", "supported_features"),
    [
        pytest.param(
            {"cop_user_set_temp_supported": True},
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF,
            id="supported",
        ),
        pytest.param(
            {"cop_user_set_temp_supported": False},
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF,
            id="unsupported",
        ),
        pytest.param(
            {},
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF,
            id="missing",
        ),
    ],
)
async def test_cabin_overheat_protection_streaming_features(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    config: dict[str, bool],
    supported_features: ClimateEntityFeature,
) -> None:
    """Test streaming cabin overheat protection features come from metadata config."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"]["LRW3F7EK4NC700000"]["config"] = config
    mock_metadata.return_value = metadata

    await setup_platform(hass, [Platform.CLIMATE])

    state = hass.states.get("climate.test_cabin_overheat_protection")
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == supported_features


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_cabin_overheat_protection_streaming_set_temperature(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
) -> None:
    """Test setting the streaming cabin overheat protection temperature."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"]["LRW3F7EK4NC700000"]["config"] = {
        "cop_user_set_temp_supported": True
    }
    mock_metadata.return_value = metadata

    await setup_platform(hass, [Platform.CLIMATE])
    entity_id = "climate.test_cabin_overheat_protection"

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.set_cop_temp",
        return_value=COMMAND_OK,
    ) as mock_set_cop_temp:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: [entity_id], ATTR_TEMPERATURE: 35},
            blocking=True,
        )
    mock_set_cop_temp.assert_called_once_with(CabinOverheatProtectionTemp.MEDIUM)
    assert hass.states.get(entity_id).attributes[ATTR_TEMPERATURE] == 35


@pytest.mark.parametrize(
    ("rhd", "target_temperature"),
    [
        pytest.param(True, 21, id="rhd"),
        pytest.param(False, 22, id="lhd"),
    ],
)
async def test_climate_streaming_drive_side(
    hass: HomeAssistant,
    mock_metadata: AsyncMock,
    mock_add_listener: AsyncMock,
    rhd: bool,
    target_temperature: float,
) -> None:
    """Test the streaming target temperature follows the driver side from metadata."""

    metadata = deepcopy(METADATA)
    metadata["vehicles"][VIN]["config"] = {"rhd": rhd}
    mock_metadata.return_value = metadata

    await setup_platform(hass, [Platform.CLIMATE])

    mock_add_listener.send(
        {
            "vin": VIN,
            "data": {
                Signal.HVAC_LEFT_TEMPERATURE_REQUEST: 22,
                Signal.HVAC_RIGHT_TEMPERATURE_REQUEST: 21,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get("climate.test_climate")
    assert state.attributes[ATTR_TEMPERATURE] == target_temperature


@pytest.mark.parametrize(
    ("hvac_power", "ac_enabled", "expected", "expected_modes"),
    [
        pytest.param(
            "HvacPowerStateOn",
            True,
            HVACMode.HEAT_COOL,
            [HVACMode.HEAT_COOL, HVACMode.OFF],
            id="on",
        ),
        pytest.param(
            "HvacPowerStatePrecondition",
            True,
            HVACMode.HEAT_COOL,
            [HVACMode.HEAT_COOL, HVACMode.OFF],
            id="precondition",
        ),
        pytest.param(
            "HvacPowerStateOverheatProtect",
            True,
            HVACMode.OFF,
            [HVACMode.HEAT_COOL, HVACMode.OFF],
            id="overheat",
        ),
        pytest.param(
            "HvacPowerStateOff",
            True,
            HVACMode.OFF,
            [HVACMode.HEAT_COOL, HVACMode.OFF],
            id="off",
        ),
        pytest.param(
            "HvacPowerStateOn",
            False,
            HVACMode.FAN_ONLY,
            [HVACMode.FAN_ONLY, HVACMode.OFF],
            id="on_fan_only",
        ),
        pytest.param(
            "HvacPowerStatePrecondition",
            False,
            HVACMode.FAN_ONLY,
            [HVACMode.FAN_ONLY, HVACMode.OFF],
            id="precondition_fan_only",
        ),
        pytest.param(
            "HvacPowerStateOverheatProtect",
            False,
            HVACMode.OFF,
            [HVACMode.FAN_ONLY, HVACMode.OFF],
            id="overheat_fan_only",
        ),
        pytest.param(
            "HvacPowerStateOff",
            False,
            HVACMode.OFF,
            [HVACMode.FAN_ONLY, HVACMode.OFF],
            id="off_fan_only",
        ),
    ],
)
async def test_climate_streaming_hvac_power(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
    hvac_power: str,
    ac_enabled: bool,
    expected: HVACMode,
    expected_modes: list[HVACMode],
) -> None:
    """Tests the streaming HVAC mode and modes from HvacPower and HvacACEnabled."""

    await setup_platform(hass, [Platform.CLIMATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.HVAC_POWER: hvac_power,
                Signal.HVAC_AC_ENABLED: ac_enabled,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    state = hass.states.get("climate.test_climate")
    assert state.state == expected
    assert state.attributes[ATTR_HVAC_MODES] == expected_modes


@pytest.mark.parametrize(
    ("ac_enabled", "expected"),
    [
        pytest.param(True, HVACMode.HEAT_COOL, id="ac"),
        pytest.param(False, HVACMode.FAN_ONLY, id="fan_only"),
    ],
)
async def test_climate_streaming_turn_on(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
    ac_enabled: bool,
    expected: HVACMode,
) -> None:
    """Tests turning on streaming climate starts it in the enabled mode."""

    await setup_platform(hass, [Platform.CLIMATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.HVAC_POWER: "HvacPowerStateOff",
                Signal.HVAC_AC_ENABLED: ac_enabled,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.auto_conditioning_start",
        return_value=COMMAND_OK,
    ) as mock_start:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: ["climate.test_climate"]},
            blocking=True,
        )
    mock_start.assert_called_once()
    assert hass.states.get("climate.test_climate").state == expected


async def test_climate_streaming_fan_only_rejects_heat_cool(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests heat/cool is not offered while the A/C is disabled."""

    await setup_platform(hass, [Platform.CLIMATE])

    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {Signal.HVAC_AC_ENABLED: False},
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {
                ATTR_ENTITY_ID: ["climate.test_climate"],
                ATTR_HVAC_MODE: HVACMode.HEAT_COOL,
            },
            blocking=True,
        )


async def test_climate_streaming_hvac_ac_enabled_changes(
    hass: HomeAssistant,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that A/C changes switch the modes, and the mode while climate is on."""

    entry = await setup_platform(hass, [Platform.CLIMATE])

    for data, expected, expected_modes in (
        (
            {Signal.HVAC_POWER: "HvacPowerStateOn"},
            HVACMode.HEAT_COOL,
            [HVACMode.HEAT_COOL, HVACMode.OFF],
        ),
        (
            {Signal.HVAC_AC_ENABLED: False},
            HVACMode.FAN_ONLY,
            [HVACMode.FAN_ONLY, HVACMode.OFF],
        ),
        (
            {Signal.HVAC_AC_ENABLED: True},
            HVACMode.HEAT_COOL,
            [HVACMode.HEAT_COOL, HVACMode.OFF],
        ),
        (
            {Signal.HVAC_POWER: "HvacPowerStateOff"},
            HVACMode.OFF,
            [HVACMode.HEAT_COOL, HVACMode.OFF],
        ),
        (
            {Signal.HVAC_AC_ENABLED: False},
            HVACMode.OFF,
            [HVACMode.FAN_ONLY, HVACMode.OFF],
        ),
        (
            {Signal.HVAC_POWER: "HvacPowerStateOn"},
            HVACMode.FAN_ONLY,
            [HVACMode.FAN_ONLY, HVACMode.OFF],
        ),
    ):
        mock_add_listener.send(
            {
                "vin": VEHICLE_DATA_ALT["response"]["vin"],
                "data": data,
                "createdAt": "2024-10-04T10:45:17.537Z",
            }
        )
        await hass.async_block_till_done()
        state = hass.states.get("climate.test_climate")
        assert state.state == expected
        assert state.attributes[ATTR_HVAC_MODES] == expected_modes

    await reload_platform(hass, entry, [Platform.CLIMATE])
    state = hass.states.get("climate.test_climate")
    assert state.state == HVACMode.FAN_ONLY
    assert state.attributes[ATTR_HVAC_MODES] == [HVACMode.FAN_ONLY, HVACMode.OFF]

    # The restored A/C state still applies when climate power is streamed again
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {Signal.HVAC_POWER: "HvacPowerStateOn"},
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()
    assert hass.states.get("climate.test_climate").state == HVACMode.FAN_ONLY
