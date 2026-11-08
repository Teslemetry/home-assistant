"""Test the Teslemetry switch platform."""

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed
from syrupy.assertion import SnapshotAssertion
from tesla_fleet_api.exceptions import InvalidCommand, InvalidRequest, TeslaFleetError
from teslemetry_stream import Signal

from homeassistant.components.labs import async_update_preview_feature
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
    NumberService,
    NumberServiceArgument,
)
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SwitchService,
)
from homeassistant.components.teslemetry.const import (
    DOMAIN,
    LABS_CHARGE_ON_SOLAR_FEATURE,
)
from homeassistant.components.teslemetry.coordinator import VEHICLE_INTERVAL
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    CommonServiceArgument,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from . import (
    assert_entities,
    assert_entities_alt,
    mock_config_entry,
    reload_platform,
    setup_platform,
)
from .const import COMMAND_ERRORS, COMMAND_OK, PRODUCTS, VEHICLE_DATA_ALT, VIN


async def _async_enable_charge_on_solar_preview_feature(hass: HomeAssistant) -> None:
    """Enable the Teslemetry charge-on-solar preview feature."""
    assert await async_setup_component(hass, "labs", {})
    await async_update_preview_feature(hass, DOMAIN, LABS_CHARGE_ON_SOLAR_FEATURE, True)


async def test_switch(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the switch entities are correct."""

    entry = await setup_platform(hass, [Platform.SWITCH])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


async def test_switch_alt(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_vehicle_data: AsyncMock,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the switch entities are correct."""

    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    entry = await setup_platform(hass, [Platform.SWITCH])
    assert_entities_alt(hass, entry.entry_id, entity_registry, snapshot)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("name", "on", "off"),
    [
        ("test_charge", "Vehicle.charge_start", "Vehicle.charge_stop"),
        (
            "test_auto_seat_climate_left",
            "Vehicle.remote_auto_seat_climate_request",
            "Vehicle.remote_auto_seat_climate_request",
        ),
        (
            "test_auto_seat_climate_right",
            "Vehicle.remote_auto_seat_climate_request",
            "Vehicle.remote_auto_seat_climate_request",
        ),
        (
            "test_auto_steering_wheel_heater",
            "Vehicle.remote_auto_steering_wheel_heat_climate_request",
            "Vehicle.remote_auto_steering_wheel_heat_climate_request",
        ),
        (
            "test_defrost",
            "Vehicle.set_preconditioning_max",
            "Vehicle.set_preconditioning_max",
        ),
        (
            "energy_site_storm_watch",
            "EnergySite.storm_mode",
            "EnergySite.storm_mode",
        ),
        (
            "energy_site_allow_charging_from_grid",
            "EnergySite.grid_import_export",
            "EnergySite.grid_import_export",
        ),
        (
            "test_sentry_mode",
            "Vehicle.set_sentry_mode",
            "Vehicle.set_sentry_mode",
        ),
    ],
)
async def test_switch_services(
    hass: HomeAssistant, name: str, on: str, off: str
) -> None:
    """Tests that the switch service calls work."""

    await setup_platform(hass, [Platform.SWITCH])

    entity_id = f"switch.{name}"
    with patch(
        f"tesla_fleet_api.teslemetry.{on}",
        return_value=COMMAND_OK,
    ) as call:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: entity_id},
            blocking=True,
        )
        state = hass.states.get(entity_id)
        assert state.state == STATE_ON
        call.assert_called_once()

    with patch(
        f"tesla_fleet_api.teslemetry.{off}",
        return_value=COMMAND_OK,
    ) as call:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_OFF,
            {CommonServiceArgument.ENTITY_ID: entity_id},
            blocking=True,
        )
        state = hass.states.get(entity_id)
        assert state.state == STATE_OFF
        call.assert_called_once()


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize("response", COMMAND_ERRORS)
async def test_switch_command_errors(hass: HomeAssistant, response: dict) -> None:
    """Tests that vehicle command failures raise HomeAssistantError."""

    await setup_platform(hass, [Platform.SWITCH])

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_start",
            return_value=response,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: "switch.test_charge"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("service", "method", "reason", "expected"),
    [
        pytest.param(
            SERVICE_TURN_ON,
            "Vehicle.charge_start",
            "is_charging",
            STATE_ON,
            id="charge_start_is_charging",
        ),
        pytest.param(
            SERVICE_TURN_OFF,
            "Vehicle.charge_stop",
            "not_charging",
            STATE_OFF,
            id="charge_stop_not_charging",
        ),
    ],
)
async def test_switch_charge_accepted_reason(
    hass: HomeAssistant, service: str, method: str, reason: str, expected: str
) -> None:
    """Tests that charge commands already in the requested state do not raise."""

    await setup_platform(hass, [Platform.SWITCH])

    with patch(
        f"tesla_fleet_api.teslemetry.{method}",
        return_value={"response": {"result": False, "reason": reason}},
    ) as call:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            service,
            {ATTR_ENTITY_ID: "switch.test_charge"},
            blocking=True,
        )
    call.assert_called_once()
    assert hass.states.get("switch.test_charge").state == expected


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize(
    ("side_effect", "message"),
    [
        pytest.param(
            InvalidCommand,
            "Command returned exception: The data request or command is unknown.",
            id="no_data",
        ),
        pytest.param(
            InvalidRequest(
                {"error": "invalid_request", "error_description": "detail from server"}
            ),
            "Command returned exception: detail from server",
            id="error_description",
        ),
        pytest.param(
            InvalidRequest(
                {
                    "response": None,
                    "error": "vehicle rejected the command",
                    "error_description": "",
                }
            ),
            "Command returned exception: vehicle rejected the command",
            id="error",
        ),
        pytest.param(
            InvalidCommand({"error": "invalid_command", "error_description": ""}),
            "Command returned exception: The data request or command is unknown.",
            id="error_is_key",
        ),
        pytest.param(
            InvalidRequest({"response": None}),
            "Command returned exception: The request body is not valid",
            id="no_error_detail",
        ),
    ],
)
async def test_switch_command_exception(
    hass: HomeAssistant,
    side_effect: type[TeslaFleetError] | TeslaFleetError,
    message: str,
) -> None:
    """Tests that an energy command SDK exception raises HomeAssistantError."""

    await setup_platform(hass, [Platform.SWITCH])

    with (
        patch(
            "tesla_fleet_api.teslemetry.EnergySite.storm_mode",
            side_effect=side_effect,
        ),
        pytest.raises(HomeAssistantError, match=f"^{message}$"),
    ):
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: "switch.energy_site_storm_watch"},
            blocking=True,
        )


