"""Run with `python -m unittest discover -s tests -v` in a GDAL environment.

Real GDAL/OGR performs every conversion. When QGIS is unavailable, only its
signal/task wrapper is stubbed; this does not verify the QGIS GUI lifecycle.
"""
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from osgeo import ogr

try:
    import qgis.core  # noqa: F401
except ImportError:
    class Signal:
        def emit(self, *args):
            pass

    class Task:
        CanCancel = 1

        def __init__(self, *args):
            self._cancelled = False

        def isCanceled(self):
            return self._cancelled

        def cancel(self):
            self._cancelled = True

        def setProgress(self, value):
            pass

    qtcore = types.ModuleType("qgis.PyQt.QtCore")
    qtcore.pyqtSignal = lambda *args: Signal()
    core = types.ModuleType("qgis.core")
    core.QgsTask = Task
    core.QgsApplication = type("Application", (), {})
    sys.modules.update({
        "qgis": types.ModuleType("qgis"),
        "qgis.PyQt": types.ModuleType("qgis.PyQt"),
        "qgis.PyQt.QtCore": qtcore,
        "qgis.core": core,
    })

from gpx_batch_converter.conversion_task import (  # noqa: E402
    COORDINATE_FIELDS,
    OUTPUT_FORMATS,
    GpxConversionTask,
    coordinate_values,
)

GPX = '''<?xml version="1.0"?>
<gpx version="1.1" creator="coordinate-tests"
 xmlns="http://www.topografix.com/GPX/1/1">
 <wpt lat="-12.1234567890" lon="40.9876543210">
  <ele>42.5</ele><name>Waypoint</name>
 </wpt>
 <rte><name>Route</name>
  <rtept lat="-13.1" lon="39.2"><name>R1</name></rtept>
  <rtept lat="-13.3" lon="39.4"><name>R2</name></rtept>
 </rte>
 <trk><name>Track</name>
  <trkseg>
   <trkpt lat="-14.1" lon="38.2"><ele>10</ele></trkpt>
   <trkpt lat="-14.3" lon="38.4"><ele>20</ele></trkpt>
  </trkseg>
  <trkseg>
   <trkpt lat="-15.1" lon="37.2"><ele>30</ele></trkpt>
   <trkpt lat="-15.3" lon="37.4"><ele>40</ele></trkpt>
  </trkseg>
 </trk>
</gpx>'''
EXPECTED = {
    "waypoints": [(-12.123456789, 40.987654321)],
    "route_points": [(-13.1, 39.2), (-13.3, 39.4)],
    "track_points": [(-14.1, 38.2), (-14.3, 38.4),
                     (-15.1, 37.2), (-15.3, 37.4)],
    "routes": [(-13.1, 39.2, -13.3, 39.4)],
    "tracks": [(-14.1, 38.2, -15.3, 37.4)],
}


class CoordinateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "field team's sample.gpx"
        self.source.write_text(GPX)

    def task(self, output_format="GeoPackage", merged=False, files=None):
        return GpxConversionTask(
            gpx_files=files or [self.source],
            output_folder=self.root / "out",
            selected_layers=list(COORDINATE_FIELDS),
            output_format=output_format,
            overwrite=True,
            merge_mode=merged,
            merge_prefix="merged",
            executables={name: shutil.which(name) or "/missing/" + name
                         for name in ("ogr2ogr", "ogrinfo")},
        )

    def test_geometry_values_and_empty_segments(self):
        cases = [
            ("POINT Z (40 -12 100)", "waypoints", (-12, 40)),
            ("LINESTRING (39 -13, 40 -14)", "routes", (-13, 39, -14, 40)),
            ("MULTILINESTRING (EMPTY, (39 -13, 40 -14), EMPTY, "
             "(41 -15, 42 -16), EMPTY)", "tracks", (-13, 39, -16, 42)),
            ("POINT EMPTY", "waypoints", (None, None)),
            ("LINESTRING EMPTY", "routes", (None,) * 4),
            ("MULTILINESTRING EMPTY", "tracks", (None,) * 4),
        ]
        for wkt, layer, expected in cases:
            with self.subTest(wkt=wkt):
                geometry = ogr.CreateGeometryFromWkt(wkt)
                before = geometry.ExportToWkt()
                self.assertEqual(coordinate_values(geometry, layer), expected)
                self.assertEqual(geometry.ExportToWkt(), before)
        self.assertEqual(coordinate_values(None, "tracks"), (None,) * 4)

    def make_staging(self, with_conflicting_field=False):
        path = self.root / "staging.gpkg"
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
        layer = ds.CreateLayer("waypoints", geom_type=ogr.wkbPoint)
        if with_conflicting_field:
            layer.CreateField(ogr.FieldDefn("latitude", ogr.OFTString))
        for wkt in ("POINT (40 -12)", None):
            feature = ogr.Feature(layer.GetLayerDefn())
            if wkt:
                feature.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            self.assertEqual(layer.CreateFeature(feature), ogr.OGRERR_NONE)
        feature = layer = ds = None
        return path

    def test_missing_geometry_stays_null(self):
        path = self.make_staging()
        self.assertTrue(self.task()._set_coordinate_attributes(path, "waypoints"))
        ds = ogr.Open(str(path))
        layer = ds.GetLayerByName("waypoints")
        values = [(f.GetField("latitude"), f.GetField("longitude")) for f in layer]
        self.assertEqual(values, [(-12, 40), (None, None)])

    def test_cancellation_rolls_back_coordinate_updates(self):
        path = self.make_staging()
        task = self.task()
        with patch.object(task, "isCanceled", side_effect=[False, True]):
            self.assertFalse(task._set_coordinate_attributes(path, "waypoints"))
        self.assertTrue(task.summary["cancelled"])
        ds = ogr.Open(str(path))
        layer = ds.GetLayerByName("waypoints")
        self.assertTrue(all(f.GetField("latitude") is None for f in layer))

    def test_coordinate_name_collision_is_reported(self):
        path = self.make_staging(with_conflicting_field=True)
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self.task()._set_coordinate_attributes(path, "waypoints")

    @unittest.skipUnless(shutil.which("ogr2ogr") and shutil.which("ogrinfo"),
                         "GDAL command-line tools required")
    def test_all_formats_and_modes(self):
        second = self.root / "second.gpx"
        second.write_text(GPX.replace("Waypoint", "Second waypoint"))
        for output_format in OUTPUT_FORMATS:
            for merged in (False, True):
                with self.subTest(output_format=output_format, merged=merged):
                    task = self.task(output_format, merged, [self.source, second])
                    task.output_folder = self.root / output_format / str(merged)
                    self.assertTrue(task.run(), str(task.exception))
                    self.assertEqual(task.summary["failed"], 0, task.results)
                    self.assertEqual(len(task.output_layers), 5 if merged else 10)
                    for layer_name, expected in EXPECTED.items():
                        path = (task._merged_output_path(layer_name) if merged
                                else task._individual_output_path(self.source, layer_name))
                        expected_rows = expected * (2 if merged else 1)
                        if output_format == "KML":
                            # The basic KML reader ignores ExtendedData, even
                            # though its writer exports it. Check the file
                            # directly and also read fields via LIBKML when
                            # that optional driver is installed.
                            ns = {"k": "http://www.opengis.net/kml/2.2"}
                            placemarks = ET.parse(path).findall(".//k:Placemark", ns)
                            self.assertEqual(len(placemarks), len(expected_rows))
                            for placemark, values in zip(placemarks, expected_rows):
                                data = {item.attrib["name"]: item.text for item in
                                        placemark.findall(".//k:SimpleData", ns)}
                                for field, value in zip(COORDINATE_FIELDS[layer_name], values):
                                    self.assertAlmostEqual(float(data[field]), value, places=9)
                            if ogr.GetDriverByName("LIBKML") is None:
                                continue
                        ds = ogr.Open(str(path))
                        self.assertIsNotNone(ds, str(path))
                        output_layer = (layer_name if merged else task.clean_filename(
                            f"{self.source.stem}_{layer_name}"))
                        layer = (ds.GetLayerByName(output_layer)
                                 if output_format == "GeoPackage" else ds.GetLayer(0))
                        features = list(layer)
                        self.assertEqual(len(features), len(expected_rows))
                        for feature, values in zip(features, expected_rows):
                            for field, value in zip(COORDINATE_FIELDS[layer_name], values):
                                self.assertAlmostEqual(float(feature.GetField(field)),
                                                       value, places=9)
                        if output_format == "GeoPackage":
                            if layer_name == "waypoints":
                                self.assertEqual(features[0].GetField("name"), "Waypoint")
                                self.assertAlmostEqual(features[0].GetField("ele"), 42.5)
                            if layer_name == "tracks":
                                self.assertEqual(features[0].GetGeometryRef().GetGeometryCount(), 2)
                            if merged:
                                self.assertEqual(features[0].GetField("source_file"), self.source.name)
                                self.assertEqual(features[-1].GetField("source_file"), second.name)
                        feature = features = layer = ds = None


if __name__ == "__main__":
    unittest.main()
