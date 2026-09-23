"""Capteurs Astuce Rouen (Transdev) : un appareil par arrêt suivi."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from .const import (
    ATTR_ALERTS,
    ATTR_DELAY,
    ATTR_DEPARTURES,
    ATTR_DESTINATION,
    ATTR_FULL_MESSAGE,
    ATTR_LINE,
    ATTR_LINE_COLOR,
    ATTR_MESSAGE,
    ATTR_SOURCE,
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

    entities = []
    for stop in stops:
        entities.append(AstuceMinutesSensor(coordinator, entry, stop))
        entities.append(AstuceTimeSensor(coordinator, entry, stop, index=0))
        entities.append(AstuceTimeSensor(coordinator, entry, stop, index=1))
        entities.append(AstuceDestinationSensor(coordinator, entry, stop))
        entities.append(AstucePerturbationMessageSensor(coordinator, entry, stop))
    async_add_entities(entities)


class _AstuceStopEntity(CoordinatorEntity[AstuceRouenCoordinator], SensorEntity):
    """Base commune : un appareil par (ligne, direction, arrêt) suivi."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AstuceRouenCoordinator, entry: ConfigEntry, stop: dict) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._stop = stop
        self._uid = stop[CONF_STOP_UID]
        self._route_id = stop[CONF_STOP_ROUTE_ID]
        self._headsign = stop[CONF_STOP_HEADSIGN]
        self._stop_id = stop[CONF_STOP_ID]

        device_name = f"{stop[CONF_STOP_NAME]} → {stop[CONF_STOP_HEADSIGN]} ({stop[CONF_STOP_ROUTE_SHORT_NAME]})"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._uid)},
            name=device_name,
            manufacturer="Métropole Rouen Normandie / Transdev Rouen",
            model="Arrêt Astuce",
        )

    def _departures(self) -> list[dict]:
        return self.coordinator.get_departures(self._stop_id, self._route_id, self._headsign)


class AstuceMinutesSensor(_AstuceStopEntity):
    """Minutes avant le prochain passage, arrondies à l'inférieur."""

    _attr_translation_key = "minutes_avant_le_prochain_passage"
    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:bus-clock"

    def __init__(self, coordinator, entry, stop) -> None:
        super().__init__(coordinator, entry, stop)
        self._attr_unique_id = f"{entry.entry_id}_{self._uid}_minutes"
        self._unsub_boundary = None

    @property
    def native_value(self):
        deps = self._departures()
        if not deps:
            return None
        delta = deps[0]["time"] - dt_util.utcnow()
        return max(0, int(delta.total_seconds() // 60))

    @property
    def extra_state_attributes(self):
        deps = self._departures()
        if not deps:
            return {}
        first = deps[0]
        route_info = self.coordinator.gtfs.routes.get(self._route_id, {})
        return {
            ATTR_LINE: route_info.get("short_name"),
            ATTR_LINE_COLOR: route_info.get("color"),
            ATTR_DESTINATION: first.get("headsign") or self._headsign,
            ATTR_DELAY: round((first.get("delay") or 0) / 60),
            ATTR_SOURCE: first.get("source"),
            ATTR_DEPARTURES: [
                {
                    "minutes": max(0, int((d["time"] - dt_util.utcnow()).total_seconds() // 60)),
                    "destination": d.get("headsign") or self._headsign,
                    "delay": round((d.get("delay") or 0) / 60),
                    "source": d.get("source"),
                }
                for d in deps
            ],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_boundary_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_boundary:
            self._unsub_boundary()
        await super().async_will_remove_from_hass()

    def _handle_coordinator_update(self) -> None:
        self._schedule_boundary_update()
        super()._handle_coordinator_update()

    def _schedule_boundary_update(self) -> None:
        """Force la mise à jour exactement à la seconde où les minutes changent."""
        if self._unsub_boundary:
            self._unsub_boundary()
            self._unsub_boundary = None

        deps = self._departures()
        if not deps:
            return
        minutes = max(0, int((deps[0]["time"] - dt_util.utcnow()).total_seconds() // 60))
        next_boundary = deps[0]["time"] - timedelta(seconds=minutes * 60)
        if next_boundary <= dt_util.utcnow():
            next_boundary = dt_util.utcnow() + timedelta(seconds=1)

        @callback
        def _at_boundary(_now):
            self._unsub_boundary = None
            self.async_write_ha_state()
            self._schedule_boundary_update()

        self._unsub_boundary = async_track_point_in_time(self.hass, _at_boundary, next_boundary)


class AstuceTimeSensor(_AstuceStopEntity):
    """Heure exacte du prochain passage (index=0) ou du suivant (index=1)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, stop, index: int) -> None:
        super().__init__(coordinator, entry, stop)
        self._index = index
        key = "prochain_passage" if index == 0 else "passage_suivant"
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{self._uid}_{key}"

    @property
    def native_value(self):
        deps = self._departures()
        if len(deps) <= self._index:
            return None
        return deps[self._index]["time"]


class AstuceDestinationSensor(_AstuceStopEntity):
    """Destination affichée par le prochain véhicule."""

    _attr_translation_key = "destination_du_prochain_passage"
    _attr_icon = "mdi:sign-direction"

    def __init__(self, coordinator, entry, stop) -> None:
        super().__init__(coordinator, entry, stop)
        self._attr_unique_id = f"{entry.entry_id}_{self._uid}_destination"

    @property
    def native_value(self):
        deps = self._departures()
        if not deps:
            return self._headsign
        return deps[0].get("headsign") or self._headsign


class AstucePerturbationMessageSensor(_AstuceStopEntity):
    """Texte des alertes en cours (tronqué à 255 caractères, limite HA)."""

    _attr_translation_key = "message_de_perturbation"
    _attr_icon = "mdi:alert"

    def __init__(self, coordinator, entry, stop) -> None:
        super().__init__(coordinator, entry, stop)
        self._attr_unique_id = f"{entry.entry_id}_{self._uid}_message_perturbation"

    def _alerts(self) -> list[dict]:
        return self.coordinator.get_alert_messages(self._stop_id, self._route_id)

    @property
    def native_value(self) -> str:
        alerts = self._alerts()
        if not alerts:
            return "Aucune perturbation"
        return " • ".join(a["message"] for a in alerts if a["message"])[:255]

    @property
    def extra_state_attributes(self) -> dict:
        alerts = self._alerts()
        full = " • ".join(a["full_message"] for a in alerts if a["full_message"])
        return {
            ATTR_MESSAGE: alerts[0]["message"] if alerts else "Aucune perturbation",
            ATTR_FULL_MESSAGE: full or "Aucune perturbation",
            ATTR_ALERTS: alerts,
        }