async def test_switch_streaming(
    hass: HomeAssistant,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the switch entities with streaming are correct."""

    entry = await setup_platform(hass, [Platform.SWITCH])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.SENTRY_MODE: "SentryModeStateIdle",
                Signal.AUTO_SEAT_CLIMATE_LEFT: True,
                Signal.AUTO_SEAT_CLIMATE_RIGHT: False,
                Signal.HVAC_STEERING_WHEEL_HEAT_AUTO: True,
                Signal.DEFROST_MODE: "DefrostModeStateOff",
                Signal.DETAILED_CHARGE_STATE: "DetailedChargeStateCharging",
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    # Reload the entry
    await reload_platform(hass, entry, [Platform.SWITCH])

    # Assert the entities restored their values with concrete assertions
    assert hass.states.get("switch.test_sentry_mode").state == STATE_ON
    assert hass.states.get("switch.test_auto_seat_climate_left").state == STATE_ON
    assert hass.states.get("switch.test_auto_seat_climate_right").state == STATE_OFF
    assert hass.states.get("switch.test_auto_steering_wheel_heater").state == STATE_ON
    assert hass.states.get("switch.test_defrost").state == STATE_OFF
    assert hass.states.get("switch.test_charge").state == STATE_ON


async def test_charge_on_solar_switch_disabled_by_default(
    hass: HomeAssistant,
) -> None:
    """Test charge-on-solar switch is disabled by default."""
    await setup_platform(hass, [Platform.SWITCH])

    assert hass.states.get("switch.test_charge_on_solar") is None


async def test_charge_on_solar_switch_enabled_by_labs(
    hass: HomeAssistant,
) -> None:
    """Test charge-on-solar switch appears when Labs feature is enabled."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.SWITCH])

    assert (state := hass.states.get("switch.test_charge_on_solar")) is not None
    assert state.attributes["assumed_state"] is True


@pytest.mark.parametrize(
    ("service", "enabled", "expected_state"),
    [
        (SERVICE_TURN_ON, True, STATE_ON),
        (SERVICE_TURN_OFF, False, STATE_OFF),
    ],
)
async def test_charge_on_solar_switch_services(
    hass: HomeAssistant,
    service: str,
    enabled: bool,
    expected_state: str,
) -> None:
    """Test charge-on-solar switch service calls use the default lower limit."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch("teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc") as (
        listener
    ):
        listener.return_value = lambda: None
        entry = await setup_platform(hass, [Platform.SWITCH])

        for call in listener.call_args_list:
            call.args[0](91)

        with patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            return_value=COMMAND_OK,
        ) as command:
            await hass.services.async_call(
                SWITCH_DOMAIN,
                service,
                {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
                blocking=True,
            )
            command.assert_called_once_with(
                enabled=enabled,
                lower_charge_limit=20,
                upper_charge_limit=91,
            )

        assert (state := hass.states.get("switch.test_charge_on_solar")) is not None
        assert state.state == expected_state
        assert state.attributes["assumed_state"] is True

        await reload_platform(hass, entry, [Platform.SWITCH])

        assert (restored := hass.states.get("switch.test_charge_on_solar")) is not None
        assert restored.state == expected_state
        assert restored.attributes["assumed_state"] is True


async def test_charge_on_solar_switch_services_polling(
    hass: HomeAssistant,
    mock_legacy: AsyncMock,
) -> None:
    """Test charge-on-solar switch service calls fetch the polled charge limit."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    await setup_platform(hass, [Platform.SWITCH])

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=20,
            upper_charge_limit=80,
        )

    assert (state := hass.states.get("switch.test_charge_on_solar")) is not None
    assert state.state == STATE_ON


