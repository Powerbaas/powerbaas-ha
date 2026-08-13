# Powerbaas Home Assistant Integration

This Home Assistant integration connects your Powerbaas devices to Home Assistant. It currently supports two device types, added side by side through the same integration:

- **P1 Meter** - monitor your energy meter, solar and dynamic tariff data
- **Boiler Controller** - drive a boiler to soak up solar surplus

## Installation

### Via HACS (Recommended)
1. Navigate to HACS → Integrations → "+ Explore & Download Repos"
2. Search for "Powerbaas"
3. Click on the result and select "Download this Repository with HACS"
4. Refresh your browser (due to a known HA bug that may not update the integration list immediately)
5. Go to "Settings" in the Home Assistant sidebar, then select "Devices & Services"
6. Click the blue "+ Add Integration" button at the bottom right, search for "Powerbaas", and install it

   [![Set up a new integration in Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=powerbaas)

### Manual Installation
1. Copy the `custom_components/powerbaas` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "Powerbaas" and add it

### Upgrading from the old manual setup

If you previously set up Powerbaas in Home Assistant following the [Powerbaas FAQ](https://www.powerbaas.nl/faq/2070705_hoe-koppel-ik-powerbaas-aan-home-assistant) using either the manual YAML `sensor`/`template` configuration, or the old `XiloXL/powerbaas-home-assistant-hacs` custom repository, remove that setup before installing this integration:

- **Manual YAML**: remove the `sensor`/`template` includes and files you added to `configuration.yaml`
- **Old HACS repository**: remove the `XiloXL/powerbaas-home-assistant-hacs` custom repository and integration

This integration replaces both — keeping the old setup alongside it will create duplicate sensors for the same device.

### Adding a device

Go to Settings → Devices & Services → Add Integration → search for "Powerbaas". You'll be asked which type of device to add - repeat this for each additional device, of either type, that you want to configure.

## Devices

- **[P1 Meter](docs/p1-meter.md)** - reads your smart meter (P1 port) and exposes power, energy and dynamic tariff sensors in Home Assistant
- **[Boiler Controller](docs/boiler-controller.md)** - controls a Powerbaas Boiler Controller module, using your extra solar power to heat your boiler instead of sending it back to the grid

## Development & Testing

```bash
pip install -r requirements.txt -r requirements_test.txt

# Whole suite
pytest

# One device's tests
pytest tests/boiler_controller -v
pytest tests/p1_meter -v

# One file / one test
pytest tests/boiler_controller/test_controller.py -v
pytest tests/boiler_controller/test_controller.py::test_async_update_auto_mode_clamps_to_max_heating_watts -v
```

Tests live under `tests/<device_type>/`, mirroring
`custom_components/powerbaas/devices/<device_type>/`. If you're fixing a bug,
see `CLAUDE.md`'s "Testing" section for the reproduce-first workflow this
repo follows.

## Support

For issues related to this Home Assistant integration, please use the GitHub Issues page of this repository.

For questions about the Powerbaas device itself, visit [powerbaas.nl](https://www.powerbaas.nl).
