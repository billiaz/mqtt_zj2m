"""Configure number in a device through MQTT topic."""
import functools
import logging

import voluptuous as vol

from homeassistant.components import number
from homeassistant.components.number import NumberEntity
from homeassistant.const import (
    CONF_DEVICE,
    CONF_ICON,
    CONF_NAME,
    CONF_OPTIMISTIC,
    CONF_UNIQUE_ID,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType, HomeAssistantType

from . import (
    CONF_COMMAND_TOPIC,
    CONF_QOS,
    CONF_STATE_TOPIC,
    DOMAIN,
    PLATFORMS,
    subscription,
)
from .. import zj2m as zj2m
from .debug_info import log_messages
from .mixins import (
    MQTT_AVAILABILITY_SCHEMA,
    MQTT_ENTITY_DEVICE_INFO_SCHEMA,
    MQTT_JSON_ATTRS_SCHEMA,
    MqttEntity,
    async_setup_entry_helper,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "MQTT Number"
DEFAULT_OPTIMISTIC = False

PLATFORM_SCHEMA = (
   zj2m.MQTT_RW_PLATFORM_SCHEMA.extend(
        {
            vol.Optional(CONF_DEVICE): MQTT_ENTITY_DEVICE_INFO_SCHEMA,
            vol.Optional(CONF_ICON): cv.icon,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
            vol.Optional(CONF_OPTIMISTIC, default=DEFAULT_OPTIMISTIC): cv.boolean,
            vol.Optional(CONF_UNIQUE_ID): cv.string,
        }
    )
    .extend(MQTT_AVAILABILITY_SCHEMA.schema)
    .extend(MQTT_JSON_ATTRS_SCHEMA.schema)
)


async def async_setup_platform(
    hass: HomeAssistantType, config: ConfigType, async_add_entities, discovery_info=None
):
    """Set up MQTT number through configuration.yaml."""
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
    await _async_setup_entity(async_add_entities, config)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up MQTT number dynamically through MQTT discovery."""

    setup = functools.partial(
        _async_setup_entity, async_add_entities, config_entry=config_entry
    )
    await async_setup_entry_helper(hass, number.DOMAIN, setup, PLATFORM_SCHEMA)


async def _async_setup_entity(
    async_add_entities, config, config_entry=None, discovery_data=None
):
    """Set up the MQTT number."""
    async_add_entities([MqttNumber(config, config_entry, discovery_data)])


class MqttNumber(MqttEntity, NumberEntity, RestoreEntity):
    """representation of an MQTT number."""

    def __init__(self, config, config_entry, discovery_data):
        """Initialize the MQTT Number."""
        self._sub_state = None

        self._current_number = None
        self._optimistic = config.get(CONF_OPTIMISTIC)
        self._unique_id = config.get(CONF_UNIQUE_ID)

        NumberEntity.__init__(self)
        MqttEntity.__init__(self, None, config, config_entry, discovery_data)

    @staticmethod
    def config_schema():
        """Return the config schema."""
        return PLATFORM_SCHEMA

    def _setup_from_config(self, config):
        self._config = config

    async def _subscribe_topics(self):
        """(Re)Subscribe to topics."""

        @callback
        @log_messages(self.hass, self.entity_id)
        def message_received(msg):
            """Handle new MQTT messages."""

            try:
                if msg.payload.decode("utf-8").isnumeric():
                    self._current_number = int(msg.payload)
                else:
                    self._current_number = float(msg.payload)
                self.async_write_ha_state()
            except ValueError:
                _LOGGER.warning("We received <%s> which is not a Number", msg.payload)

        if self._config.get(CONF_STATE_TOPIC) is None:
            # Force into optimistic mode.
            self._optimistic = True
        else:
            self._sub_state = await subscription.async_subscribe_topics(
                self.hass,
                self._sub_state,
                {
                    "state_topic": {
                        "topic": self._config.get(CONF_STATE_TOPIC),
                        "msg_callback": message_received,
                        "qos": self._config[CONF_QOS],
                        "encoding": None,
                    }
                },
            )

        if self._optimistic:
            last_state = await self.async_get_last_state()
            if last_state:
                self._current_number = last_state.state

    @property
    def value(self):
        """Return the current value."""
        return self._current_number

    async def async_set_value(self, value: float) -> None:
        """Update the current value."""

        current_number = value

        if value.is_integer():
            current_number = int(value)

        if self._optimistic:
            self._current_number = current_number
            self.async_write_ha_state()

       zj2m.async_publish(
            self.hass,
            self._config[CONF_COMMAND_TOPIC],
            current_number,
            self._config[CONF_QOS],
        )

    @property
    def name(self):
        """Return the name of this number."""
        return self._config[CONF_NAME]

    @property
    def assumed_state(self):
        """Return true if we do optimistic updates."""
        return self._optimistic

    @property
    def icon(self):
        """Return the icon."""
        return self._config.get(CONF_ICON)
