"""Update platform for Teslemetry integration."""

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Self, override

from tesla_fleet_api import firmware_at_least
from tesla_fleet_api.const import Scope
from tesla_fleet_api.router import VehicleRouter
from tesla_fleet_api.teslemetry import Vehicle

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
    UpdateEntityStateAttribute,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from . import TeslemetryConfigEntry
from .entity import (
    TeslemetryRootEntity,
    TeslemetryVehiclePollingEntity,
    TeslemetryVehicleStreamEntity,
)
from .helpers import handle_vehicle_command
from .models import TeslemetryVehicleData

AVAILABLE = "available"
DOWNLOADING = "downloading"
INSTALLING = "installing"
WIFI_WAIT = "downloading_wifi_wait"
SCHEDULED = "scheduled"

# The start time is vehicle local time read as UTC, so allow for the timezone skew
SCHEDULED_EXPIRY = timedelta(days=1)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslemetryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Teslemetry update platform from a config entry."""

    async_add_entities(
        TeslemetryVehiclePollingUpdateEntity(vehicle, entry.runtime_data.scopes)
        if vehicle.poll or not firmware_at_least(vehicle.firmware, "2024.44.25")
        else TeslemetryStreamingUpdateEntity(vehicle, entry.runtime_data.scopes)
        for vehicle in entry.runtime_data.vehicles
    )


class TeslemetryUpdateEntity(TeslemetryRootEntity, UpdateEntity):
    """Teslemetry Updates entity."""

    api: Vehicle | VehicleRouter
    _attr_supported_features = UpdateEntityFeature.PROGRESS

    @override
    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        self.raise_for_scope(Scope.VEHICLE_CMDS)

        await handle_vehicle_command(self.api.schedule_software_update(offset_sec=0))
        self._attr_in_progress = True
        self.async_write_ha_state()


class TeslemetryVehiclePollingUpdateEntity(
    TeslemetryVehiclePollingEntity, TeslemetryUpdateEntity
):
    """Teslemetry Updates entity."""

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Update."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        super().__init__(
            data,
            "vehicle_state_software_update_status",
        )

    @override
    def _async_update_attrs(self) -> None:
        """Update the attributes of the entity."""

        # Supported Features
        if self.scoped and self._value in (
            AVAILABLE,
            SCHEDULED,
        ):
            # Only allow install when an update has been fully downloaded
            self._attr_supported_features = (
                UpdateEntityFeature.PROGRESS | UpdateEntityFeature.INSTALL
            )
        else:
            self._attr_supported_features = UpdateEntityFeature.PROGRESS

        # Installed Version
        self._attr_installed_version = self.get("vehicle_state_car_version")
        if self._attr_installed_version is not None:
            # Remove build from version
            self._attr_installed_version = self._attr_installed_version.split(" ")[0]

        # Latest Version
        if self._value in (
            AVAILABLE,
            SCHEDULED,
            INSTALLING,
            DOWNLOADING,
            WIFI_WAIT,
        ):
            self._attr_latest_version = self.coordinator.data[
                "vehicle_state_software_update_version"
            ]
        else:
            self._attr_latest_version = self._attr_installed_version

        # In Progress
        if self._value in (
            SCHEDULED,
            INSTALLING,
        ):
            self._attr_in_progress = True
            if install_perc := self.get("vehicle_state_software_update_install_perc"):
                self._attr_update_percentage = install_perc
        else:
            self._attr_in_progress = False
            self._attr_update_percentage = None


@dataclass
class TeslemetryUpdateExtraStoredData(ExtraStoredData):
    """Scheduled start time stored with the update state."""

    scheduled_start_time: int | None

    @override
    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of the scheduled start time."""
        return asdict(self)

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> Self:
        """Initialize the scheduled start time from a dict."""
        return cls(restored["scheduled_start_time"])


