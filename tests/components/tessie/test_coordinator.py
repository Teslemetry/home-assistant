"""Test the Tessie sensor platform."""

from copy import deepcopy
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from tesla_fleet_api.exceptions import (
    Forbidden,
    InvalidToken,
    MissingToken,
    RateLimited,
)

from homeassistant.components.tessie import PLATFORMS
from homeassistant.components.tessie.const import DOMAIN
from homeassistant.components.tessie.coordinator import (
    TESSIE_ENERGY_HISTORY_INTERVAL,
    TESSIE_FLEET_API_SYNC_INTERVAL,
    TESSIE_SYNC_INTERVAL,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from .common import (
    ENERGY_HISTORY,
    ERROR_AUTH,
    ERROR_CONNECTION,
    ERROR_UNKNOWN,
    setup_platform,
)

from tests.common import async_fire_time_changed

WAIT = timedelta(seconds=TESSIE_SYNC_INTERVAL)
RETRY_AFTER = timedelta(seconds=300)


async def test_coordinator_online(
    hass: HomeAssistant, mock_get_state, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the coordinator handles online vehicles."""

    await setup_platform(hass, PLATFORMS)

    freezer.tick(WAIT)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_get_state.assert_called_once()
    assert hass.states.get("binary_sensor.test_status").state == STATE_ON


async def test_coordinator_clienterror(
    hass: HomeAssistant, mock_get_state, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the coordinator handles client errors."""

    mock_get_state.side_effect = ERROR_UNKNOWN
    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])
    coordinator = entry.runtime_data.vehicles[0].data_coordinator

    freezer.tick(WAIT)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_get_state.assert_called_once()
    assert hass.states.get("binary_sensor.test_status").state == STATE_UNAVAILABLE
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.translation_domain == DOMAIN
    assert coordinator.last_exception.translation_key == "cannot_connect"


