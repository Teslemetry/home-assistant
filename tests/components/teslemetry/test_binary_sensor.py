"""Test the Teslemetry binary sensor platform."""

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

from aiopowerwall import PowerwallConnectionError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from freezegun.api import FrozenDateTimeFactory
import pytest
from syrupy.assertion import SnapshotAssertion
from teslemetry_stream import Signal

from homeassistant.components.teslemetry.const import (
    CONF_SITE_ID,
    DOMAIN,
    SUBENTRY_TYPE_ENERGY_SITE,
)
from homeassistant.components.teslemetry.coordinator import (
    LOCAL_STATUS_INTERVAL,
    VEHICLE_INTERVAL,
)
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from . import assert_entities, assert_entities_alt, mock_config_entry, setup_platform
from .const import METADATA, POWERWALL_STATUS, VEHICLE_DATA_ALT

from tests.common import MockConfigEntry, async_fire_time_changed, mock_restore_cache

SITE_ID = 123456
LOCAL_STATUS_KEYS = (
    "contactor_closed",
    "escan_firmware_updating",
    "grid_ok",
    "microgrid_ok",
    "pw3can_firmware_updating",
    "site_manager_running",
    "site_running",
)

# aiopowerwall's PowerwallClient parses the PEM at construction time, so tests
# that build one need a real (if undersized, for speed) RSA key rather than
# arbitrary bytes.
_TEST_RSA_KEY_PEM = rsa.generate_private_key(
    public_exponent=65537, key_size=1024
).private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensor(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the binary sensor entities are correct."""

    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])
    assert_entities(hass, entry.entry_id, entity_registry, snapshot)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensor_refresh(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    mock_vehicle_data: AsyncMock,
    freezer: FrozenDateTimeFactory,
    mock_legacy: AsyncMock,
) -> None:
    """Tests that the binary sensor entities are correct."""

    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])

    # Refresh
    mock_vehicle_data.return_value = VEHICLE_DATA_ALT
    freezer.tick(VEHICLE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert_entities_alt(hass, entry.entry_id, entity_registry, snapshot)


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensors_streaming(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the binary sensor entities with streaming are correct."""

    freezer.move_to("2024-01-01 00:00:00+00:00")

    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "data": {
                Signal.FD_WINDOW: "WindowStateOpened",
                Signal.FP_WINDOW: "INVALID_VALUE",
                Signal.RD_WINDOW: "WindowStateClosed",
                Signal.RP_WINDOW: "WindowStatePartiallyOpen",
                Signal.DOOR_STATE: {
                    "DriverFront": True,
                    "DriverRear": False,
                    "PassengerFront": False,
                    "PassengerRear": False,
                    "TrunkFront": False,
                    "TrunkRear": False,
                },
                Signal.DRIVER_SEAT_BELT: None,
                Signal.REAR_DEFROST_ENABLED: True,
            },
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    # Reload the entry
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    # Assert the entities restored their values with concrete assertions
    assert hass.states.get("binary_sensor.test_front_driver_window").state == "on"
    assert (
        hass.states.get("binary_sensor.test_front_passenger_window").state
        == STATE_UNKNOWN
    )
    assert hass.states.get("binary_sensor.test_rear_driver_window").state == "off"
    assert hass.states.get("binary_sensor.test_rear_passenger_window").state == "on"
    assert hass.states.get("binary_sensor.test_front_driver_door").state == "on"
    assert hass.states.get("binary_sensor.test_front_passenger_door").state == "off"
    assert hass.states.get("binary_sensor.test_driver_seat_belt").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.test_rear_defroster").state == "on"


@pytest.mark.parametrize("restored_state", [STATE_UNKNOWN, STATE_UNAVAILABLE])
@pytest.mark.parametrize(
    "entity_id",
    ["binary_sensor.test_front_driver_window", "binary_sensor.test_charge_cable"],
)
async def test_binary_sensors_streaming_restore_unknown(
    hass: HomeAssistant,
    entity_id: str,
    restored_state: str,
) -> None:
    """Tests that a restored unknown or unavailable state is not restored as off."""

    mock_restore_cache(hass, (State(entity_id, restored_state),))

    await setup_platform(hass, [Platform.BINARY_SENSOR])

    assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_binary_sensors_connectivity(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_vehicle_data: AsyncMock,
    mock_add_listener: AsyncMock,
) -> None:
    """Tests that the binary sensor entities with streaming are correct."""

    freezer.move_to("2024-01-01 00:00:00+00:00")

    await setup_platform(hass, [Platform.BINARY_SENSOR])

    # Stream update
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "status": "CONNECTED",
            "networkInterface": "cellular",
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    mock_add_listener.send(
        {
            "vin": VEHICLE_DATA_ALT["response"]["vin"],
            "status": "DISCONNECTED",
            "networkInterface": "wifi",
            "createdAt": "2024-10-04T10:45:17.537Z",
        }
    )
    await hass.async_block_till_done()

    # Assert the entities have correct state with concrete assertions
    assert hass.states.get("binary_sensor.test_cellular").state == "on"
    assert hass.states.get("binary_sensor.test_wi_fi").state == "off"


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [
        pytest.param(METADATA["scopes"], True, id="location_scope"),
        pytest.param(
            [scope for scope in METADATA["scopes"] if scope != "vehicle_location"],
            False,
            id="no_location_scope",
        ),
    ],
)
async def test_gps_state_requires_location_scope(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_metadata: AsyncMock,
    scopes: list[str],
    expected: bool,
) -> None:
    """Test the GPS state binary sensor is only created with the location scope."""

    mock_metadata.return_value = {**METADATA, "scopes": scopes}

    await setup_platform(hass, [Platform.BINARY_SENSOR])

    assert (
        entity_registry.async_get_entity_id(
            Platform.BINARY_SENSOR, DOMAIN, "LRW3F7EK4NC700000-gps_state"
        )
        is not None
    ) is expected


