"""Capteur de perturbation trafic par arrêt suivi."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_STOP_HEADSIGN,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_STOP_ROUTE_ID,
    CONF_STOP_ROUTE_SHORT_NAME,
    CONF_STOP_UID,
    CONF_STOPS,
    DOMAIN,
)
from .coordinator import AstuceRouenCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: AstuceRouenCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    stops = entry.options.get(CONF_STOPS, [])

    entities = [AstucePerturbationBinarySensor(coordinator, entry, stop) for stop in stops]
    async_add_entities(entities)


class _AstuceAlertEntityBase(CoordinatorEntity[AstuceRouenCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AstuceRouenCoordinator, entry: ConfigEntry, stop: dict) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._stop = stop
        self._uid = stop[CONF_STOP_UID]
        self._route_id = stop[CONF_STOP_ROUTE_ID]
        self._stop_id = stop[CONF_STOP_ID]

        device_name = f"{stop[CONF_STOP_NAME]} → {stop[CONF_STOP_HEADSIGN]} ({stop[CONF_STOP_ROUTE_SHORT_NAME]})"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uid)},
            name=device_name,
            manufacturer="Métropole Rouen Normandie / Transdev Rouen",
            model="Arrêt Astuce",
        )

    def _alerts(self) -> list[dict]:
        return self.coordinator.get_alert_messages(self._stop_id, self._route_id)


class AstucePerturbationBinarySensor(_AstuceAlertEntityBase, BinarySensorEntity):
    """Allumé quand une alerte en cours concerne la ligne, l'arrêt ou le réseau."""

    _attr_translation_key = "perturbation"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry, stop) -> None:
        super().__init__(coordinator, entry, stop)
        self._attr_unique_id = f"{entry.entry_id}_{self._uid}_perturbation"

    @property
    def is_on(self) -> bool:
        return len(self._alerts()) > 0