async def test_coordinator_auth(
    hass: HomeAssistant, mock_get_state, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the coordinator handles auth errors."""

    mock_get_state.side_effect = ERROR_AUTH
    await setup_platform(hass, [Platform.BINARY_SENSOR])

    freezer.tick(WAIT)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_get_state.assert_called_once()


async def test_coordinator_connection(
    hass: HomeAssistant, mock_get_state, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the coordinator handles connection errors."""

    mock_get_state.side_effect = ERROR_CONNECTION
    entry = await setup_platform(hass, [Platform.BINARY_SENSOR])
    coordinator = entry.runtime_data.vehicles[0].data_coordinator
    freezer.tick(WAIT)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_get_state.assert_called_once()
    assert hass.states.get("binary_sensor.test_status").state == STATE_UNAVAILABLE
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.translation_domain == DOMAIN
    assert coordinator.last_exception.translation_key == "cannot_connect"


@pytest.mark.parametrize(
    ("mock_fixture", "interval"),
    [
        ("mock_get_state", WAIT),
        ("mock_live_status", TESSIE_FLEET_API_SYNC_INTERVAL),
        ("mock_site_info", TESSIE_FLEET_API_SYNC_INTERVAL),
        ("mock_energy_history", TESSIE_ENERGY_HISTORY_INTERVAL),
    ],
    ids=["state", "live", "info", "history"],
)
@pytest.mark.parametrize(
    ("after", "calls_at_interval", "calls_at_retry_after"),
    [
        pytest.param(str(RETRY_AFTER.seconds), 1, 2, id="seconds"),
        pytest.param(None, 2, 3, id="missing"),
        pytest.param("Wed, 21 Oct 2026 07:28:00 GMT", 2, 3, id="http-date"),
        pytest.param("-300", 2, 3, id="negative"),
        pytest.param("inf", 2, 3, id="infinite"),
    ],
)
async def test_coordinator_rate_limited(
    hass: HomeAssistant,
    mock_fixture: str,
    interval: timedelta,
    after: str | None,
    calls_at_interval: int,
    calls_at_retry_after: int,
    request: pytest.FixtureRequest,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tests that a 429 defers the next refresh only for a usable Retry-After."""

    mock = request.getfixturevalue(mock_fixture)
    await setup_platform(hass, [Platform.SENSOR])

    mock.reset_mock()
    mock.side_effect = RateLimited({"reset": None, "after": after})
    freezer.tick(interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock.assert_called_once()
    assert "Unexpected error" not in caplog.text

    # A usable Retry-After skips the normal interval, anything else falls back to it.
    mock.side_effect = None
    freezer.tick(interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock.call_count == calls_at_interval

    freezer.tick(RETRY_AFTER - interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert mock.call_count == calls_at_retry_after


async def test_coordinator_live_error(
    hass: HomeAssistant, mock_live_status, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the energy live coordinator handles fleet errors."""

    entry = await setup_platform(hass, [Platform.SENSOR])
    coordinator = entry.runtime_data.energysites[0].live_coordinator
    assert coordinator is not None

    mock_live_status.reset_mock()
    mock_live_status.side_effect = Forbidden
    freezer.tick(TESSIE_FLEET_API_SYNC_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_live_status.assert_called_once()
    assert hass.states.get("sensor.energy_site_solar_power").state == STATE_UNAVAILABLE
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.translation_domain == DOMAIN
    assert coordinator.last_exception.translation_key == "cannot_connect"


async def test_coordinator_info_error(
    hass: HomeAssistant, mock_site_info, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the energy info coordinator handles fleet errors."""

    entry = await setup_platform(hass, [Platform.SENSOR])
    coordinator = entry.runtime_data.energysites[0].info_coordinator

    mock_site_info.reset_mock()
    mock_site_info.side_effect = Forbidden
    freezer.tick(TESSIE_FLEET_API_SYNC_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_site_info.assert_called_once()
    assert (
        hass.states.get("sensor.energy_site_vpp_backup_reserve").state
        == STATE_UNAVAILABLE
    )
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.translation_domain == DOMAIN
    assert coordinator.last_exception.translation_key == "cannot_connect"


@pytest.mark.parametrize(
    ("mock_fixture", "side_effect"),
    [
        ("mock_live_status", InvalidToken),
        ("mock_site_info", InvalidToken),
        ("mock_site_info", MissingToken),
        ("mock_energy_history", InvalidToken),
        ("mock_energy_history", MissingToken),
    ],
)
async def test_coordinator_reauth(
    hass: HomeAssistant,
    mock_fixture: str,
    side_effect: type[Exception],
    request: pytest.FixtureRequest,
) -> None:
    """Tests that energy coordinators handle auth errors."""

    mock = request.getfixturevalue(mock_fixture)
    mock.side_effect = side_effect
    entry = await setup_platform(hass, [Platform.SENSOR])
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_coordinator_energy_history_error(
    hass: HomeAssistant, mock_energy_history, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the energy history coordinator handles fleet errors."""

    entry = await setup_platform(hass, [Platform.SENSOR])
    coordinator = entry.runtime_data.energysites[0].history_coordinator
    assert coordinator is not None

    mock_energy_history.reset_mock()
    mock_energy_history.side_effect = Forbidden
    freezer.tick(TESSIE_ENERGY_HISTORY_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_energy_history.assert_called_once()
    assert (
        hass.states.get("sensor.energy_site_grid_imported").state == STATE_UNAVAILABLE
    )
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.translation_domain == DOMAIN
    assert coordinator.last_exception.translation_key == "cannot_connect"


async def test_coordinator_energy_history_invalid_data(
    hass: HomeAssistant, mock_energy_history, freezer: FrozenDateTimeFactory
) -> None:
    """Tests that the energy history coordinator handles invalid data gracefully."""

    entry = await setup_platform(hass, [Platform.SENSOR])
    coordinator = entry.runtime_data.energysites[0].history_coordinator
    assert coordinator is not None

    # Capture state after successful initial load
    state_before = hass.states.get("sensor.energy_site_grid_imported").state

    mock_energy_history.reset_mock()
    mock_energy_history.side_effect = lambda *a, **kw: {"response": {}}
    freezer.tick(TESSIE_ENERGY_HISTORY_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_energy_history.assert_called_once()

    # Sensor should retain last good state rather than becoming unavailable
    assert hass.states.get("sensor.energy_site_grid_imported").state == state_before
    assert coordinator.last_exception is None


async def test_coordinator_energy_history_cold_start_invalid_data(
    hass: HomeAssistant, mock_energy_history, freezer: FrozenDateTimeFactory
) -> None:
    """Tests cold-start fallback when first energy history fetch has invalid data."""

    mock_energy_history.side_effect = lambda *a, **kw: {"response": {}}
    entry = await setup_platform(hass, [Platform.SENSOR])
    coordinator = entry.runtime_data.energysites[0].history_coordinator
    assert coordinator is not None

    # Coordinator should not have raised an exception; data stays empty
    assert coordinator.last_exception is None
    assert coordinator.data == {}

    # Sensor should be unknown until the first successful fetch
    assert hass.states.get("sensor.energy_site_grid_imported").state == STATE_UNKNOWN

    # Now recover: restore valid energy history data and trigger an update
    mock_energy_history.side_effect = lambda *a, **kw: deepcopy(ENERGY_HISTORY)
    mock_energy_history.reset_mock()
    freezer.tick(TESSIE_ENERGY_HISTORY_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    mock_energy_history.assert_called_once()

    # Coordinator should have real data and no exception
    assert coordinator.last_exception is None
    assert coordinator.data["solar_energy_exported"] == 724
