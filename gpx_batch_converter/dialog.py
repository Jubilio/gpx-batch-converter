from pathlib import Path
import csv
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsProject,
    QgsVectorLayer,
)

from .conversion_task import (
    GpxConversionTask,
    OUTPUT_FORMATS,
    find_gdal_executables,
)


def qgis_message_level(name):
    """Return a QGIS message level in old or scoped enum form."""
    scoped_enum = getattr(Qgis, "MessageLevel", None)
    if scoped_enum is not None:
        return getattr(scoped_enum, name)
    return getattr(Qgis, name)


def header_resize_mode(name):
    """Return a QHeaderView resize mode in Qt 5 or Qt 6."""
    scoped_enum = getattr(QHeaderView, "ResizeMode", None)
    if scoped_enum is not None:
        return getattr(scoped_enum, name)
    return getattr(QHeaderView, name)


def table_selection_behavior(name):
    """Return a table selection behavior in Qt 5 or Qt 6."""
    scoped_enum = getattr(
        QAbstractItemView,
        "SelectionBehavior",
        None,
    )
    if scoped_enum is not None:
        return getattr(scoped_enum, name)
    return getattr(QAbstractItemView, name)


def table_edit_trigger(name):
    """Return a table edit trigger in Qt 5 or Qt 6."""
    scoped_enum = getattr(
        QAbstractItemView,
        "EditTrigger",
        None,
    )
    if scoped_enum is not None:
        return getattr(scoped_enum, name)
    return getattr(QAbstractItemView, name)


class FolderSelector(QWidget):
    """Line edit and Browse button for selecting a folder."""

    def __init__(self, dialog_title, parent=None):
        super().__init__(parent)
        self.dialog_title = dialog_title

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(
            "Select or paste a folder path"
        )

        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.path_edit, 1)
        layout.addWidget(self.browse_button)

    def browse(self):
        current_path = self.path_edit.text().strip()
        start_folder = (
            current_path
            if current_path and Path(current_path).is_dir()
            else str(Path.home())
        )

        selected_folder = QFileDialog.getExistingDirectory(
            self,
            self.dialog_title,
            start_folder,
        )

        if selected_folder:
            self.path_edit.setText(selected_folder)

    def path(self):
        return Path(
            self.path_edit.text().strip().strip('"').strip("'")
        )