async def _setup_paired(hass: HomeAssistant) -> MockConfigEntry:
    """Set up the binary sensor platform with the energy site paired locally."""
    entry = mock_config_entry()
    entry = MockConfigEntry(
        domain=entry.domain,
        version=entry.version,
        minor_version=entry.minor_version,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_ENERGY_SITE,
                unique_id=str(SITE_ID),
                title="Energy Site",
                data={
                    CONF_SITE_ID: SITE_ID,
                    CONF_HOST: "192.168.91.1",
                    CONF_PASSWORD: "abcde",
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "homeassistant.components.teslemetry._async_get_rsa_key_pem",
            return_value=_TEST_RSA_KEY_PEM,
        ),
        patch(
            "homeassistant.components.teslemetry.PLATFORMS", [Platform.BINARY_SENSOR]
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _local_entity_ids(entity_registry: er.EntityRegistry) -> dict[str, str]:
    """Return the entity ids of the local status binary sensors by key."""
    return {
        key: entity_id
        for key in LOCAL_STATUS_KEYS
        if (
            entity_id := entity_registry.async_get_entity_id(
                Platform.BINARY_SENSOR, DOMAIN, f"{SITE_ID}-{key}"
            )
        )
    }


def _without(*path: str) -> dict[str, Any]:
    """Return the gateway status without the key at a path."""
    data = deepcopy(POWERWALL_STATUS)
    parent = data
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]
    return data


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_local_binary_sensors(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test a paired energy site creates the local status binary sensors."""
    await _setup_paired(hass)

    entity_ids = _local_entity_ids(entity_registry)
    assert entity_ids.keys() == set(LOCAL_STATUS_KEYS)
    for entity_id in entity_ids.values():
        assert entity_registry.async_get(entity_id) == snapshot(
            name=f"{entity_id}-entry"
        )
        assert hass.states.get(entity_id) == snapshot(name=f"{entity_id}-state")


async def test_local_binary_sensors_unpaired(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_powerwall_status: AsyncMock,
) -> None:
    """Test an energy site without local pairing creates no local sensors."""
    await setup_platform(hass, [Platform.BINARY_SENSOR])

    mock_powerwall_status.assert_not_called()
    assert not _local_entity_ids(entity_registry)


@pytest.mark.parametrize(
    ("status", "missing"),
    [
        pytest.param(_without("pw3Can"), "pw3can_firmware_updating", id="pw3can"),
        pytest.param(
            _without("control", "siteShutdown", "isShutDown"),
            "site_running",
            id="site_shutdown",
        ),
    ],
)
async def test_local_binary_sensors_missing_signal(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_powerwall_status: AsyncMock,
    status: dict[str, Any],
    missing: str,
) -> None:
    """Test a signal absent from the first refresh skips its sensor."""
    mock_powerwall_status.side_effect = None
    mock_powerwall_status.return_value = status

    await _setup_paired(hass)

    assert _local_entity_ids(entity_registry).keys() == set(LOCAL_STATUS_KEYS) - {
        missing
    }


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_local_binary_sensors_first_refresh_failure(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_powerwall_status: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test sensors from a failed first local refresh recover without a reload."""
    mock_powerwall_status.side_effect = PowerwallConnectionError("offline")

    entry = await _setup_paired(hass)

    assert entry.state is ConfigEntryState.LOADED
    entity_ids = _local_entity_ids(entity_registry)
    assert entity_ids.keys() == set(LOCAL_STATUS_KEYS)
    for entity_id in entity_ids.values():
        assert (state := hass.states.get(entity_id))
        assert state.state == STATE_UNAVAILABLE

    mock_powerwall_status.side_effect = None
    mock_powerwall_status.return_value = POWERWALL_STATUS
    freezer.tick(LOCAL_STATUS_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    for entity_id in entity_ids.values():
        assert (state := hass.states.get(entity_id))
        assert state.state != STATE_UNAVAILABLE
    assert (state := hass.states.get(entity_ids["grid_ok"]))
    assert state.state == STATE_ON


async def test_local_binary_sensors_poll_failure(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_powerwall_status: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a failed local poll makes the sensors unavailable until it recovers."""
    await _setup_paired(hass)
    entity_id = _local_entity_ids(entity_registry)["grid_ok"]
    assert (state := hass.states.get(entity_id))
    assert state.state == STATE_ON

    mock_powerwall_status.side_effect = PowerwallConnectionError("offline")
    freezer.tick(LOCAL_STATUS_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (state := hass.states.get(entity_id))
    assert state.state == STATE_UNAVAILABLE

    status = deepcopy(POWERWALL_STATUS)
    status["control"]["islanding"]["gridOK"] = False
    mock_powerwall_status.side_effect = None
    mock_powerwall_status.return_value = status
    freezer.tick(LOCAL_STATUS_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (state := hass.states.get(entity_id))
    assert state.state == STATE_OFF