@pytest.mark.usefixtures("entity_registry_enabled_by_default", "mock_old_firmware")
async def test_charge_on_solar_switch_services_old_firmware(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a non-polling vehicle below the streaming firmware still fetches the polled charge limit."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    # The charge limit number is the polling entity that keeps the coordinator running.
    await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

    # This vehicle's raw poll flag is off, so its coordinator gets no initial
    # refresh; wait for the first poll so the charge limit is known.
    freezer.tick(VEHICLE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=20,
            upper_charge_limit=80,
        )

    assert (state := hass.states.get("switch.test_charge_on_solar")) is not None
    assert state.state == STATE_ON


async def test_charge_on_solar_switch_uses_lower_limit_number(
    hass: HomeAssistant,
) -> None:
    """Test the switch sends the value set on the lower limit number entity."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch("teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc") as (
        listener
    ):
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        for call in listener.call_args_list:
            call.args[0](91)
        await hass.async_block_till_done()

    await hass.services.async_call(
        NUMBER_DOMAIN,
        NumberService.SET_VALUE,
        {
            CommonServiceArgument.ENTITY_ID: "number.test_charge_on_solar_lower_limit",
            NumberServiceArgument.VALUE: 40,
        },
        blocking=True,
    )

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=40,
            upper_charge_limit=91,
        )


async def test_charge_on_solar_switch_turn_on_uses_restored_charge_limit(
    hass: HomeAssistant,
) -> None:
    """Test turning on after a restart uses the restored charge limit, not a guess."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch("teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc") as (
        listener
    ):
        listener.return_value = lambda: None
        entry = await setup_platform(hass, [Platform.SWITCH])

        for call in listener.call_args_list:
            call.args[0](65)

        await reload_platform(hass, entry, [Platform.SWITCH])

        with patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            return_value=COMMAND_OK,
        ) as command:
            await hass.services.async_call(
                SWITCH_DOMAIN,
                SwitchService.TURN_ON,
                {CommonServiceArgument.ENTITY_ID: "switch.test_charge_on_solar"},
                blocking=True,
            )
            command.assert_called_once_with(
                enabled=True,
                lower_charge_limit=20,
                upper_charge_limit=65,
            )


