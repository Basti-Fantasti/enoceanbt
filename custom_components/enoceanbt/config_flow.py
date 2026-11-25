"""Config flow: teach an EnOcean rocker switch by pressing two of its keys."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from . import DOMAIN
from .rocker import MappingError, derive_mapping
from .teach import TeachCollector

LISTEN_TIMEOUT_S = 30.0
POLL_INTERVAL_S = 0.2

# Placeholder texts that depend on runtime values and therefore cannot live
# in the translation files as fixed strings.
_TEXTS = {
    "de": {
        "first": {"1x2": "oben", "2x2": "links oben"},
        "second": {"1x2": "unten", "2x2": "rechts unten"},
        "rocker": "Taster",
        "actor": "vermutlich Aktor",
        "actor_users": "\n\nWird bereits ausgewertet von: {names}",
    },
    "en": {
        "first": {"1x2": "top", "2x2": "top left"},
        "second": {"1x2": "bottom", "2x2": "bottom right"},
        "rocker": "rocker",
        "actor": "probably actor",
        "actor_users": "\n\nAlready used by: {names}",
    },
}


def _fmt(address: int) -> str:
    return f"0x{address:08X}"


class EnOceanBtConfigFlow(ConfigFlow, domain=DOMAIN):
    """Teach one rocker switch per config entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._layout: str = "2x2"
        self._task: asyncio.Task | None = None
        self._first: TeachCollector | None = None
        self._second: TeachCollector | None = None
        self._address: int | None = None
        self._first_button: str | None = None
        self._mapping: dict | None = None
        self._mapping_error: str = "wrong_pair"
        self._retry_step: str = "listen_first"

    # -- helpers -----------------------------------------------------------

    @property
    def _hub(self):
        return self.hass.data.get(DOMAIN, {}).get("hub")

    def _texts(self) -> dict:
        lang = (self.hass.config.language or "en").split("-")[0]
        return _TEXTS.get(lang, _TEXTS["en"])

    async def _listen(
        self, collector: TeachCollector, exclude: set[int] | None = None
    ) -> None:
        """Feed rocker actions into the collector until ready or timeout."""
        exclude = exclude or set()

        def _on_action(sender, action, t) -> None:
            if sender not in exclude:
                collector.feed(sender, action, t)

        remove = self._hub.add_teach_listener(_on_action)
        try:
            deadline = time.monotonic() + LISTEN_TIMEOUT_S
            while time.monotonic() < deadline:
                if collector.ready(time.monotonic()):
                    return
                await asyncio.sleep(POLL_INTERVAL_S)
        finally:
            remove()

    async def _finish_task(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            await task  # propagate unexpected errors

    def async_remove(self) -> None:
        """Flow closed by the user: stop listening."""
        if self._task is not None and not self._task.done():
            self._task.cancel()

    # -- steps -------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        hub = self._hub
        if hub is None or not hub.connected:
            return self.async_abort(reason="not_connected")
        if user_input is not None:
            self._layout = user_input["layout"]
            return await self.async_step_listen_first()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("layout", default="2x2"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["1x2", "2x2"],
                            translation_key="layout",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_listen_first(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._task is None:
            self._first = TeachCollector()
            exclude = set()
            for uid in self._async_current_ids():
                try:
                    exclude.add(int(uid, 16))
                except (TypeError, ValueError):
                    pass
            self._task = self.hass.async_create_task(
                self._listen(self._first, exclude)
            )
        if not self._task.done():
            return self.async_show_progress(
                step_id="listen_first",
                progress_action="press_first",
                progress_task=self._task,
                description_placeholders={
                    "target": self._texts()["first"][self._layout]
                },
            )
        await self._finish_task()
        if self._first.preselect() is None:
            self._retry_step = "listen_first"
            return self.async_show_progress_done(next_step_id="timeout")
        return self.async_show_progress_done(next_step_id="pick")

    async def async_step_timeout(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if self._retry_step == "listen_second":
                return await self.async_step_listen_second()
            return await self.async_step_listen_first()
        return self.async_show_form(step_id="timeout", data_schema=vol.Schema({}))

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        candidates = self._first.candidates()
        by_addr = {_fmt(c.sender): c for c in candidates}
        chosen = None
        if user_input is not None:
            chosen = by_addr.get(user_input["address"])
        elif len(candidates) == 1:
            chosen = candidates[0]
        if chosen is None:
            texts = self._texts()
            options = [
                selector.SelectOptionDict(
                    value=_fmt(c.sender),
                    label=f"{_fmt(c.sender)} "
                    f"({texts['rocker'] if c.released else texts['actor']})",
                )
                for c in candidates
            ]
            default = self._first.preselect()
            return self.async_show_form(
                step_id="pick",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            "address", default=_fmt(default.sender)
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=options,
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    }
                ),
            )
        self._address = chosen.sender
        self._first_button = chosen.button
        await self.async_set_unique_id(f"{self._address:08X}")
        self._abort_if_unique_id_configured()
        return await self.async_step_listen_second()

    async def async_step_listen_second(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._task is None:
            self._second = TeachCollector(only_sender=self._address, settle_s=0)
            self._task = self.hass.async_create_task(self._listen(self._second))
        if not self._task.done():
            return self.async_show_progress(
                step_id="listen_second",
                progress_action="press_second",
                progress_task=self._task,
                description_placeholders={
                    "target": self._texts()["second"][self._layout]
                },
            )
        await self._finish_task()
        cand = self._second.preselect()
        if cand is None:
            self._retry_step = "listen_second"
            return self.async_show_progress_done(next_step_id="timeout")
        try:
            self._mapping = derive_mapping(
                self._layout, self._first_button, cand.button
            )
        except MappingError as err:
            self._mapping_error = err.reason
            return self.async_show_progress_done(next_step_id="wrong_second")
        return self.async_show_progress_done(next_step_id="confirm")

    async def async_step_wrong_second(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_listen_second()
        return self.async_show_form(
            step_id="wrong_second",
            data_schema=vol.Schema({}),
            errors={"base": self._mapping_error},
            description_placeholders={
                "target": self._texts()["second"][self._layout]
            },
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["name"],
                data={
                    "address": self._address,
                    "layout": self._layout,
                    "mapping": self._mapping,
                    "area_id": user_input.get("area_id"),
                },
            )
        users = self._hub.actor_users(self._address) if self._hub else []
        hint = (
            self._texts()["actor_users"].format(names=", ".join(users))
            if users
            else ""
        )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Optional("area_id"): selector.AreaSelector(),
                }
            ),
            description_placeholders={
                "address": _fmt(self._address),
                "actor_users": hint,
            },
        )
