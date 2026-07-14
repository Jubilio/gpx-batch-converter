<p align="center">
  <img src="icon.png" alt="GPX Batch Converter icon" width="128">
</p>

<h1 align="center">GPX Batch Converter</h1>

<p align="center">
  A QGIS plugin for batch-converting GPX layers to ESRI Shapefiles.
</p>

<p align="center">
  <img alt="QGIS" src="https://img.shields.io/badge/QGIS-3.28%20to%204.x-589632?logo=qgis&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/Python-PyQGIS-3776AB?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-blue.svg">
  <img alt="Version" src="https://img.shields.io/badge/Version-1.0.3-orange.svg">
</p>

## Overview

**GPX Batch Converter** converts multiple GPX files from a selected folder into ESRI Shapefiles. It runs directly inside QGIS through PyQGIS, so users do not need to open the OSGeo4W Shell or run command-line scripts manually.

The plugin is useful for processing GPS data collected by field teams, including tracks, individual track points, routes, route points and waypoints.

## Features

- Batch-processes all `.gpx` files in a selected folder.
- Converts the following GPX layers:
  - `waypoints`
  - `routes`
  - `route_points`
  - `tracks`
  - `track_points`
- Allows users to select separate input and output folders.
- Creates UTF-8 encoded ESRI Shapefiles.
- Optionally overwrites existing outputs.
- Optionally adds converted layers to the current QGIS project.
- Skips missing or empty GPX layers automatically.
- Displays conversion progress, status messages and a final summary.
- Includes a custom toolbar and Plugin Manager icon.
- Supports both Qt 5 and Qt 6 enum handling.

## Compatibility

| Component        | Supported version                                          |
| ---------------- | ---------------------------------------------------------- |
| QGIS             | 3.28 to 4.x                                                |
| Qt               | Qt 5 and Qt 6                                              |
| Operating system | Windows, Linux and macOS, subject to the QGIS installation |
| Output format    | ESRI Shapefile                                             |

The plugin metadata declares:

```ini
qgisMinimumVersion=3.28
qgisMaximumVersion=4.99
supportsQt6=True
```

## Installation

### Install from ZIP

1. Download the latest plugin ZIP release.
2. Open QGIS.
3. Go to **Plugins → Manage and Install Plugins**.
4. Open the **Install from ZIP** tab.
5. Select the downloaded ZIP file.
6. Click **Install Plugin**.
7. Enable **GPX Batch Converter** if it is not enabled automatically.

After installation, the plugin is available from:

```text
Vector → GPX Batch Converter
```

It is also available from the QGIS plugin toolbar.

### Manual installation

Copy the complete `gpx_batch_converter` folder into the QGIS profile plugin directory.

Typical Windows location:

```text
C:\Users\<USERNAME>\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins\
```

For QGIS 3, the profile folder may instead be located under:

```text
C:\Users\<USERNAME>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\
```

Restart QGIS and enable the plugin from **Manage and Install Plugins**.

## Usage

1. Open **GPX Batch Converter**.
2. Select the folder containing the GPX files.
3. Select the folder where the Shapefiles will be saved.
4. Choose the GPX layers to convert.
5. Choose whether existing Shapefiles should be overwritten.
6. Choose whether converted layers should be added to the current QGIS project.
7. Click **Convert**.

The progress bar and log panel show the current file, completed outputs, skipped layers and errors.

## Output naming

The plugin creates one Shapefile for each selected GPX layer.

For an input file named:

```text
Track_Field_Team_01.gpx
```

The outputs may include:

```text
Track_Field_Team_01_tracks.shp
Track_Field_Team_01_track_points.shp
Track_Field_Team_01_waypoints.shp
```

A Shapefile consists of several related files, such as `.shp`, `.shx`, `.dbf`, `.prj` and `.cpg`. Keep these files together when copying or sharing the output.

## Repository structure

```text
gpx_batch_converter/
├── __init__.py
├── dialog.py
├── icon.png
├── LICENSE
├── metadata.txt
├── plugin.py
└── README.md
```

| File             | Purpose                                           |
| ---------------- | ------------------------------------------------- |
| `__init__.py`  | Provides the QGIS`classFactory()` entry point.  |
| `plugin.py`    | Registers the menu and toolbar action.            |
| `dialog.py`    | Contains the user interface and conversion logic. |
| `metadata.txt` | Defines plugin metadata and QGIS compatibility.   |
| `icon.png`     | Plugin icon used in QGIS.                         |
| `LICENSE`      | MIT licence.                                      |

## Development

The plugin uses the QGIS Python API:

- `QgsVectorLayer` to read GPX sublayers;
- `QgsVectorFileWriter` to create Shapefiles;
- `QgsProject` to add converted outputs to the active project;
- PyQt widgets for the graphical interface.

No external Python package is required beyond the libraries included with QGIS.

### Local development installation

Clone the repository into the QGIS plugin directory:

```bash
git clone https://github.com/Jubilio/gpx-batch-converter.git gpx_batch_converter
```

Restart QGIS or reload the plugin with a plugin-reloading tool during development.

## Known considerations

- GPX files do not always contain every supported layer. Missing or empty layers are skipped.
- ESRI Shapefile field names and data types have format limitations. For workflows requiring fewer restrictions, a future version may add GeoPackage output.
- Existing output files may be locked when they are already open in QGIS or another application. Remove the layer or close the application before overwriting it.
- Large batches may take time to load into the QGIS project when **Add converted Shapefiles to the current QGIS project** is selected.

## Changelog

### Version 1.0.3

- Declared compatibility with QGIS 3.28 through QGIS 4.99.
- Added `supportsQt6=True` for QGIS 4 and Qt 6.
- Fixed the completion-notification variable name conflict.

### Version 1.0.2

- Added a custom icon to the toolbar, menu, dialog and Plugin Manager.

### Version 1.0.1

- Fixed folder selection under QGIS 4 and Qt 6.
- Added compatibility helpers for Qt and QGIS scoped enums.

### Version 1.0.0

- Initial batch GPX-to-Shapefile conversion release.

## Contributing

Contributions, bug reports and feature suggestions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make and test your changes in QGIS.
4. Commit the changes with a clear message.
5. Open a pull request describing the change.

When reporting a problem, include:

- QGIS version;
- operating system;
- plugin version;
- relevant QGIS log or traceback;
- a sample GPX file when it can be shared safely.

## Suggested future improvements

- GeoPackage output.
- Recursive processing of subfolders.
- Merge selected GPX layers into combined outputs.
- Processing Toolbox integration.
- Coordinate reference system options.
- Cancellation support for long-running batches.
- Automated tests and continuous integration.

## Author

**Jubilio Filiano Mausse**
GIS, data management and remote-sensing professional.

## Licence

This project is licensed under the **MIT License**. See the [`LICENSE`](LICENSE) file for details.
