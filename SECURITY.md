# Security Policy

## Supported versions

Security fixes are applied to the latest released version of GPX Batch
Converter.

| Version | Supported |
|---|---|
| 1.2.x | Yes |
| Earlier versions | No |

## Reporting a vulnerability

Please do not disclose a suspected vulnerability in a public GitHub issue.

Send a private report to:

**jubiliomausse5@gmail.com**

Include:

- the affected plugin version;
- QGIS version and operating system;
- a clear description of the issue;
- steps or a minimal file required to reproduce it;
- potential impact;
- any suggested remediation.

## Security design

The plugin does not use a command shell to execute GDAL tools. It permits only
the absolute paths to `ogr2ogr` and `ogrinfo` discovered from the active QGIS
environment. Arguments are passed separately with `shell=False`.

Merged-output provenance fields are added using the bundled GDAL/OGR Python
API. No dynamic SQL query is constructed from GPX filenames, paths or layer
names.
