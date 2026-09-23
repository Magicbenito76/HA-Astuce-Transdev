"""Config flow pour Astuce Rouen (lignes Transdev Rouen)."""
from __future__ import annotations

from uuid import uuid4

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_STOP_HEADSIGN,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_STOP_ROUTE_COLOR,
    CONF_STOP_ROUTE_ID,
    CONF_STOP_ROUTE_SHORT_NAME,
    CONF_STOP_UID,
    CONF_STOPS,
    DOMAIN,
)


class AstuceRouenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Créé l'entrée d'intégration. Les arrêts se règlent ensuite via les options."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(
                title="Astuce Rouen (Transdev)",
                data={},
                options={CONF_STOPS: []},
            )
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return AstuceRouenOptionsFlow(config_entry)


class AstuceRouenOptionsFlow(config_entries.OptionsFlow):
    """Ajouter ou retirer des arrêts suivis (ligne → direction → arrêt)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._route_id: str | None = None
        self._headsign: str | None = None

    def _gtfs(self):
        return self.hass.data[DOMAIN][self.config_entry.entry_id]["gtfs"]

    async def async_step_init(self, user_input: dict | None = None):
        stops = self.config_entry.options.get(CONF_STOPS, [])
        menu = ["add_stop"]
        if stops:
            menu.append("remove_stop")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_add_stop(self, user_input: dict | None = None):
        gtfs = self._gtfs()
        lines = gtfs.get_lines()
        if not lines:
            return self.async_abort(reason="gtfs_unavailable")

        if user_input is not None:
            self._route_id = user_input["route_id"]
            return await self.async_step_add_stop_direction()

        schema = vol.Schema({vol.Required("route_id"): vol.In(dict(lines))})
        return self.async_show_form(step_id="add_stop", data_schema=schema)

    async def async_step_add_stop_direction(self, user_input: dict | None = None):
        gtfs = self._gtfs()
        directions = gtfs.get_directions(self._route_id)
        if not directions:
            return self.async_abort(reason="no_direction")

        if user_input is not None:
            self._headsign = user_input["headsign"]
            return await self.async_step_add_stop_stop()

        schema = vol.Schema({vol.Required("headsign"): vol.In({d: d for d in directions})})
        return self.async_show_form(step_id="add_stop_direction", data_schema=schema)

    async def async_step_add_stop_stop(self, user_input: dict | None = None):
        gtfs = self._gtfs()
        stops = gtfs.get_stops_for_direction(self._route_id, self._headsign)
        if not stops:
            return self.async_abort(reason="no_stop")

        if user_input is not None:
            stop_id = user_input["stop_id"]
            stop_name = dict(stops)[stop_id]
            route_info = gtfs.routes[self._route_id]

            new_stop = {
                CONF_STOP_UID: uuid4().hex,
                CONF_STOP_ROUTE_ID: self._route_id,
                CONF_STOP_ROUTE_SHORT_NAME: route_info["short_name"],
                CONF_STOP_ROUTE_COLOR: route_info.get("color"),
                CONF_STOP_HEADSIGN: self._headsign,
                CONF_STOP_ID: stop_id,
                CONF_STOP_NAME: stop_name,
            }
            stops_list = list(self.config_entry.options.get(CONF_STOPS, []))
            stops_list.append(new_stop)
            return self.async_create_entry(title="", data={CONF_STOPS: stops_list})

        schema = vol.Schema({vol.Required("stop_id"): vol.In(dict(stops))})
        return self.async_show_form(step_id="add_stop_stop", data_schema=schema)

    async def async_step_remove_stop(self, user_input: dict | None = None):
        stops_list = list(self.config_entry.options.get(CONF_STOPS, []))
        if not stops_list:
            return self.async_abort(reason="no_stops")

        choices = {
            s[CONF_STOP_UID]: f"{s[CONF_STOP_ROUTE_SHORT_NAME]} → {s[CONF_STOP_HEADSIGN]} ({s[CONF_STOP_NAME]})"
            for s in stops_list
        }

        if user_input is not None:
            remaining = [s for s in stops_list if s[CONF_STOP_UID] != user_input["uid"]]
            return self.async_create_entry(title="", data={CONF_STOPS: remaining})

        schema = vol.Schema({vol.Required("uid"): vol.In(choices)})
        return self.async_show_form(step_id="remove_stop", data_schema=schema)
