"""Climate platform for Tessie integration."""

from itertools import chain
from typing import Any, override

from tessie_api import (
    set_climate_keeper_mode,
    start_cabin_overheat_protection,
    start_climate_preconditioning,
    stop_cabin_overheat_protection,
    stop_climate,
)

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TessieConfigEntry
from .const import DOMAIN, TessieClimateKeeper
from .entity import TessieEntity
from .models import TessieVehicleData

PARALLEL_UPDATES = 0

# FanOnly currently not supported by upstream library
COP_MODES = {"Off": HVACMode.OFF, "On": HVACMode.COOL}

DRIVER_TEMP = "climate_state_driver_temp_setting"
PASSENGER_TEMP = "climate_state_passenger_temp_setting"
PRESET_SYNC = "sync"
PRESET_SPLIT = "split"
PASSENGER_FEATURES = (
    ClimateEntityFeature.TURN_ON
    | ClimateEntityFeature.TURN_OFF
    | ClimateEntityFeature.PRESET_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TessieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Tessie Climate platform from a config entry."""
    data = entry.runtime_data

    async_add_entities(
        chain(
            (TessieClimateEntity(vehicle) for vehicle in data.vehicles),
            (TessiePassengerClimateEntity(vehicle) for vehicle in data.vehicles),
            (
                TessieCabinOverheatProtectionClimateEntity(vehicle)
                for vehicle in data.vehicles
            ),
        )
    )


class TessieCabinClimateEntity(TessieEntity, ClimateEntity):
    """Vehicle cabin climate control for one front seat."""

    _attr_precision = PRECISION_HALVES
    _attr_min_temp = 15
    _attr_max_temp = 28
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT_COOL, HVACMode.OFF]

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode."""
        if self.get("climate_state_is_climate_on"):
            return HVACMode.HEAT_COOL
        return HVACMode.OFF

    @property
    @override
    def native_current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.get("climate_state_inside_temp")

    @property
    @override
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return self.get("climate_state_max_avail_temp", self._attr_max_temp)

    @property
    @override
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return self.get("climate_state_min_avail_temp", self._attr_min_temp)

    @override
    async def async_turn_on(self) -> None:
        """Set the climate state to on."""
        await self.run(start_climate_preconditioning)
        self.set(("climate_state_is_climate_on", True))

    @override
    async def async_turn_off(self) -> None:
        """Set the climate state to off."""
        await self.run(stop_climate)
        self.set(("climate_state_is_climate_on", False))

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the climate mode and state."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()


class TessieClimateEntity(TessieCabinClimateEntity):
    """Vehicle Location Climate Class."""

    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes: list = [
        TessieClimateKeeper.OFF,
        TessieClimateKeeper.ON,
        TessieClimateKeeper.DOG,
        TessieClimateKeeper.CAMP,
    ]

    def __init__(
        self,
        vehicle: TessieVehicleData,
    ) -> None:
        """Initialize the Climate entity."""
        super().__init__(vehicle, "primary")

    @property
    @override
    def native_target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self.get(DRIVER_TEMP)

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return self.get("climate_state_climate_keeper_mode")

    @override
    async def async_turn_off(self) -> None:
        """Set the climate state to off."""
        await self.run(stop_climate)
        self.set(
            ("climate_state_is_climate_on", False),
            ("climate_state_climate_keeper_mode", "off"),
        )

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the climate temperature."""
        if mode := kwargs.get(ATTR_HVAC_MODE):
            await self.async_set_hvac_mode(mode)

        if temp := kwargs.get(ATTR_TEMPERATURE):
            # A passenger set point that differs from the driver's is split, so keep it
            passenger_temp = self.get(PASSENGER_TEMP)
            if passenger_temp is None or passenger_temp == self.get(DRIVER_TEMP):
                passenger_temp = temp

            await self.run(
                self.api.set_temps(driver_temp=temp, passenger_temp=passenger_temp)
            )
            self.set((DRIVER_TEMP, temp), (PASSENGER_TEMP, passenger_temp))

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the climate preset mode."""
        await self.run(
            set_climate_keeper_mode, mode=self._attr_preset_modes.index(preset_mode)
        )
        self.set(
            (
                "climate_state_climate_keeper_mode",
                preset_mode,
            ),
            (
                "climate_state_is_climate_on",
                preset_mode != self._attr_preset_modes[0],
            ),
        )


class TessiePassengerClimateEntity(TessieCabinClimateEntity):
    """Vehicle passenger climate control, synced with the driver or split."""

    _attr_preset_modes = [PRESET_SYNC, PRESET_SPLIT]
    _attr_entity_registry_enabled_default = False
    _split_selected = False

    def __init__(
        self,
        vehicle: TessieVehicleData,
    ) -> None:
        """Initialize the passenger climate entity."""
        super().__init__(vehicle, "passenger_temp")

    @override
    def _async_update_attrs(self) -> None:
        """Derive the preset from the set points again on each poll."""
        self._split_selected = False

    @property
    @override
    def native_target_temperature(self) -> float | None:
        """Return the passenger temperature."""
        return self.get(PASSENGER_TEMP)

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return sync or split, derived from the set points as the vehicle reports no sync state."""
        driver_temp = self.get(DRIVER_TEMP)
        passenger_temp = self.get(PASSENGER_TEMP)
        if driver_temp is None or passenger_temp is None:
            return None
        if driver_temp != passenger_temp or self._split_selected:
            return PRESET_SPLIT
        return PRESET_SYNC

    @property
    @override
    def supported_features(self) -> ClimateEntityFeature:
        """Allow a target temperature only when split."""
        if self.preset_mode == PRESET_SPLIT:
            return PASSENGER_FEATURES | ClimateEntityFeature.TARGET_TEMPERATURE
        return PASSENGER_FEATURES

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the passenger temperature, keeping the driver temperature."""
        if mode := kwargs.get(ATTR_HVAC_MODE):
            await self.async_set_hvac_mode(mode)

        if temp := kwargs.get(ATTR_TEMPERATURE):
            await self.run(
                self.api.set_temps(
                    driver_temp=self.get(DRIVER_TEMP), passenger_temp=temp
                )
            )
            self._split_selected = False
            self.set((PASSENGER_TEMP, temp))

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Sync the passenger with the driver, or allow a split temperature."""
        if (driver_temp := self.get(DRIVER_TEMP)) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="driver_temperature_unknown",
            )

        if preset_mode == PRESET_SYNC:
            await self.run(
                self.api.set_temps(driver_temp=driver_temp, passenger_temp=driver_temp)
            )
            self._split_selected = False
            self.set((PASSENGER_TEMP, driver_temp))
        else:
            self._split_selected = True
            self.async_write_ha_state()


class TessieCabinOverheatProtectionClimateEntity(TessieEntity, ClimateEntity):
    """Vehicle Cabin Overheat Protection."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL]
    _attr_entity_registry_enabled_default = False
    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        vehicle: TessieVehicleData,
    ) -> None:
        """Initialize the cabin overheat protection climate entity."""
        super().__init__(vehicle, "climate_state_cabin_overheat_protection")

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return current cabin overheat protection mode."""
        if (state := self._value) is None:
            return None
        return COP_MODES.get(state)

    @override
    async def async_turn_on(self) -> None:
        """Set the cabin overheat protection state to on."""
        await self.async_set_hvac_mode(HVACMode.COOL)

    @override
    async def async_turn_off(self) -> None:
        """Set the cabin overheat protection state to off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the cabin overheat protection mode."""
        if hvac_mode == HVACMode.OFF:
            await self.run(stop_cabin_overheat_protection)
            self.set((self.key, "Off"))
        elif hvac_mode == HVACMode.COOL:
            await self.run(start_cabin_overheat_protection)
            self.set((self.key, "On"))