class GpxBatchConverterDialog(QDialog):
    """Graphical interface for batch GPX conversion."""

    LAYER_OPTIONS = (
        ("waypoints", "Waypoints"),
        ("routes", "Routes"),
        ("route_points", "Route points"),
        ("tracks", "Tracks"),
        ("track_points", "Track points"),
    )

    RESULT_COLUMNS = (
        "Source GPX",
        "GPX layer",
        "Status",
        "Features",
        "Output",
        "Message",
    )

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.current_task = None
        self.task_running = False
        self.last_results = []

        self.setWindowTitle("GPX Batch Converter")
        self.setWindowIcon(
            QIcon(str(Path(__file__).resolve().parent / "icon.png"))
        )
        self.setMinimumWidth(840)
        self.resize(980, 760)

        self.input_selector = FolderSelector(
            "Select the folder containing GPX files"
        )
        self.output_selector = FolderSelector(
            "Select the output folder"
        )

        self.format_combo = QComboBox()
        self.format_combo.addItems(list(OUTPUT_FORMATS.keys()))
        self.format_combo.setCurrentText("ESRI Shapefile")
        self.format_combo.currentTextChanged.connect(
            self.update_format_note
        )

        self.format_note = QLabel()
        self.format_note.setWordWrap(True)

        self.layer_checkboxes = {}
        for layer_name, label in self.LAYER_OPTIONS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(
                layer_name in {"tracks", "track_points"}
            )
            self.layer_checkboxes[layer_name] = checkbox

        self.merge_checkbox = QCheckBox(
            "Merge all GPX files into one output per layer type"
        )
        self.merge_checkbox.setChecked(False)
        self.merge_checkbox.toggled.connect(
            self.update_merge_controls
        )

        self.merge_prefix_edit = QLineEdit("merged")
        self.merge_prefix_edit.setPlaceholderText(
            "Prefix for merged outputs"
        )
        self.merge_prefix_edit.setEnabled(False)

        self.add_to_project_checkbox = QCheckBox(
            "Add completed outputs to the current QGIS project"
        )
        self.add_to_project_checkbox.setChecked(True)

        self.overwrite_checkbox = QCheckBox(
            "Overwrite existing outputs"
        )
        self.overwrite_checkbox.setChecked(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setAcceptRichText(False)
        self.log_output.setPlaceholderText(
            "Background conversion messages will appear here."
        )

        self.results_summary_label = QLabel(
            "No conversion results are available."
        )
        self.results_summary_label.setWordWrap(True)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(
            len(self.RESULT_COLUMNS)
        )
        self.results_table.setHorizontalHeaderLabels(
            self.RESULT_COLUMNS
        )
        self.results_table.setSelectionBehavior(
            table_selection_behavior("SelectRows")
        )
        self.results_table.setEditTriggers(
            table_edit_trigger("NoEditTriggers")
        )
        self.results_table.setAlternatingRowColors(True)

        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            header_resize_mode("ResizeToContents"),
        )
        header.setSectionResizeMode(
            1,
            header_resize_mode("ResizeToContents"),
        )
        header.setSectionResizeMode(
            2,
            header_resize_mode("ResizeToContents"),
        )
        header.setSectionResizeMode(
            3,
            header_resize_mode("ResizeToContents"),
        )
        header.setSectionResizeMode(
            4,
            header_resize_mode("Stretch"),
        )
        header.setSectionResizeMode(
            5,
            header_resize_mode("Stretch"),
        )

        self.export_results_button = QPushButton(
            "Export results to CSV"
        )
        self.export_results_button.setEnabled(False)
        self.export_results_button.clicked.connect(
            self.export_results
        )

        self.clear_results_button = QPushButton("Clear results")
        self.clear_results_button.setEnabled(False)
        self.clear_results_button.clicked.connect(
            self.clear_results
        )

        self.tabs = QTabWidget()
        self.tabs.addTab(
            self._create_progress_tab(),
            "Progress",
        )
        self.tabs.addTab(
            self._create_results_tab(),
            "Results",
        )

        self.convert_button = QPushButton("Convert")
        self.convert_button.setDefault(True)
        self.convert_button.clicked.connect(
            self.start_conversion
        )

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(
            self.cancel_conversion
        )

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        self._build_layout()
        self.update_format_note()

    def _create_progress_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self.log_output)
        return tab

    def _create_results_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self.results_summary_label)
        layout.addWidget(self.results_table, 1)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.export_results_button)
        button_layout.addWidget(self.clear_results_button)
        layout.addLayout(button_layout)

        return tab

    def _build_layout(self):
        main_layout = QVBoxLayout(self)

        intro = QLabel(
            "Batch-convert GPX sublayers in the background. "
            "Choose the output format, monitor progress, cancel safely, "
            "and review every processed file in the Results panel."
        )
        intro.setWordWrap(True)
        main_layout.addWidget(intro)

        folder_group = QGroupBox("Folders and output")
        folder_layout = QFormLayout(folder_group)
        folder_layout.addRow(
            "Input folder:",
            self.input_selector,
        )
        folder_layout.addRow(
            "Output folder:",
            self.output_selector,
        )
        folder_layout.addRow(
            "Output format:",
            self.format_combo,
        )
        folder_layout.addRow("", self.format_note)
        main_layout.addWidget(folder_group)

        layer_group = QGroupBox("GPX layers to convert")
        layer_layout = QVBoxLayout(layer_group)
        for layer_name, _ in self.LAYER_OPTIONS:
            layer_layout.addWidget(
                self.layer_checkboxes[layer_name]
            )
        main_layout.addWidget(layer_group)

        options_group = QGroupBox("Options")
        options_layout = QFormLayout(options_group)
        options_layout.addRow(self.overwrite_checkbox)
        options_layout.addRow(self.add_to_project_checkbox)
        options_layout.addRow(self.merge_checkbox)
        options_layout.addRow(
            "Merged output prefix:",
            self.merge_prefix_edit,
        )
        main_layout.addWidget(options_group)

        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.tabs, 1)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.convert_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.close_button)
        main_layout.addLayout(button_layout)

    def update_format_note(self):
        output_format = self.format_combo.currentText()

        notes = {
            "ESRI Shapefile": (
                "Creates one Shapefile dataset per output layer."
            ),
            "GeoPackage": (
                "In merge mode, all merged layer types are stored in "
                "one GeoPackage. In individual mode, each output layer "
                "uses its own GeoPackage file."
            ),
            "GeoJSON": (
                "Creates one GeoJSON file per output layer."
            ),
            "KML": (
                "Creates one KML file per output layer. Some field types "
                "may be simplified by the KML driver."
            ),
            "CSV (geometry as WKT)": (
                "Creates a CSV file with geometry stored in a WKT column."
            ),
        }

        self.format_note.setText(notes.get(output_format, ""))

    def update_merge_controls(self):
        self.merge_prefix_edit.setEnabled(
            self.merge_checkbox.isChecked()
            and not self.task_running
        )

    def selected_layers(self):
        return [
            layer_name
            for layer_name, checkbox
            in self.layer_checkboxes.items()
            if checkbox.isChecked()
        ]

    @staticmethod
    def clean_filename(name, fallback="merged"):
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

    def validate_inputs(self):
        input_text = self.input_selector.path_edit.text().strip()
        output_text = self.output_selector.path_edit.text().strip()

        if not input_text:
            QMessageBox.warning(
                self,
                "Invalid input folder",
                "Select the folder containing the GPX files.",
            )
            return None

        if not output_text:
            QMessageBox.warning(
                self,
                "Invalid output folder",
                "Select a folder for the converted outputs.",
            )
            return None

        input_folder = self.input_selector.path()
        output_folder = self.output_selector.path()
        selected_layers = self.selected_layers()
        merge_mode = self.merge_checkbox.isChecked()

        if not input_folder.exists() or not input_folder.is_dir():
            QMessageBox.warning(
                self,
                "Invalid input folder",
                "Select an existing folder containing GPX files.",
            )
            return None

        if not selected_layers:
            QMessageBox.warning(
                self,
                "No GPX layer selected",
                "Select at least one GPX layer to convert.",
            )
            return None

        merge_prefix = ""
        if merge_mode:
            prefix_text = self.merge_prefix_edit.text().strip()
            if not prefix_text:
                QMessageBox.warning(
                    self,
                    "Missing output prefix",
                    "Enter a prefix for the merged output files.",
                )
                return None

            merge_prefix = self.clean_filename(prefix_text)

        try:
            output_folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.critical(
                self,
                "Output folder error",
                f"The output folder could not be created:\n{error}",
            )
            return None

        gpx_files = sorted(
            file
            for file in input_folder.iterdir()
            if file.is_file() and file.suffix.lower() == ".gpx"
        )

        if not gpx_files:
            QMessageBox.information(
                self,
                "No GPX files",
                "No GPX files were found in the selected input folder.",
            )
            return None

        executables = find_gdal_executables()
        missing_executables = [
            name
            for name in ("ogr2ogr", "ogrinfo")
            if name not in executables
        ]

        if missing_executables:
            QMessageBox.critical(
                self,
                "GDAL tools not found",
                (
                    "The following GDAL tools could not be found in the "
                    "active QGIS environment:\n\n"
                    + "\n".join(missing_executables)
                    + "\n\nRepair or reinstall the QGIS/GDAL installation."
                ),
            )
            return None

        return {
            "input_folder": input_folder,
            "output_folder": output_folder,
            "selected_layers": selected_layers,
            "merge_mode": merge_mode,
            "merge_prefix": merge_prefix,
            "gpx_files": gpx_files,
            "executables": executables,
        }

    def set_busy(self, busy):
        self.task_running = busy

        self.convert_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.close_button.setEnabled(not busy)

        self.input_selector.setEnabled(not busy)
        self.output_selector.setEnabled(not busy)
        self.format_combo.setEnabled(not busy)

        for checkbox in self.layer_checkboxes.values():
            checkbox.setEnabled(not busy)

        self.overwrite_checkbox.setEnabled(not busy)
        self.add_to_project_checkbox.setEnabled(not busy)
        self.merge_checkbox.setEnabled(not busy)
        self.merge_prefix_edit.setEnabled(
            not busy and self.merge_checkbox.isChecked()
        )

    def log(self, message):
        self.log_output.append(str(message))
        self.log_output.ensureCursorVisible()

    def start_conversion(self):
        validated = self.validate_inputs()
        if validated is None:
            return

        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText(
            "Conversion task submitted to the QGIS Task Manager."
        )
        self.tabs.setCurrentIndex(0)
        self.set_busy(True)

        self.current_task = GpxConversionTask(
            gpx_files=validated["gpx_files"],
            output_folder=validated["output_folder"],
            selected_layers=validated["selected_layers"],
            output_format=self.format_combo.currentText(),
            overwrite=self.overwrite_checkbox.isChecked(),
            merge_mode=validated["merge_mode"],
            merge_prefix=validated["merge_prefix"],
            executables=validated["executables"],
            finished_callback=self.task_finished,
        )

        self.current_task.messageEmitted.connect(self.log)
        self.current_task.progressChanged.connect(
            self.progress_changed
        )

        added = QgsApplication.taskManager().addTask(
            self.current_task
        )

        if not added:
            self.set_busy(False)
            self.current_task = None
            QMessageBox.critical(
                self,
                "Task error",
                "QGIS could not start the background conversion task.",
            )

    def progress_changed(self, progress):
        self.progress_bar.setValue(int(progress))
        self.status_label.setText(
            f"Background conversion: {int(progress)}%"
        )

    def cancel_conversion(self):
        if self.current_task is None:
            return

        self.cancel_button.setEnabled(False)
        self.status_label.setText(
            "Cancelling the active GDAL operation..."
        )
        self.log("Cancellation requested.")
        self.current_task.cancel()

    def task_finished(self, task, successful):
        self.current_task = None
        self.set_busy(False)

        self.last_results = list(task.results)
        self.populate_results(task.results)
        self.update_results_summary(task.summary)
        self.tabs.setCurrentIndex(1)

        if task.summary.get("cancelled") or task.cancelled:
            self.progress_bar.setValue(int(task.progress()))
            self.status_label.setText("Conversion cancelled.")
            notification_level = qgis_message_level("Warning")
            title = "Conversion cancelled"
            message = (
                "The task was cancelled. Outputs completed before "
                "cancellation were preserved."
            )

        elif task.exception is not None:
            self.status_label.setText("Conversion failed.")
            notification_level = qgis_message_level("Critical")
            title = "Conversion failed"
            message = str(task.exception)

        elif task.summary.get("failed", 0):
            self.progress_bar.setValue(100)
            self.status_label.setText(
                "Conversion completed with errors."
            )
            notification_level = qgis_message_level("Warning")
            title = "Conversion completed with errors"
            message = (
                f"{task.summary['failed']} operation(s) failed. "
                "Review the Results panel."
            )

        else:
            self.progress_bar.setValue(100)
            self.status_label.setText("Conversion completed.")
            notification_level = qgis_message_level("Success")
            title = "Conversion completed"
            message = "Review the Results panel for details."

        if (
            self.add_to_project_checkbox.isChecked()
            and task.output_layers
        ):
            self.add_outputs_to_project(task.output_layers)

        self.iface.messageBar().pushMessage(
            title,
            message,
            level=notification_level,
            duration=10,
        )

    def populate_results(self, results):
        self.results_table.setRowCount(0)

        for result in results:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)

            values = (
                result.get("source_file", ""),
                result.get("layer", ""),
                result.get("status", ""),
                result.get("features", ""),
                result.get("output", ""),
                result.get("message", ""),
            )

            for column, value in enumerate(values):
                self.results_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(str(value)),
                )

        has_results = bool(results)
        self.export_results_button.setEnabled(has_results)
        self.clear_results_button.setEnabled(has_results)

    def update_results_summary(self, summary):
        if self.merge_checkbox.isChecked():
            text = (
                f"Merged outputs: {summary.get('merged_outputs', 0)} | "
                f"Source layers included: {summary.get('included', 0)} | "
                f"Missing/empty: {summary.get('missing_empty', 0)} | "
                f"Existing skipped: "
                f"{summary.get('existing_skipped', 0)} | "
                f"Failed: {summary.get('failed', 0)}"
            )
        else:
            text = (
                f"Converted: {summary.get('converted', 0)} | "
                f"Missing/empty: {summary.get('missing_empty', 0)} | "
                f"Existing skipped: "
                f"{summary.get('existing_skipped', 0)} | "
                f"Failed: {summary.get('failed', 0)}"
            )

        if summary.get("cancelled"):
            text += " | Status: Cancelled"

        self.results_summary_label.setText(text)

    def add_outputs_to_project(self, output_layers):
        added = 0

        for output in output_layers:
            layer = QgsVectorLayer(
                output["uri"],
                output["name"],
                "ogr",
            )

            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                added += 1
            else:
                self.log(
                    "Could not add output to project: "
                    f"{output['uri']}"
                )

        if added:
            self.log(
                f"Added {added} output layer(s) to the QGIS project."
            )

    def export_results(self):
        if not self.last_results:
            return

        default_path = str(
            Path.home() / "gpx_conversion_results.csv"
        )

        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export conversion results",
            default_path,
            "CSV files (*.csv)",
        )

        if not selected_path:
            return

        output_path = Path(selected_path)
        if output_path.suffix.lower() != ".csv":
            output_path = output_path.with_suffix(".csv")

        fieldnames = [
            "source_file",
            "layer",
            "status",
            "features",
            "output",
            "message",
        ]

        try:
            with output_path.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as csv_file:
                writer = csv.DictWriter(
                    csv_file,
                    fieldnames=fieldnames,
                )
                writer.writeheader()
                writer.writerows(self.last_results)

            self.iface.messageBar().pushMessage(
                "Results exported",
                str(output_path),
                level=qgis_message_level("Success"),
                duration=8,
            )
        except OSError as error:
            QMessageBox.critical(
                self,
                "Export error",
                str(error),
            )

    def clear_results(self):
        self.last_results = []
        self.results_table.setRowCount(0)
        self.results_summary_label.setText(
            "No conversion results are available."
        )
        self.export_results_button.setEnabled(False)
        self.clear_results_button.setEnabled(False)

    def closeEvent(self, event):
        if self.task_running:
            QMessageBox.information(
                self,
                "Conversion running",
                (
                    "Cancel the active conversion before closing "
                    "the plugin window."
                ),
            )
            event.ignore()
            return

        event.accept()
