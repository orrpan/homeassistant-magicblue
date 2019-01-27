import functools
import logging
import threading

import voluptuous as vol

# Import the device class from the component that you want to support
from homeassistant.components.light import (
    ATTR_BRIGHTNESS, ATTR_HS_COLOR, ATTR_EFFECT,
    SUPPORT_COLOR, SUPPORT_BRIGHTNESS, SUPPORT_EFFECT,
    Light, PLATFORM_SCHEMA, SUPPORT_WHITE_VALUE, ATTR_WHITE_VALUE
)

import homeassistant.helpers.config_validation as cv
import homeassistant.util.color as color_util

# Home Assistant depends on 3rd party packages for API specific code.
REQUIREMENTS = [
    #'magicblue==0.5.0',
    'https://github.com/orrpan/magicblue/archive/master.zip'
    '#magicblue==master',
    'bluepy==1.1.4',
    'webcolors'
]

CONF_NAME = 'name'
CONF_ADDRESS = 'address'
CONF_VERSION = 'version'
CONF_HCI_DEVICE_ID = 'hci_device_id'

DEFAULT_VERSION = 9
DEFAULT_HCI_DEVICE_ID = 0

# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_ADDRESS): cv.string,
    vol.Optional(CONF_VERSION, default=DEFAULT_VERSION): cv.positive_int,
    vol.Optional(CONF_HCI_DEVICE_ID, default=DEFAULT_HCI_DEVICE_ID):
        cv.positive_int
})

_LOGGER = logging.getLogger(__name__)


# region Decorators
def comm_lock(blocking=True):
    """
    Lock method (per instance) such that the decorated method cannot be ran from multiple thread simulatinously.
    If blocking = True (default), the thread will wait for the lock to become available and then execute the method.
    If blocking = False, the thread will try to acquire the lock, fail and _not_ execute the method.
    """
    def ensure_lock(instance):
        if not hasattr(instance, '_comm_lock'):
            instance._comm_lock = threading.Lock()

        return instance._comm_lock

    def call_wrapper(func):
        """Call wrapper for decorator."""

        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            """Lock method (per instance) such that the decorated method cannot be ran from multiple thread simulatinously."""

            lock = ensure_lock(self)

            locked = lock.acquire(blocking)
            if locked:
                _LOGGER.debug('comm_lock(): %s.%s: entry', self, func.__name__)
                vals = func(self, *args, **kwargs)
                lock.release()
                _LOGGER.debug('comm_lock(): %s.%s: exit', self, func.__name__)
                return vals

            _LOGGER.debug('comm_lock(): %s.%s: lock not acquired, exiting', self, func.__name__)

        return wrapper

    return call_wrapper
# endregion


# region Home-Assistant
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the MagicBlue platform."""
    from magicblue import MagicBlue

    # Assign configuration variables. The configuration check takes care they are
    # present.
    bulb_name = config.get(CONF_NAME)
    bulb_mac_address = config.get(CONF_ADDRESS)
    bulb_version = config.get(CONF_VERSION)
    hci_device_id = config.get(CONF_HCI_DEVICE_ID)

    bulb = MagicBlue(bulb_mac_address, hci_device_id, bulb_version)

    # Add devices
    add_devices([MagicBlueLight(hass, bulb, bulb_name)])
    

class MagicBlueLight(Light):
    """Representation of an Bluetooth Light."""
    def __init__(self, hass, light, name):
        """Initialize an Bluetooth Light."""

        self.hass = hass
        self._light = light
        self._name = name
        self._is_on = light.is_on
        self._hs_color = light.rgb_color
        self._brightness = light.brightness
        self._available = False
        self._effect = light.effect
        self._effects = [e for e in light.effects.__members__.keys()]
        self._white = light.white

    @property
    def name(self):
        """Return the display name of this light."""
        return self._name

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._is_on

    @property
    def hs_color(self):
        """Return the color property."""
        return self._hs_color

    @property
    def brightness(self):
        """Return the brightness of the light (an integer in the range 1-255)."""
        return self._brightness
    
    @property
    def available(self):
        """Return status of available."""
        return self._available

    @property
    def effect(self):
        """Return the number of effect."""
        return self._effect

    @property
    def effect_list(self):
        """Return the list of supported effects."""
        return self._effects

    @property
    def white(self):
        """Return white."""
        return self._white

    @property
    def supported_features(self):
        """Return the supported features."""
        return SUPPORT_BRIGHTNESS | SUPPORT_COLOR | SUPPORT_EFFECT

    def update(self):
        _LOGGER.debug("%s.update()", self)
        self.hass.add_job(self._update_blocking)

    @comm_lock(False)
    def _update_blocking(self):
        _LOGGER.debug("%s._update_blocking()", self)

        try:
            if not self._light.test_connection():
                self._light.connect()

            self._light.update()
            self._is_on = self._light.is_on
            self._brightness = self._light.brightness
            self._hs_color = color_util.color_RGB_to_hs(*self._light.rgb_color)
            self._effect = self._light.effect
            self._available = True
        except Exception as ex:
            _LOGGER.debug("%s._update_blocking(): Exception during update status: %s", self, ex)
            self._available = False

    @comm_lock()
    def turn_on(self, **kwargs):
        """Instruct the light to turn on."""
        _LOGGER.debug("%s.turn_on()", self)
        if not self._light.test_connection():
            try:
                self._light.connect()
            except Exception as e:
                _LOGGER.error('%s.turn_on(): Could not connect to %s', self, self._light)
                return

        if not self.is_on:
            self._light.turn_on()
        else:
            if ATTR_HS_COLOR in kwargs and ATTR_BRIGHTNESS in kwargs:
                rgb = color_util.color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
                self._light.set_all(rgb, kwargs[ATTR_BRIGHTNESS])
                self._brightness = kwargs[ATTR_BRIGHTNESS]
                self._hs_color = kwargs[ATTR_HS_COLOR]
            elif ATTR_HS_COLOR in kwargs:
                rgb = color_util.color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
                self._light.set_rgb_color(rgb)
                self._hs_color = kwargs[ATTR_HS_COLOR]
            if ATTR_BRIGHTNESS in kwargs:
                self._light.set_brightness(kwargs[ATTR_BRIGHTNESS])
                self._brightness = kwargs[ATTR_BRIGHTNESS]
            if ATTR_EFFECT in kwargs:
                self._light.set_effect(Effect[kwargs[ATTR_EFFECT]])
                self._effect = kwargs[ATTR_EFFECT]

        self._is_on = True

    @comm_lock()
    def turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        _LOGGER.debug("%s: MagicBlueLight.turn_off()", self)
        if not self._light.test_connection():
            try:
                self._light.connect()
            except Exception as e:
                _LOGGER.error('%s.turn_off(): Could not connect to %s', self, self._light)
                return

        self._light.turn_off()
        self._is_on = False

    def __str__(self):
        return "<MagicBlueLight('{}', '{}')>".format(self._light, self._name)

    def __repr__(self):
        return "<MagicBlueLight('{}', '{}')>".format(self._light, self._name)
# endregion
