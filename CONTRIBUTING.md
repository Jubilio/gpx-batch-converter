# Contributing

Contributions, bug reports and documentation improvements are welcome.

## Development setup

1. Clone the repository.
2. Copy or link the `gpx_batch_converter` folder into the active QGIS
   profile's `python/plugins` directory.
3. Enable the plugin in QGIS.
4. Use the sample file in `test_data/sample_test.gpx` for a basic test.
5. Confirm that the plugin works without errors in the supported QGIS
   version before opening a pull request.

## Code guidelines

- Write code comments and user-facing strings in English.
- Keep the plugin compatible with QGIS 3.28 and QGIS 4 where practical.
- Do not commit `__pycache__`, generated UI files, local outputs or packaged
  ZIP releases.
- Keep GDAL subprocess calls cancellable.
- Do not access QGIS GUI objects from a background task.

## Coordinate regression tests

With the GDAL Python bindings, `ogr2ogr` and `ogrinfo` available, run:

```bash
python -m unittest discover -s tests -v
```

The tests exercise all five output formats in individual and merged modes,
including multipart endpoints, coordinate precision, null geometries,
cancellation rollback and preservation of source attributes. If QGIS is
unavailable, only its task/signal wrapper is stubbed; GDAL conversions are
real. A manual check inside QGIS is still required before release.