async def test_charge_on_solar_switch_uses_limit_when_number_disabled(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test the switch still sends the user's limit once the number entity is registry-disabled."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch("teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc") as (
        listener
    ):
        listener.return_value = lambda: None
        entry = await setup_platform(hass, [Platform.SWITCH, Platform.NUMBER])

        await hass.services.async_call(
            NUMBER_DOMAIN,
            NumberService.SET_VALUE,
            {
                CommonServiceArgument.ENTITY_ID: "number.test_charge_on_solar_lower_limit",
                NumberServiceArgument.VALUE: 35,
            },
            blocking=True,
        )

        entity_registry.async_update_entity(
            "number.test_charge_on_solar_lower_limit",
            disabled_by=er.RegistryEntryDisabler.USER,
        )
        await hass.async_block_till_done()

        await reload_platform(hass, entry, [Platform.SWITCH, Platform.NUMBER])

    assert hass.states.get("number.test_charge_on_solar_lower_limit") is None

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=35,
            upper_charge_limit=None,
        )


async def test_charge_on_solar_switch_uses_stored_limit_when_number_disabled(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    entity_registry: er.EntityRegistry,
) -> None:
    """Test the switch sends the stored limit after a restart with the number long disabled."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    # No restore state exists for the disabled number, as once it has expired.
    hass_storage[f"{DOMAIN}.charge_on_solar.{entry.entry_id}"] = {
        "version": 1,
        "data": {VIN: {"enabled": False, "lower_limit": 35, "charge_limit_soc": None}},
    }
    entity_registry.async_get_or_create(
        NUMBER_DOMAIN,
        DOMAIN,
        f"{VIN}-charge_on_solar_lower_limit",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    with patch(
        "homeassistant.components.teslemetry.PLATFORMS",
        [Platform.SWITCH, Platform.NUMBER],
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("number.test_charge_on_solar_lower_limit") is None
    assert (state := hass.states.get("switch.test_charge_on_solar")) is not None
    assert state.state == STATE_OFF

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
        return_value=COMMAND_OK,
    ) as command:
        await hass.services.async_call(
            SWITCH_DOMAIN,
            SwitchService.TURN_ON,
            {CommonServiceArgument.ENTITY_ID: "switch.test_charge_on_solar"},
            blocking=True,
        )
        command.assert_called_once_with(
            enabled=True,
            lower_charge_limit=35,
            upper_charge_limit=None,
        )


async def test_charge_on_solar_switch_turn_on_omits_unknown_charge_limit(
    hass: HomeAssistant,
) -> None:
    """Test turning on omits the upper limit rather than guessing when unknown."""
    await _async_enable_charge_on_solar_preview_feature(hass)

    with patch("teslemetry_stream.TeslemetryStreamVehicle.listen_ChargeLimitSoc") as (
        listener
    ):
        listener.return_value = lambda: None
        await setup_platform(hass, [Platform.SWITCH])

        with patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            return_value=COMMAND_OK,
        ) as command:
            await hass.services.async_call(
                SWITCH_DOMAIN,
                SwitchService.TURN_ON,
                {CommonServiceArgument.ENTITY_ID: "switch.test_charge_on_solar"},
                blocking=True,
            )
            command.assert_called_once_with(
                enabled=True,
                lower_charge_limit=20,
                upper_charge_limit=None,
            )


CHARGE_ON_SOLAR_STORAGE = {
    "version": 1,
    "data": {VIN: {"enabled": True, "lower_limit": 20, "charge_limit_soc": 80}},
}
CHARGE_ON_SOLAR_READ = {
    "response": {"enabled": False, "lowerChargeLimit": 30, "upperChargeLimit": 80}
}


async def _async_setup_charge_on_solar(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Set up the charge-on-solar entities with the feature stored as enabled."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    entry = mock_config_entry()
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}.charge_on_solar.{entry.entry_id}"] = deepcopy(
        CHARGE_ON_SOLAR_STORAGE
    )
    with patch(
        "homeassistant.components.teslemetry.PLATFORMS",
        [Platform.SWITCH, Platform.NUMBER],
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(
    ("domain", "service", "service_data"),
    [
        pytest.param(
            SWITCH_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: "switch.test_charge_on_solar"},
            id="switch",
        ),
        pytest.param(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 40},
            id="number",
        ),
    ],
)
async def test_charge_on_solar_command_reads_settings(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    domain: str,
    service: str,
    service_data: dict[str, Any],
) -> None:
    """Test a successful command is followed by reading the vehicle's own settings."""
    await _async_setup_charge_on_solar(hass, hass_storage)

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            return_value=COMMAND_OK,
        ),
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.get_charge_on_solar",
            return_value=CHARGE_ON_SOLAR_READ,
        ) as read,
    ):
        await hass.services.async_call(domain, service, service_data, blocking=True)
    read.assert_called_once_with()

    assert (switch := hass.states.get("switch.test_charge_on_solar")) is not None
    assert switch.state == STATE_OFF
    assert (number := hass.states.get("number.test_charge_on_solar_lower_limit"))
    assert number.state == "30"