class TeslemetryStreamingUpdateEntity(
    TeslemetryVehicleStreamEntity, TeslemetryUpdateEntity, RestoreEntity
):
    """Teslemetry Updates entity."""

    _download_percentage: int = 0
    _install_percentage: int = 0
    _scheduled_start_time: int | None = None

    def __init__(
        self,
        data: TeslemetryVehicleData,
        scopes: list[Scope],
    ) -> None:
        """Initialize the Update."""
        self.scoped = Scope.VEHICLE_CMDS in scopes
        super().__init__(
            data,
            "vehicle_state_software_update_status",
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_state()) is not None:
            self._attr_installed_version = state.attributes.get(
                UpdateEntityStateAttribute.INSTALLED_VERSION
            )
            self._attr_latest_version = state.attributes.get(
                UpdateEntityStateAttribute.LATEST_VERSION
            )
            self._attr_supported_features = UpdateEntityFeature(
                state.attributes.get(
                    "supported_features", self._attr_supported_features
                )
            )
            # A restored in-progress flag with installed == latest is a missed
            # completion; restoring it would re-strand the entity every restart.
            if not self._up_to_date:
                self._attr_in_progress = state.attributes.get(
                    UpdateEntityStateAttribute.IN_PROGRESS, False
                )
                self._attr_update_percentage = state.attributes.get(
                    UpdateEntityStateAttribute.UPDATE_PERCENTAGE
                )
            if (extra_data := await self.async_get_last_extra_data()) is not None:
                self._scheduled_start_time = TeslemetryUpdateExtraStoredData.from_dict(
                    extra_data.as_dict()
                ).scheduled_start_time
            # Without a percentage, in progress came from a schedule that may have expired
            if self._attr_update_percentage is None:
                self._async_update_progress()
            self.async_write_ha_state()

        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_SoftwareUpdateDownloadPercentComplete(
                self._async_handle_software_update_download_percent_complete
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_SoftwareUpdateInstallationPercentComplete(
                self._async_handle_software_update_installation_percent_complete
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_SoftwareUpdateScheduledStartTime(
                self._async_handle_software_update_scheduled_start_time
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_SoftwareUpdateVersion(
                self._async_handle_software_update_version
            )
        )
        self.async_on_remove(
            self.vehicle.stream_vehicle.listen_Version(self._async_handle_version)
        )

    def _async_handle_software_update_download_percent_complete(
        self, value: float | None
    ) -> None:
        """Handle software update download percent complete."""

        self._download_percentage = round(value) if value is not None else 0
        if self.scoped and self._download_percentage == 100:
            self._attr_supported_features = (
                UpdateEntityFeature.PROGRESS | UpdateEntityFeature.INSTALL
            )
        else:
            self._attr_supported_features = UpdateEntityFeature.PROGRESS
        self._async_update_progress()
        self.async_write_ha_state()

    def _async_handle_software_update_installation_percent_complete(
        self, value: float | None
    ) -> None:
        """Handle software update installation percent complete."""

        self._install_percentage = round(value) if value is not None else 0
        self._async_update_progress()
        self.async_write_ha_state()

    def _async_handle_software_update_scheduled_start_time(
        self, value: int | None
    ) -> None:
        """Handle software update scheduled start time."""

        self._scheduled_start_time = value
        self._async_update_progress()
        self.async_write_ha_state()

    def _async_handle_software_update_version(self, value: str | None) -> None:
        """Handle software update version."""

        self._attr_latest_version = (
            value if value and value != " " else self._attr_installed_version
        )
        self.async_write_ha_state()

    def _async_handle_version(self, value: str | None) -> None:
        """Handle version."""

        if value is not None:
            self._attr_installed_version = value.split(" ")[0]
            # A new installed version can be the only signal that an offline
            # install finished, so re-evaluate any lingering scheduled flag.
            self._async_update_progress()
            self.async_write_ha_state()

    @property
    @override
    def extra_restore_state_data(self) -> TeslemetryUpdateExtraStoredData:
        """Return the scheduled start time to restore."""
        return TeslemetryUpdateExtraStoredData(self._scheduled_start_time)

    @property
    def _up_to_date(self) -> bool:
        """Return True when the installed version matches the known latest version."""
        return (
            self._attr_installed_version is not None
            and self._attr_installed_version == self._attr_latest_version
        )

    def _async_update_progress(self) -> None:
        """Update the progress of the update."""

        if 0 < self._download_percentage < 100:
            self._attr_in_progress = True
            self._attr_update_percentage = self._download_percentage
        elif 10 < self._install_percentage < 100:
            self._attr_in_progress = True
            self._attr_update_percentage = self._install_percentage
        elif (
            self._scheduled_start_time is not None
            and self._scheduled_start_time
            > (dt_util.utcnow() - SCHEDULED_EXPIRY).timestamp()
            and not self._up_to_date
        ):
            self._attr_in_progress = True
            self._attr_update_percentage = None
        else:
            self._attr_in_progress = False
            self._attr_update_percentage = None
