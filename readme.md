# Powerbaas Home Assistant Integration

This Home Assistant integration connects your Powerbaas devices to Home Assistant. It currently supports two device types, added side by side through the same integration:

- **P1 Meter** - monitor your energy meter, solar and dynamic tariff data
- **Boiler Controller** - drive a boiler to soak up solar surplus

## Installation

### Via HACS (Recommended)
1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL
6. Select "Integration" as category
7. Click "Add"
8. Find "Powerbaas" in the integration list and install it

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

- **[P1 Meter](docs/p1-meter.md)** - energy meter, solar and dynamic tariff sensors
- **[Boiler Controller](docs/boiler-controller.md)** - control modes, calibration and the sensors/services it exposes

## Support

For issues related to this Home Assistant integration, please use the GitHub Issues page of this repository.

For questions about the Powerbaas device itself, visit [powerbaas.nl](https://www.powerbaas.nl).
