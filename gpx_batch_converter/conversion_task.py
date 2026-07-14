from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from osgeo import ogr

from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import QgsApplication, QgsTask


OUTPUT_FORMATS = {
    "ESRI Shapefile": {
        "driver": "ESRI Shapefile",
        "extension": ".shp",
        "layer_creation_options": ["ENCODING=UTF-8"],
    },
    "GeoPackage": {
        "driver": "GPKG",
        "extension": ".gpkg",
        "layer_creation_options": [],
    },
    "GeoJSON": {
        "driver": "GeoJSON",
        "extension": ".geojson",
        "layer_creation_options": [],
    },
    "KML": {
        "driver": "KML",
        "extension": ".kml",
        "layer_creation_options": [],
    },
    "CSV (geometry as WKT)": {
        "driver": "CSV",
        "extension": ".csv",
        "layer_creation_options": [
            "GEOMETRY=AS_WKT",
            "CREATE_CSVT=YES",
        ],
    },
}


SHAPEFILE_COMPONENTS = (
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".qpj",
    ".sbn",
    ".sbx",
)


def task_can_cancel_flag():
    """Return the cancellable-task flag in QGIS 3 or QGIS 4."""
    scoped_flag = getattr(QgsTask, "Flag", None)
    if scoped_flag is not None:
        return scoped_flag.CanCancel
    return QgsTask.CanCancel


def _candidate_executables(name):
    suffix = ".exe" if os.name == "nt" else ""
    executable_name = f"{name}{suffix}"
    candidates = []

    detected = shutil.which(name)
    if detected:
        candidates.append(Path(detected))

    osgeo_root = os.environ.get("OSGEO4W_ROOT")
    if osgeo_root:
        candidates.append(Path(osgeo_root) / "bin" / executable_name)

    prefix = Path(QgsApplication.prefixPath())
    candidates.extend(
        [
            prefix / executable_name,
            prefix / "bin" / executable_name,
            prefix.parent / "bin" / executable_name,
            prefix.parent.parent / "bin" / executable_name,
            Path(sys.executable).resolve().parent / executable_name,
        ]
    )

    # macOS QGIS application bundle locations.
    if sys.platform == "darwin":
        candidates.extend(
            [
                prefix.parent / "MacOS" / "bin" / executable_name,
                prefix.parent.parent / "MacOS" / "bin" / executable_name,
            ]
        )

    unique = []
    seen = set()
    for candidate in candidates:
        resolved = str(candidate)
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)

    return unique


def find_gdal_executables():
    """
    Locate ogr2ogr and ogrinfo inside the active QGIS/GDAL environment.

    This function must be called from the main QGIS thread before starting
    the background task.
    """
    found = {}

    for executable in ("ogr2ogr", "ogrinfo"):
        for candidate in _candidate_executables(executable):
            if candidate.exists() and candidate.is_file():
                found[executable] = str(candidate)
                break

    return found