@pytest.mark.parametrize(
    "read",
    [
        pytest.param({"side_effect": TeslaFleetError}, id="error"),
        pytest.param({"return_value": COMMAND_OK}, id="no_settings"),
    ],
)
async def test_charge_on_solar_command_keeps_settings_without_read(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    read: dict[str, Any],
) -> None:
    """Test the sent settings are kept when the vehicle's own cannot be read."""
    await _async_setup_charge_on_solar(hass, hass_storage)

    with (
        patch(
            "tesla_fleet_api.teslemetry.Vehicle.charge_on_solar",
            return_value=COMMAND_OK,
        ),
        patch("tesla_fleet_api.teslemetry.Vehicle.get_charge_on_solar", **read),
    ):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: "number.test_charge_on_solar_lower_limit", ATTR_VALUE: 40},
            blocking=True,
        )

    assert (switch := hass.states.get("switch.test_charge_on_solar")) is not None
    assert switch.state == STATE_ON
    assert (number := hass.states.get("number.test_charge_on_solar_lower_limit"))
    assert number.state == "40"


@pytest.mark.parametrize(
    ("vehicle_state", "read_count", "expected_state", "expected_lower_limit"),
    [
        pytest.param("online", 1, STATE_OFF, "30", id="online"),
        pytest.param("asleep", 0, STATE_ON, "20", id="asleep"),
    ],
)
async def test_charge_on_solar_setup_reads_settings_only_when_online(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    mock_products: AsyncMock,
    vehicle_state: str,
    read_count: int,
    expected_state: str,
    expected_lower_limit: str,
) -> None:
    """Test setup reads the vehicle's settings only when that cannot wake it."""
    products = deepcopy(PRODUCTS)
    products["response"][0]["state"] = vehicle_state
    mock_products.return_value = products

    with patch(
        "tesla_fleet_api.teslemetry.Vehicle.get_charge_on_solar",
        return_value=CHARGE_ON_SOLAR_READ,
    ) as read:
        await _async_setup_charge_on_solar(hass, hass_storage)
    assert read.call_count == read_count

    assert (switch := hass.states.get("switch.test_charge_on_solar")) is not None
    assert switch.state == expected_state
    assert (number := hass.states.get("number.test_charge_on_solar_lower_limit"))
    assert number.state == expected_lower_limit


async def test_disable_charge_on_solar_preview_removes_registry_entries(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test disabling preview removes charge-on-solar switch from entity registry."""
    await _async_enable_charge_on_solar_preview_feature(hass)
    entry = await setup_platform(hass, [Platform.SWITCH])

    assert entity_registry.async_get("switch.test_charge_on_solar") is not None

    with patch.object(hass.config_entries, "async_schedule_reload"):
        await async_update_preview_feature(
            hass, DOMAIN, LABS_CHARGE_ON_SOLAR_FEATURE, False
        )
        await hass.async_block_till_done()

    await reload_platform(hass, entry, [Platform.SWITCH])

    assert entity_registry.async_get("switch.test_charge_on_solar") is None
