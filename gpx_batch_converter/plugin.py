from pathlib import Path
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from .dialog import GpxBatchConverterDialog


class GpxBatchConverterPlugin:
    """Main QGIS plugin class."""

    MENU_NAME = "&GPX Batch Converter"

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.icon_path = Path(__file__).resolve().parent / "icon.png"

    def initGui(self):
        self.action = QAction(
            QIcon(str(self.icon_path)),
            "GPX Batch Converter",
            self.iface.mainWindow()
        )
        self.action.setObjectName("gpxBatchConverterAction")
        self.action.setStatusTip(
            "Batch-convert GPX layers to ESRI Shapefiles"
        )
        self.action.triggered.connect(self.run)

        self.iface.addPluginToVectorMenu(
            self.MENU_NAME,
            self.action
        )
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginVectorMenu(
                self.MENU_NAME,
                self.action
            )
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

        if self.dialog is not None:
            if self.dialog.current_task is not None:
                self.dialog.current_task.cancel()
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def run(self):
        if self.dialog is None:
            self.dialog = GpxBatchConverterDialog(
                self.iface,
                self.iface.mainWindow()
            )

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
