"""Config flow for the Powerbaas integration.

Adding a device starts with a menu asking which kind of Powerbaas device is
being set up. Each device type's own steps live in its own package under
``devices/`` (see P1MeterFlowMixin / BoilerControllerFlowMixin /
AircoBridgeFlowMixin) and are mixed into this single ConfigFlow class, since
Home Assistant only allows one ConfigFlow per domain.
"""
import logging

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_P1_METER,
    DEVICE_TYPE_BOILER_CONTROLLER,
    DEVICE_TYPE_AIRCO_BRIDGE,
    DISABLED_DEVICE_TYPES,
)
from .devices.p1_meter.config_flow import P1MeterFlowMixin, P1MeterOptionsFlow
from .devices.p1_meter.const import P1_MDNS_HOSTNAME
from .devices.boiler_controller.config_flow import (
    BoilerControllerFlowMixin,
    BoilerControllerOptionsFlow,
)
from .devices.boiler_controller.const import BC_HOST_PREFIX
from .devices.airco_bridge.config_flow import (
    AircoBridgeFlowMixin,
    AircoBridgeOptionsFlow,
)
from .devices.airco_bridge.const import AIRCO_HOST_PREFIX

_LOGGER = logging.getLogger(__name__)


class PowerbaasConfigFlow(
    P1MeterFlowMixin,
    BoilerControllerFlowMixin,
    AircoBridgeFlowMixin,
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Ask which kind of Powerbaas device is being added."""
        menu_options = [
            device_type
            for device_type in (
                DEVICE_TYPE_P1_METER,
                DEVICE_TYPE_BOILER_CONTROLLER,
                DEVICE_TYPE_AIRCO_BRIDGE,
            )
            if device_type not in DISABLED_DEVICE_TYPES
        ]
        return self.async_show_menu(
            step_id="user",
            menu_options=menu_options,
        )

    async def async_step_zeroconf(self, discovery_info):
        """Route Zeroconf discovery to the matching device type's flow.

        Only one class in the MRO can own ``async_step_zeroconf``, so each
        device type's mixin exposes a private handler instead
        (``_async_zeroconf_boiler_controller`` / ``_async_zeroconf_airco_bridge``
        / ``_async_zeroconf_p1_meter``) and this method dispatches to the right
        one based on hostname. Handlers call self.async_set_unique_id(...)
        before creating an entry (hassfest only greps this file for that call,
        so it's noted here to avoid a false-positive "needs to set a unique ID"
        warning).
        """
        hostname = (discovery_info.hostname or discovery_info.name or "").rstrip(".").split(".")[0].lower()

        if any(hostname.startswith(prefix) for prefix in BC_HOST_PREFIX):
            if DEVICE_TYPE_BOILER_CONTROLLER in DISABLED_DEVICE_TYPES:
                return self.async_abort(reason="unsupported_device")
            return await self._async_zeroconf_boiler_controller(discovery_info)
        if any(hostname.startswith(prefix) for prefix in AIRCO_HOST_PREFIX):
            if DEVICE_TYPE_AIRCO_BRIDGE in DISABLED_DEVICE_TYPES:
                return self.async_abort(reason="unsupported_device")
            return await self._async_zeroconf_airco_bridge(discovery_info)
        if hostname == P1_MDNS_HOSTNAME:
            if DEVICE_TYPE_P1_METER in DISABLED_DEVICE_TYPES:
                return self.async_abort(reason="unsupported_device")
            return await self._async_zeroconf_p1_meter(discovery_info)

        return self.async_abort(reason="unsupported_device")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        device_type = config_entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_P1_METER)
        if device_type == DEVICE_TYPE_BOILER_CONTROLLER:
            return BoilerControllerOptionsFlow(config_entry)
        if device_type == DEVICE_TYPE_AIRCO_BRIDGE:
            return AircoBridgeOptionsFlow(config_entry)
        return P1MeterOptionsFlow()
