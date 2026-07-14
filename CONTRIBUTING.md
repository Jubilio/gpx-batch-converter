# Contributing

Contributions, bug reports and documentation improvements are welcome.

## Development setup

1. Clone the repository.
2. Copy or link the `gpx_batch_converter` folder into the active QGIS
   profile's `python/plugins` directory.
3. Enable the plugin in QGIS.
4. Use the sample file in `test_data/sample_complete.gpx` for a basic test.
5. Confirm that the plugin works without errors in the supported QGIS
   version before opening a pull request.

## Code guidelines

- Write code comments and user-facing strings in English.
- Keep the plugin compatible with QGIS 3.28 and QGIS 4 where practical.
- Do not commit `__pycache__`, generated UI files, local outputs or packaged
  ZIP releases.
- Keep GDAL subprocess calls cancellable.
- Do not access QGIS GUI objects from a background task.
