"""Intégration Home Assistant : réseau Astuce (lignes Transdev Rouen)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import DOMAIN, STATIC_REFRESH_HOUR, STATIC_REFRESH_MINUTE
from .coordinator import AstuceRouenCoordinator
from .gtfs_static import GtfsStatic

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    gtfs = GtfsStatic(hass)
    await gtfs.async_ensure_loaded()

    coordinator = AstuceRouenCoordinator(hass, gtfs)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "gtfs": gtfs,
        "coordinator": coordinator,
    }

    async def _refresh_static(_now) -> None:
        try:
            await gtfs.async_refresh()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Échec du rafraîchissement du GTFS Astuce : %s", err)

    unsub = async_track_time_change(
        hass,
        _refresh_static,
        hour=STATIC_REFRESH_HOUR,
        minute=STATIC_REFRESH_MINUTE,
        second=0,
    )
    hass.data[DOMAIN][entry.entry_id]["unsub_static_refresh"] = unsub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharge l'entrée quand un arrêt est ajouté/retiré via les options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data and data.get("unsub_static_refresh"):
            data["unsub_static_refresh"]()
    return unloaded
