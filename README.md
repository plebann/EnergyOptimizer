# Energy Optimizer

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]

_Integration to optimize energy usage in Home Assistant._

**This is a template integration for HACS. Customize it to add your platforms and functionality.**

The integration is ready to be extended with platforms like `sensor`, `binary_sensor`, `switch`, etc.

## Installation

### HACS (Recommended)

1. Add this repository to HACS as a custom repository
2. Search for "Energy Optimizer" in HACS
3. Click Install
4. Restart Home Assistant

### Manual Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `energy_optimizer`.
4. Download _all_ the files from the `custom_components/energy_optimizer/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Energy Optimizer"

## Configuration is done in the UI

<!---->

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[energy_optimizer]: https://github.com/plebann/EnergyOptimizer
[commits-shield]: https://img.shields.io/github/commit-activity/y/plebann/EnergyOptimizer.svg?style=for-the-badge
[commits]: https://github.com/plebann/EnergyOptimizer/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/plebann/EnergyOptimizer.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/plebann/EnergyOptimizer.svg?style=for-the-badge
[releases]: https://github.com/plebann/EnergyOptimizer/releases