class GpxConversionTask(QgsTask):
    """Cancellable background task for batch GPX conversion."""

    messageEmitted = pyqtSignal(str)

    def __init__(
        self,
        gpx_files,
        output_folder,
        selected_layers,
        output_format,
        overwrite,
        merge_mode,
        merge_prefix,
        executables,
        finished_callback=None,
    ):
        super().__init__(
            "GPX Batch Converter",
            task_can_cancel_flag(),
        )

        self.gpx_files = [Path(path) for path in gpx_files]
        self.output_folder = Path(output_folder)
        self.selected_layers = list(selected_layers)
        self.output_format = output_format
        self.format_config = OUTPUT_FORMATS[output_format]
        self.overwrite = bool(overwrite)
        self.merge_mode = bool(merge_mode)
        self.merge_prefix = merge_prefix
        self.ogr2ogr = executables["ogr2ogr"]
        self.ogrinfo = executables["ogrinfo"]
        self.finished_callback = finished_callback

        self.results = []
        self.output_layers = []
        self.summary = {
            "converted": 0,
            "merged_outputs": 0,
            "included": 0,
            "missing_empty": 0,
            "existing_skipped": 0,
            "failed": 0,
            "cancelled": False,
        }

        self.exception = None
        self.cancelled = False
        self._current_process = None

    def run(self):
        try:
            self.output_folder.mkdir(parents=True, exist_ok=True)

            if self.merge_mode:
                return self._run_merged()

            return self._run_individual()

        except Exception as error:
            self.exception = error
            self.messageEmitted.emit(f"Unexpected error: {error}")
            return False

    def finished(self, result):
        """
        Called by QGIS on the main thread after run() has completed.
        """
        if self.finished_callback is not None:
            self.finished_callback(self, result)

    def cancel(self):
        self.cancelled = True
        self.summary["cancelled"] = True
        self._terminate_current_process()
        super().cancel()

    def _terminate_current_process(self):
        process = self._current_process

        if process is None or process.poll() is not None:
            return

        try:
            process.terminate()
            process.wait(timeout=2)
            return
        except (OSError, subprocess.SubprocessError) as terminate_error:
            self.messageEmitted.emit(
                "The GDAL process did not terminate cleanly: "
                f"{terminate_error}. Attempting a forced stop."
            )

        try:
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError) as kill_error:
            self.messageEmitted.emit(
                "The GDAL process could not be forcibly stopped: "
                f"{kill_error}"
            )

    def _validate_gdal_command(self, command):
        """
        Validate a GDAL command before execution.

        Only the previously discovered absolute paths to ogr2ogr and
        ogrinfo are permitted. Arguments are passed as a sequence with
        shell=False, so they are never interpreted by a command shell.
        """
        if not isinstance(command, (list, tuple)) or not command:
            raise ValueError("The GDAL command must be a non-empty sequence.")

        allowed_executables = {
            str(Path(self.ogr2ogr).resolve()),
            str(Path(self.ogrinfo).resolve()),
        }

        executable = str(Path(command[0]).resolve())
        if executable not in allowed_executables:
            raise ValueError(
                "Execution was blocked because the command does not use "
                "an approved GDAL executable."
            )

        validated = []
        for argument in command:
            if not isinstance(argument, (str, os.PathLike)):
                raise TypeError(
                    "Every GDAL command argument must be a string or path."
                )

            value = str(argument)
            if "\x00" in value:
                raise ValueError(
                    "A GDAL command argument contains a null byte."
                )

            validated.append(value)

        return tuple(validated)

    def _run_process(self, command):
        """
        Run one validated GDAL command while checking for cancellation.
        """
        validated_command = self._validate_gdal_command(command)

        creation_flags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags = subprocess.CREATE_NO_WINDOW

        # Security: the executable is restricted to validated absolute GDAL
        # paths, arguments are passed as a tuple, and shell execution is
        # explicitly disabled.  # nosec B603
        process = subprocess.Popen(  # nosec B603
            validated_command,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        self._current_process = process

        try:
            while True:
                if self.isCanceled() or self.cancelled:
                    self._terminate_current_process()
                    stdout, stderr = process.communicate()
                    return None, stdout, stderr, True

                try:
                    stdout, stderr = process.communicate(timeout=0.20)
                    return process.returncode, stdout, stderr, False
                except subprocess.TimeoutExpired:
                    time.sleep(0.02)
        finally:
            self._current_process = None

    @staticmethod
    def clean_filename(name, fallback="gpx_layer"):
        cleaned = re.sub(
            r"[^\w\s-]",
            "",
            str(name),
            flags=re.UNICODE,
        )
        cleaned = re.sub(
            r"\s+",
            "_",
            cleaned.strip(),
        )
        return cleaned[:80] or fallback

    def _record(
        self,
        source_file,
        layer_name,
        status,
        feature_count="",
        output="",
        message="",
    ):
        self.results.append(
            {
                "source_file": str(source_file),
                "layer": str(layer_name),
                "status": str(status),
                "features": feature_count,
                "output": str(output),
                "message": str(message),
            }
        )

    def _advance_progress(self, completed, total):
        if total <= 0:
            self.setProgress(100)
        else:
            self.setProgress(min(100, (completed / total) * 100))

    def _inspect_gpx(self, gpx_file):
        command = [
            self.ogrinfo,
            "-ro",
            "-so",
            "-al",
            str(gpx_file),
        ]

        return_code, stdout, stderr, was_cancelled = self._run_process(
            command
        )

        if was_cancelled:
            return None, "Cancelled"

        if return_code != 0:
            message = stderr.strip() or stdout.strip() or (
                "GDAL could not open the GPX file."
            )
            return None, message

        counts = {}
        current_layer = None

        for raw_line in stdout.splitlines():
            line = raw_line.strip()

            if line.lower().startswith("layer name:"):
                current_layer = line.split(":", 1)[1].strip()
                continue

            if (
                current_layer is not None
                and line.lower().startswith("feature count:")
            ):
                value = line.split(":", 1)[1].strip()
                try:
                    counts[current_layer] = int(value)
                except ValueError:
                    counts[current_layer] = 0

        # Fallback for GDAL builds whose -al output does not expose all counts.
        for layer_name in self.selected_layers:
            if layer_name in counts:
                continue

            command = [
                self.ogrinfo,
                "-ro",
                "-so",
                str(gpx_file),
                layer_name,
            ]

            return_code, stdout, stderr, was_cancelled = (
                self._run_process(command)
            )

            if was_cancelled:
                return None, "Cancelled"

            if return_code != 0:
                counts[layer_name] = 0
                continue

            match = re.search(
                r"Feature Count:\s*(\d+)",
                stdout,
                flags=re.IGNORECASE,
            )
            counts[layer_name] = int(match.group(1)) if match else 0

        return counts, ""

    def _remove_output(self, output_path):
        output_path = Path(output_path)

        if output_path.suffix.lower() == ".shp":
            for extension in SHAPEFILE_COMPONENTS:
                component = output_path.with_suffix(extension)
                if component.exists():
                    component.unlink()
            return

        if output_path.exists():
            output_path.unlink()

        # CSV sidecar containing field types.
        if output_path.suffix.lower() == ".csv":
            csvt_path = output_path.with_suffix(".csvt")
            if csvt_path.exists():
                csvt_path.unlink()

    def _individual_output_path(self, gpx_file, layer_name):
        base_name = self.clean_filename(gpx_file.stem)
        extension = self.format_config["extension"]

        return (
            self.output_folder
            / f"{base_name}_{layer_name}{extension}"
        )

    def _merged_output_path(self, layer_name):
        extension = self.format_config["extension"]

        if self.output_format == "GeoPackage":
            return (
                self.output_folder
                / f"{self.merge_prefix}{extension}"
            )

        return (
            self.output_folder
            / f"{self.merge_prefix}_{layer_name}{extension}"
        )

    def _layer_uri(self, output_path, layer_name):
        if self.output_format == "GeoPackage":
            return f"{output_path}|layername={layer_name}"
        return str(output_path)

    def _add_output_descriptor(
        self,
        output_path,
        layer_name,
        display_name,
    ):
        self.output_layers.append(
            {
                "uri": self._layer_uri(output_path, layer_name),
                "name": display_name,
            }
        )

    def _translate_command(
        self,
        source_path,
        source_layer,
        output_path,
        output_layer,
    ):
        command = [
            self.ogr2ogr,
            "-f",
            self.format_config["driver"],
            "-overwrite",
            "-skipfailures",
        ]

        for option in self.format_config["layer_creation_options"]:
            command.extend(["-lco", option])

        command.extend(
            [
                str(output_path),
                str(source_path),
                source_layer,
                "-nln",
                output_layer,
            ]
        )

        return command

    def _stage_append_command(
        self,
        staging_path,
        gpx_file,
        source_layer,
        destination_layer,
        layer_already_created,
    ):
        """
        Build a direct GPX-to-GeoPackage append command.

        No SQL statement is constructed. Source provenance is added after
        the append through the GDAL/OGR Python API.
        """
        command = [
            self.ogr2ogr,
            "-f",
            "GPKG",
            "-skipfailures",
        ]

        if staging_path.exists():
            command.append("-update")

        if layer_already_created:
            command.extend(["-append", "-addfields"])

        command.extend(
            [
                str(staging_path),
                str(gpx_file),
                source_layer,
                "-nln",
                destination_layer,
            ]
        )

        return command

    @staticmethod
    def _ensure_text_field(layer, field_name):
        """Create a text field when it is not already present."""
        if layer.FindFieldIndex(field_name, True) >= 0:
            return

        field_definition = ogr.FieldDefn(field_name, ogr.OFTString)
        field_definition.SetWidth(254)

        result = layer.CreateField(field_definition)
        if result != ogr.OGRERR_NONE:
            raise RuntimeError(
                f"Could not create the provenance field: {field_name}"
            )

    def _set_unassigned_provenance(
        self,
        staging_path,
        layer_name,
        gpx_file,
        source_layer,
    ):
        """
        Set provenance fields on features added by the latest append.

        Features already processed have a non-empty source_file value and
        are left unchanged. This avoids dynamic SQL and preserves traceability.
        """
        dataset = ogr.Open(str(staging_path), update=1)
        if dataset is None:
            raise RuntimeError(
                f"Could not open the staging GeoPackage: {staging_path}"
            )

        try:
            layer = dataset.GetLayerByName(layer_name)
            if layer is None:
                raise RuntimeError(
                    f"Could not open the staging layer: {layer_name}"
                )

            provenance_values = {
                "source_file": gpx_file.name,
                "source_path": str(gpx_file),
                "source_layer": source_layer,
            }

            for field_name in provenance_values:
                self._ensure_text_field(layer, field_name)

            layer.ResetReading()
            for feature in layer:
                existing_source = feature.GetField("source_file")
                if existing_source not in (None, ""):
                    continue

                for field_name, value in provenance_values.items():
                    feature.SetField(field_name, value)

                result = layer.SetFeature(feature)
                if result != ogr.OGRERR_NONE:
                    raise RuntimeError(
                        "Could not update provenance fields for a "
                        f"feature in {layer_name}."
                    )

            layer.SyncToDisk()
            dataset.FlushCache()
        finally:
            dataset = None

    def _run_individual(self):
        total_steps = len(self.gpx_files) * (
            len(self.selected_layers) + 1
        )
        completed_steps = 0

        for file_index, gpx_file in enumerate(
            self.gpx_files,
            start=1,
        ):
            if self.isCanceled() or self.cancelled:
                self.summary["cancelled"] = True
                return False

            self.messageEmitted.emit(
                f"[{file_index}/{len(self.gpx_files)}] "
                f"Inspecting {gpx_file.name}"
            )

            counts, inspection_error = self._inspect_gpx(gpx_file)
            completed_steps += 1
            self._advance_progress(completed_steps, total_steps)

            if counts is None:
                if inspection_error == "Cancelled":
                    self.summary["cancelled"] = True
                    return False

                for layer_name in self.selected_layers:
                    self._record(
                        gpx_file.name,
                        layer_name,
                        "Failed",
                        message=inspection_error,
                    )
                    self.summary["failed"] += 1
                    completed_steps += 1
                    self._advance_progress(
                        completed_steps,
                        total_steps,
                    )
                continue

            for layer_name in self.selected_layers:
                if self.isCanceled() or self.cancelled:
                    self.summary["cancelled"] = True
                    return False

                feature_count = counts.get(layer_name, 0)
                output_path = self._individual_output_path(
                    gpx_file,
                    layer_name,
                )

                if feature_count <= 0:
                    self._record(
                        gpx_file.name,
                        layer_name,
                        "Missing/Empty",
                        feature_count=0,
                        message=(
                            "The GPX layer is missing or contains no features."
                        ),
                    )
                    self.summary["missing_empty"] += 1

                elif output_path.exists() and not self.overwrite:
                    self._record(
                        gpx_file.name,
                        layer_name,
                        "Skipped Existing",
                        feature_count=feature_count,
                        output=output_path,
                        message="The output already exists.",
                    )
                    self.summary["existing_skipped"] += 1

                else:
                    if output_path.exists():
                        self._remove_output(output_path)

                    output_layer = self.clean_filename(
                        f"{gpx_file.stem}_{layer_name}",
                        fallback=layer_name,
                    )

                    command = self._translate_command(
                        gpx_file,
                        layer_name,
                        output_path,
                        output_layer,
                    )

                    return_code, stdout, stderr, was_cancelled = (
                        self._run_process(command)
                    )

                    if was_cancelled:
                        self.summary["cancelled"] = True
                        return False

                    if return_code == 0 and output_path.exists():
                        self._record(
                            gpx_file.name,
                            layer_name,
                            "Converted",
                            feature_count=feature_count,
                            output=output_path,
                        )
                        self.summary["converted"] += 1
                        self._add_output_descriptor(
                            output_path,
                            output_layer
                            if self.output_format == "GeoPackage"
                            else layer_name,
                            output_path.stem,
                        )
                        self.messageEmitted.emit(
                            f"OK: {output_path.name}"
                        )
                    else:
                        message = (
                            stderr.strip()
                            or stdout.strip()
                            or "GDAL did not create the output."
                        )
                        self._record(
                            gpx_file.name,
                            layer_name,
                            "Failed",
                            feature_count=feature_count,
                            output=output_path,
                            message=message,
                        )
                        self.summary["failed"] += 1
                        self.messageEmitted.emit(
                            f"FAILED: {gpx_file.name} / "
                            f"{layer_name}: {message}"
                        )

                completed_steps += 1
                self._advance_progress(completed_steps, total_steps)

        self.setProgress(100)
        return True

    def _run_merged(self):
        total_steps = (
            len(self.gpx_files)
            + len(self.gpx_files) * len(self.selected_layers)
            + len(self.selected_layers)
        )
        completed_steps = 0
        inspections = {}

        # If a single merged GeoPackage already exists and overwrite is
        # disabled, skip it before doing expensive work.
        if self.output_format == "GeoPackage":
            package_path = self._merged_output_path(
                self.selected_layers[0]
            )

            if package_path.exists() and not self.overwrite:
                for layer_name in self.selected_layers:
                    self._record(
                        "ALL FILES",
                        layer_name,
                        "Skipped Existing",
                        output=package_path,
                        message=(
                            "The merged GeoPackage already exists."
                        ),
                    )
                    self.summary["existing_skipped"] += 1
                self.setProgress(100)
                return True

        # Inspect each source file once.
        for file_index, gpx_file in enumerate(
            self.gpx_files,
            start=1,
        ):
            if self.isCanceled() or self.cancelled:
                self.summary["cancelled"] = True
                return False

            self.messageEmitted.emit(
                f"[{file_index}/{len(self.gpx_files)}] "
                f"Inspecting {gpx_file.name}"
            )
            inspections[gpx_file] = self._inspect_gpx(gpx_file)

            completed_steps += 1
            self._advance_progress(completed_steps, total_steps)

        with tempfile.TemporaryDirectory(
            prefix="gpx_batch_converter_"
        ) as temporary_folder:
            staging_path = (
                Path(temporary_folder) / "merged_staging.gpkg"
            )
            built_layers = {}

            for layer_index, layer_name in enumerate(
                self.selected_layers,
                start=1,
            ):
                layer_created = False
                total_features = 0
                included_sources = 0

                self.messageEmitted.emit(
                    f"[{layer_index}/{len(self.selected_layers)}] "
                    f"Building merged {layer_name}"
                )

                for gpx_file in self.gpx_files:
                    if self.isCanceled() or self.cancelled:
                        self.summary["cancelled"] = True
                        return False

                    counts, inspection_error = inspections[gpx_file]

                    if counts is None:
                        self._record(
                            gpx_file.name,
                            layer_name,
                            "Failed",
                            message=inspection_error,
                        )
                        self.summary["failed"] += 1

                    else:
                        feature_count = counts.get(layer_name, 0)

                        if feature_count <= 0:
                            self._record(
                                gpx_file.name,
                                layer_name,
                                "Missing/Empty",
                                feature_count=0,
                                message=(
                                    "The GPX layer is missing or empty."
                                ),
                            )
                            self.summary["missing_empty"] += 1
                        else:
                            command = self._stage_append_command(
                                staging_path,
                                gpx_file,
                                layer_name,
                                layer_name,
                                layer_created,
                            )

                            (
                                return_code,
                                stdout,
                                stderr,
                                was_cancelled,
                            ) = self._run_process(command)

                            if was_cancelled:
                                self.summary["cancelled"] = True
                                return False

                            if return_code == 0:
                                try:
                                    self._set_unassigned_provenance(
                                        staging_path,
                                        layer_name,
                                        gpx_file,
                                        layer_name,
                                    )
                                except RuntimeError as provenance_error:
                                    self._record(
                                        gpx_file.name,
                                        layer_name,
                                        "Failed",
                                        feature_count=feature_count,
                                        message=str(provenance_error),
                                    )
                                    self.summary["failed"] += 1
                                    completed_steps += 1
                                    self._advance_progress(
                                        completed_steps,
                                        total_steps,
                                    )
                                    continue

                                layer_created = True
                                total_features += feature_count
                                included_sources += 1
                                self.summary["included"] += 1
                                self._record(
                                    gpx_file.name,
                                    layer_name,
                                    "Included",
                                    feature_count=feature_count,
                                    output=(
                                        self._merged_output_path(
                                            layer_name
                                        )
                                    ),
                                )
                            else:
                                message = (
                                    stderr.strip()
                                    or stdout.strip()
                                    or "GDAL could not append the layer."
                                )
                                self._record(
                                    gpx_file.name,
                                    layer_name,
                                    "Failed",
                                    feature_count=feature_count,
                                    message=message,
                                )
                                self.summary["failed"] += 1

                    completed_steps += 1
                    self._advance_progress(
                        completed_steps,
                        total_steps,
                    )

                if layer_created:
                    built_layers[layer_name] = {
                        "features": total_features,
                        "sources": included_sources,
                    }
                else:
                    self._record(
                        "ALL FILES",
                        layer_name,
                        "Missing/Empty",
                        feature_count=0,
                        message=(
                            "No non-empty source layer was available "
                            "for the merged output."
                        ),
                    )

                completed_steps += 1
                self._advance_progress(completed_steps, total_steps)

            if self.isCanceled() or self.cancelled:
                self.summary["cancelled"] = True
                return False

            if not built_layers:
                self.setProgress(100)
                return True

            # A merged GeoPackage stores every selected layer in one file.
            if self.output_format == "GeoPackage":
                final_package = self._merged_output_path(
                    next(iter(built_layers))
                )

                if final_package.exists():
                    self._remove_output(final_package)

                try:
                    shutil.copy2(staging_path, final_package)
                except Exception as error:
                    for layer_name, details in built_layers.items():
                        self._record(
                            "ALL FILES",
                            layer_name,
                            "Failed",
                            feature_count=details["features"],
                            output=final_package,
                            message=str(error),
                        )
                        self.summary["failed"] += 1
                    return False

                for layer_name, details in built_layers.items():
                    self._record(
                        "ALL FILES",
                        layer_name,
                        "Merged",
                        feature_count=details["features"],
                        output=final_package,
                        message=(
                            f"{details['sources']} source layers included."
                        ),
                    )
                    self.summary["merged_outputs"] += 1
                    self._add_output_descriptor(
                        final_package,
                        layer_name,
                        f"{self.merge_prefix}_{layer_name}",
                    )

                self.setProgress(100)
                return True

            # Other formats use one merged output file per layer type.
            for layer_name, details in built_layers.items():
                if self.isCanceled() or self.cancelled:
                    self.summary["cancelled"] = True
                    return False

                output_path = self._merged_output_path(layer_name)

                if output_path.exists() and not self.overwrite:
                    self._record(
                        "ALL FILES",
                        layer_name,
                        "Skipped Existing",
                        feature_count=details["features"],
                        output=output_path,
                        message="The output already exists.",
                    )
                    self.summary["existing_skipped"] += 1
                    continue

                if output_path.exists():
                    self._remove_output(output_path)

                output_layer = self.clean_filename(
                    f"{self.merge_prefix}_{layer_name}",
                    fallback=layer_name,
                )

                command = self._translate_command(
                    staging_path,
                    layer_name,
                    output_path,
                    output_layer,
                )

                return_code, stdout, stderr, was_cancelled = (
                    self._run_process(command)
                )

                if was_cancelled:
                    self.summary["cancelled"] = True
                    return False

                if return_code == 0 and output_path.exists():
                    self._record(
                        "ALL FILES",
                        layer_name,
                        "Merged",
                        feature_count=details["features"],
                        output=output_path,
                        message=(
                            f"{details['sources']} source layers included."
                        ),
                    )
                    self.summary["merged_outputs"] += 1
                    self._add_output_descriptor(
                        output_path,
                        layer_name,
                        output_path.stem,
                    )
                    self.messageEmitted.emit(
                        f"OK: {output_path.name}"
                    )
                else:
                    message = (
                        stderr.strip()
                        or stdout.strip()
                        or "GDAL did not create the merged output."
                    )
                    self._record(
                        "ALL FILES",
                        layer_name,
                        "Failed",
                        feature_count=details["features"],
                        output=output_path,
                        message=message,
                    )
                    self.summary["failed"] += 1

        self.setProgress(100)
        return True
