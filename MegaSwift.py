"""
MegaSwift - Water Utility Civil Plan Takeoff Application
V1.2

DEPENDENCIES — install before running:
    pip install PyQt6 PyMuPDF ollama

What those packages are:
  PyQt6      — A professional-grade desktop GUI framework for Python, built on top
                of the Qt toolkit. Used by companies like Autodesk and VLC. Gives us
                windows, buttons, toolbars, scroll areas, and drawing capabilities.
  PyMuPDF    — A fast Python library for reading and rendering PDF files. It converts
                PDF pages into images we can display and interact with.
  ollama     — Python client for Ollama, the local LLM runner. Powers the chat panel.
                Requires Ollama to be installed and running (https://ollama.com).
"""

import sys
import json
import os
import math
import re

# Optional — app works without it, but the Chat panel requires it
try:
    import ollama as _ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# Tell Qt where to find its platform plugins (fixes "cocoa not found" on macOS with Anaconda)
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(os.path.dirname(__import__("PyQt6").__file__), "Qt6", "plugins", "platforms")
)

import fitz  # PyMuPDF
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QGraphicsView, QGraphicsScene,
    QGraphicsObject, QGraphicsEllipseItem,
    QToolBar, QPushButton, QLabel, QFileDialog, QInputDialog,
    QMessageBox, QStatusBar, QStackedWidget, QTabWidget
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QThread, QObject, pyqtSlot
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QColor, QAction, QKeySequence, QFont, QBrush
)


# ---------------------------------------------------------------------------
# Endpoint Handle
# ---------------------------------------------------------------------------

class EndpointHandle(QGraphicsEllipseItem):
    """
    A small draggable circle at each end of a measurement line.
    When dragged, it notifies its parent MeasurementItem so the line
    and label can update in real time.
    """
    RADIUS = 11  # scene units — visible at full-page zoom, comfortably clickable when zoomed in

    def __init__(self, endpoint_index: int, measurement, scene_x: float, scene_y: float):
        r = self.RADIUS
        super().__init__(-r, -r, r * 2, r * 2)
        self._index = endpoint_index
        self._measurement = measurement

        self.setPos(scene_x, scene_y)
        self.setFlags(
            QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setZValue(3)  # draw above line and label

        pen = QPen(QColor("#ffffff"), 1.5)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(180, 180, 180, 190)))

    def itemChange(self, change, value):
        # ItemPositionHasChanged fires after every move; value = new pos in parent coords.
        # Since handles have no parent item, parent coords == scene coords.
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionHasChanged:
            self._measurement.endpoint_moved(self._index, value)
        return super().itemChange(change, value)


# ---------------------------------------------------------------------------
# Measurement Item
# ---------------------------------------------------------------------------

class MeasurementItem(QGraphicsObject):
    """
    A persistent line annotation drawn on a PDF page.
    Draws itself (line + distance label) via custom paint().
    Emits recalculation_needed when either endpoint handle is dragged,
    so the viewer can update the scale or recompute the dimension distance.

    Two endpoint handles are created alongside this item and stored in
    self.handles — the viewer is responsible for adding them to the scene.
    """

    COLOR_SCALE = QColor("#ff8800")       # orange  — scale reference line
    COLOR_DIMENSION = QColor("#ff3232")   # red     — dimension lines
    COLOR_SELECTED = QColor("#00ccff")    # cyan    — selection highlight

    recalculation_needed = pyqtSignal(object)  # emits self when a handle is dragged

    def __init__(self, p1: QPointF, p2: QPointF, label: str,
                 color: QColor, mtype: str = "dimension", known_feet: float = None):
        super().__init__()
        self._p1 = QPointF(p1)
        self._p2 = QPointF(p2)
        self._label = label
        self._color = color
        self._mtype = mtype
        self._known_feet = known_feet   # only set for scale lines; used when recalculating

        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(1)

        self._font = QFont("Arial")
        self._font.setPixelSize(50)     # 50 scene units tall — clearly visible at page zoom
        self._font.setBold(True)

        # Create the two draggable handles (caller adds them to the scene)
        self.handles = [
            EndpointHandle(0, self, p1.x(), p1.y()),
            EndpointHandle(1, self, p2.x(), p2.y()),
        ]

    # ------------------------------------------------------------------
    # QGraphicsItem required overrides
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        x1, y1 = self._p1.x(), self._p1.y()
        x2, y2 = self._p2.x(), self._p2.y()
        pad = 150   # extra space for label above the line
        return QRectF(
            min(x1, x2) - pad, min(y1, y2) - pad,
            abs(x2 - x1) + pad * 2, abs(y2 - y1) + pad * 2
        ).normalized()

    def paint(self, painter: QPainter, option, widget=None):
        color = self.COLOR_SELECTED if self.isSelected() else self._color

        # --- Line ---
        pen = QPen(color, 2)
        pen.setCosmetic(True)   # stays 2px wide regardless of zoom
        painter.setPen(pen)
        painter.drawLine(self._p1, self._p2)

        # --- Label centered above the midpoint, offset perpendicular to the line ---
        painter.setFont(self._font)
        painter.setPen(QPen(color))

        mid_x = (self._p1.x() + self._p2.x()) / 2
        mid_y = (self._p1.y() + self._p2.y()) / 2
        dx = self._p2.x() - self._p1.x()
        dy = self._p2.y() - self._p1.y()
        length = math.hypot(dx, dy)

        if length > 0:
            nx, ny = -dy / length, dx / length
            if ny > 0:          # always offset toward the top of the screen
                nx, ny = -nx, -ny
        else:
            nx, ny = 0, -1

        offset = max(80, length * 0.05)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(self._label)
        th = fm.height()

        painter.drawText(
            QPointF(mid_x + nx * offset - tw / 2,
                    mid_y + ny * offset + th / 3),
            self._label
        )

    # ------------------------------------------------------------------
    # Handle movement callback
    # ------------------------------------------------------------------

    def endpoint_moved(self, index: int, new_pos: QPointF):
        """Called by an EndpointHandle when it is dragged."""
        self.prepareGeometryChange()
        if index == 0:
            self._p1 = QPointF(new_pos)
        else:
            self._p2 = QPointF(new_pos)
        self.update()
        self.recalculation_needed.emit(self)

    # ------------------------------------------------------------------
    # Label editing
    # ------------------------------------------------------------------

    def set_label(self, text: str):
        self._label = text
        self.update()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def label(self) -> str:     return self._label
    def p1(self) -> QPointF:    return QPointF(self._p1)
    def p2(self) -> QPointF:    return QPointF(self._p2)
    def mtype(self) -> str:     return self._mtype
    def known_feet(self):       return self._known_feet

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = {
            "type": self._mtype,
            "p1": [self._p1.x(), self._p1.y()],
            "p2": [self._p2.x(), self._p2.y()],
            "label": self._label,
            "color": self._color.name(),
        }
        if self._known_feet is not None:
            d["known_feet"] = self._known_feet
        return d

    @staticmethod
    def from_dict(d: dict) -> "MeasurementItem":
        p1 = QPointF(d["p1"][0], d["p1"][1])
        p2 = QPointF(d["p2"][0], d["p2"][1])
        color = QColor(d.get("color", "#ff3232"))
        return MeasurementItem(
            p1, p2, d["label"], color,
            d.get("type", "dimension"),
            d.get("known_feet")
        )


# ---------------------------------------------------------------------------
# Background Page Renderer
# ---------------------------------------------------------------------------

class PageRenderWorker(QObject):
    """
    Runs on a background QThread. Receives render requests and emits
    the finished pixmap back to the main thread — keeping the UI responsive.
    """
    page_ready = pyqtSignal(QPixmap, int)

    @pyqtSlot(str, int)
    def render(self, pdf_path: str, page_index: int):
        try:
            doc = fitz.open(pdf_path)
            page = doc[page_index]
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            img = QImage(
                pix.samples, pix.width, pix.height,
                pix.stride, QImage.Format.Format_RGB888
            )
            pixmap = QPixmap.fromImage(img)
            doc.close()
            self.page_ready.emit(pixmap, page_index)
        except Exception:
            self.page_ready.emit(QPixmap(), page_index)


# ---------------------------------------------------------------------------
# PDF Viewer
# ---------------------------------------------------------------------------

class PDFViewer(QGraphicsView):
    """
    The main PDF canvas.
    - Scroll-wheel zoom (anchored to cursor), click-drag pan
    - Scale tool: one scale line per page; endpoints are draggable
    - Dimension tool: draggable endpoint handles, live label update
    - Click to select a measurement, double-click to edit its label, Delete to remove
    """

    scale_set = pyqtSignal(float)   # feet per pixel — emitted on calibration or handle drag

    MODE_NORMAL = "normal"
    MODE_SCALE = "scale"
    MODE_DIMENSION = "dimension"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._scene = QGraphicsScene()
        self.setScene(self._scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setBackgroundBrush(QColor(60, 60, 60))

        self._mode = self.MODE_NORMAL
        self._click_points = []
        self._temp_line = None
        self._scale_known_distance = None
        self._feet_per_pixel = None
        self._base_scale = None

        self._measurements: list[MeasurementItem] = []
        self._scale_item: MeasurementItem | None = None  # only one scale line per page

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def set_mode(self, mode, known_distance=None):
        self._mode = mode
        self._click_points = []
        self._clear_temp_line()

        if mode == self.MODE_NORMAL:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)

        if mode == self.MODE_SCALE:
            self._scale_known_distance = known_distance

    # ------------------------------------------------------------------
    # Page loading
    # ------------------------------------------------------------------

    def load_page(self, pixmap: QPixmap):
        self._scene.clear()
        self._temp_line = None
        self._click_points = []
        self._measurements = []
        self._scale_item = None

        self._scene.addPixmap(pixmap)
        self.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._base_scale = self.transform().m11()

    # ------------------------------------------------------------------
    # Measurement persistence
    # ------------------------------------------------------------------

    def _add_measurement(self, item: MeasurementItem):
        """Add a MeasurementItem and its handles to the scene."""
        self._scene.addItem(item)
        for h in item.handles:
            self._scene.addItem(h)
        item.recalculation_needed.connect(self._on_recalculation_needed)
        self._measurements.append(item)

    def _remove_measurement(self, item: MeasurementItem):
        """Remove a MeasurementItem and its handles from the scene."""
        for h in item.handles:
            self._scene.removeItem(h)
        self._scene.removeItem(item)
        if item in self._measurements:
            self._measurements.remove(item)
        if item is self._scale_item:
            self._scale_item = None

    def load_measurements(self, data: list):
        for d in data:
            item = MeasurementItem.from_dict(d)
            self._add_measurement(item)
            if d.get("type") == "scale":
                self._scale_item = item

    def get_measurements(self) -> list:
        return [m.to_dict() for m in self._measurements]

    # ------------------------------------------------------------------
    # Recalculation when handles are dragged
    # ------------------------------------------------------------------

    def _on_recalculation_needed(self, item: MeasurementItem):
        p1, p2 = item.p1(), item.p2()
        pixel_dist = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
        if pixel_dist == 0:
            return

        if item.mtype() == "scale" and item.known_feet() is not None:
            self._feet_per_pixel = item.known_feet() / pixel_dist
            self.scale_set.emit(self._feet_per_pixel)

        elif item.mtype() == "dimension" and self._feet_per_pixel:
            new_dist = pixel_dist * self._feet_per_pixel
            item.set_label(f"{new_dist:.2f} ft")

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        zooming_in = event.angleDelta().y() > 0
        factor = 1.06 if zooming_in else 1 / 1.06

        if not zooming_in and self._base_scale is not None:
            current = self.transform().m11()
            min_scale = self._base_scale * 0.90
            if current * factor < min_scale:
                factor = min_scale / current

        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if self._mode in (self.MODE_SCALE, self.MODE_DIMENSION):
            if event.button() == Qt.MouseButton.LeftButton:
                self._click_points.append(self.mapToScene(event.pos()))
                if len(self._click_points) == 2:
                    self._finalize_measurement()
            return

        if self._mode == self.MODE_NORMAL and event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())

            # If clicking an endpoint handle, suspend pan so the handle can be dragged
            if isinstance(item, EndpointHandle):
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                super().mousePressEvent(event)
                return

            # If clicking a measurement line, select it
            if isinstance(item, MeasurementItem):
                self._scene.clearSelection()
                item.setSelected(True)
                return

            # Otherwise clear selection and allow normal pan
            self._scene.clearSelection()

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._mode == self.MODE_NORMAL:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._mode == self.MODE_NORMAL and event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, MeasurementItem):
                self._edit_measurement(item)
                return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        if self._mode in (self.MODE_SCALE, self.MODE_DIMENSION):
            if len(self._click_points) == 1:
                self._draw_temp_line(self._click_points[0], self.mapToScene(event.pos()))
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            to_remove = [i for i in self._scene.selectedItems() if isinstance(i, MeasurementItem)]
            for item in to_remove:
                self._remove_measurement(item)
            if to_remove:
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_temp_line(self, p1: QPointF, p2: QPointF):
        self._clear_temp_line()
        pen = QPen(QColor(255, 200, 0), 2)
        pen.setCosmetic(True)
        self._temp_line = self._scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), pen)

    def _clear_temp_line(self):
        if self._temp_line:
            self._scene.removeItem(self._temp_line)
            self._temp_line = None

    # ------------------------------------------------------------------
    # Measurement finalization
    # ------------------------------------------------------------------

    def _finalize_measurement(self):
        p1, p2 = self._click_points
        pixel_dist = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
        self._clear_temp_line()
        self._click_points = []

        if self._mode == self.MODE_SCALE:
            if pixel_dist > 0:
                self._feet_per_pixel = self._scale_known_distance / pixel_dist
                label = f"Scale: {self._scale_known_distance:.2f} ft"

                # Remove existing scale line — only one allowed per page
                if self._scale_item:
                    self._remove_measurement(self._scale_item)

                item = MeasurementItem(
                    p1, p2, label, MeasurementItem.COLOR_SCALE,
                    mtype="scale", known_feet=self._scale_known_distance
                )
                self._add_measurement(item)
                self._scale_item = item
                self.scale_set.emit(self._feet_per_pixel)
            self.set_mode(self.MODE_NORMAL)

        elif self._mode == self.MODE_DIMENSION:
            if self._feet_per_pixel and pixel_dist > 0:
                distance = pixel_dist * self._feet_per_pixel
                label = f"{distance:.2f} ft"
                item = MeasurementItem(
                    p1, p2, label, MeasurementItem.COLOR_DIMENSION, mtype="dimension"
                )
                self._add_measurement(item)
            else:
                QMessageBox.warning(self, "No Scale Set", "Please set the scale before measuring.")
            self.set_mode(self.MODE_NORMAL)

    # ------------------------------------------------------------------
    # Label editing
    # ------------------------------------------------------------------

    def _edit_measurement(self, item: MeasurementItem):
        new_label, ok = QInputDialog.getText(
            self, "Edit Measurement", "Edit label:", text=item.label()
        )
        if ok and new_label.strip():
            item.set_label(new_label.strip())

    # ------------------------------------------------------------------
    # Scale accessors
    # ------------------------------------------------------------------

    def get_scale(self):
        return self._feet_per_pixel

    def set_scale(self, feet_per_pixel):
        self._feet_per_pixel = feet_per_pixel


# ---------------------------------------------------------------------------
# Project Panel (left sidebar)
# ---------------------------------------------------------------------------

class ProjectPanel(QWidget):
    page_selected = pyqtSignal(int)
    page_rename_requested = pyqtSignal(int)

    TAKEOFF_CATEGORIES = [
        "DRAINAGE",
        "ROOF DRAIN",
        "SEWER",
        "FORCE MAIN",
        "WATER",
        "IRRIGATION",
        "FIRE",
        "ALTERNATIVE MATERIAL",
        "NOTES",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        layout.addWidget(self.tabs)

        # --- Pages tab ---
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Project")
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tabs.addTab(self.tree, "Pages")

        # --- Takeoff Summary tab ---
        self.takeoff_tree = QTreeWidget()
        self.takeoff_tree.setHeaderLabel("Takeoff Summary")
        self._build_takeoff_tree()
        self.tabs.addTab(self.takeoff_tree, "Takeoff Summary")

        self._project_item = None
        self._page_items = []

    def _build_takeoff_tree(self):
        for category in self.TAKEOFF_CATEGORIES:
            folder = QTreeWidgetItem([category])
            self.takeoff_tree.addTopLevelItem(folder)

    def load_project(self, project_name: str, pages: list):
        self.tree.clear()
        self._page_items = []

        self._project_item = QTreeWidgetItem([project_name])
        self.tree.addTopLevelItem(self._project_item)

        for i, page in enumerate(pages):
            item = QTreeWidgetItem([page.get("name", f"Page {i + 1}")])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            self._project_item.addChild(item)
            self._page_items.append(item)

        self._project_item.setExpanded(True)

    def _on_current_changed(self, current, _previous):
        if current is None:
            return
        index = current.data(0, Qt.ItemDataRole.UserRole)
        if index is not None:
            self.page_selected.emit(index)

    def _on_item_double_clicked(self, item, _column):
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is not None:
            self.page_rename_requested.emit(index)

    def update_page_name(self, index: int, name: str):
        if 0 <= index < len(self._page_items):
            self._page_items[index].setText(0, name)

    def select_page(self, index: int):
        if 0 <= index < len(self._page_items):
            self.tree.setCurrentItem(self._page_items[index])

    def page_count(self) -> int:
        return len(self._page_items)


# ---------------------------------------------------------------------------
# Welcome Screen
# ---------------------------------------------------------------------------

class WelcomeScreen(QWidget):
    open_pdf_requested = pyqtSignal()
    open_project_requested = pyqtSignal()
    pdf_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("background-color: #2b2b2b;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        title = QLabel("MegaSwift")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #ffffff; font-size: 28px; font-weight: bold;")

        subtitle = QLabel("Water Utility Plan Takeoff")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #aaaaaa; font-size: 14px;")

        self.drop_label = QLabel("Drop a PDF here  —  or use a button below")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet(
            "color: #888888; font-size: 12px; border: 2px dashed #555555;"
            "border-radius: 8px; padding: 30px 50px;"
        )

        new_btn = QPushButton("Open PDF  /  New Project")
        new_btn.setFixedWidth(240)
        new_btn.setFixedHeight(44)
        new_btn.setStyleSheet(
            "QPushButton { background-color: #0078d4; color: white; font-size: 14px;"
            "border-radius: 6px; } QPushButton:hover { background-color: #005fa3; }"
        )
        new_btn.clicked.connect(self.open_pdf_requested)

        open_btn = QPushButton("Open Existing Project  (.mswift)")
        open_btn.setFixedWidth(240)
        open_btn.setFixedHeight(36)
        open_btn.setStyleSheet(
            "QPushButton { background-color: #3c3c3c; color: #cccccc; font-size: 13px;"
            "border-radius: 6px; border: 1px solid #555; }"
            "QPushButton:hover { background-color: #4a4a4a; }"
        )
        open_btn.clicked.connect(self.open_project_requested)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(20)
        layout.addWidget(self.drop_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(10)
        layout.addWidget(new_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if any(u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
                event.acceptProposedAction()
                self.drop_label.setStyleSheet(
                    "color: #ffffff; font-size: 12px; border: 2px dashed #0078d4;"
                    "border-radius: 8px; padding: 30px 50px; background-color: #1a3a5c;"
                )

    def dragLeaveEvent(self, event):
        self.drop_label.setStyleSheet(
            "color: #888888; font-size: 12px; border: 2px dashed #555555;"
            "border-radius: 8px; padding: 30px 50px;"
        )

    def dropEvent(self, event):
        self.drop_label.setStyleSheet(
            "color: #888888; font-size: 12px; border: 2px dashed #555555;"
            "border-radius: 8px; padding: 30px 50px;"
        )
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".pdf"):
                self.pdf_dropped.emit(path)
                return


# ---------------------------------------------------------------------------
# Chat Panel (Ollama conversation sidebar)
# ---------------------------------------------------------------------------

class OllamaChatWorker(QObject):
    """
    Runs a streaming Ollama chat call on a background thread.
    Emits tokens as they arrive so the UI can display them live.
    """
    token_received = pyqtSignal(str)
    finished       = pyqtSignal()
    error          = pyqtSignal(str)

    def __init__(self, messages: list, model: str, host: str):
        super().__init__()
        self._messages = messages
        self._model    = model
        self._host     = host

    @pyqtSlot()
    def run(self):
        try:
            client = _ollama.Client(host=self._host)
            stream = client.chat(
                model=self._model,
                messages=self._messages,
                stream=True,
            )
            for chunk in stream:
                token = chunk["message"]["content"]
                if token:
                    self.token_received.emit(token)
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class ChatPanel(QWidget):
    """
    Collapsible right-side chat panel backed by a local Ollama model.
    Streams responses token-by-token. Model and host are configurable.
    """

    DEFAULT_MODEL = "llama3.2"
    DEFAULT_HOST  = "http://localhost:11434"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(420)

        self._history: list[dict] = []
        self._page_context = ""
        self._worker  = None
        self._thread  = None
        self._bot_buf = ""

        self.model = self.DEFAULT_MODEL
        self.host  = self.DEFAULT_HOST

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Ollama Chat")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(title)
        header.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(50)
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)
        root.addLayout(header)

        # Model label
        self._model_label = QLabel(f"Model: {self.model}")
        self._model_label.setStyleSheet("color:#888; font-size:10px;")
        root.addWidget(self._model_label)

        # Conversation display
        from PyQt6.QtWidgets import QTextEdit as _QTE
        self._display = _QTE()
        self._display.setReadOnly(True)
        self._display.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; font-size:12px; border:1px solid #444;"
        )
        root.addWidget(self._display, stretch=1)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(4)
        from PyQt6.QtWidgets import QTextEdit as _QTE2
        self._input = _QTE2()
        self._input.setFixedHeight(64)
        self._input.setPlaceholderText("Ask about this plan…")
        self._input.setStyleSheet("font-size:12px;")
        self._input.installEventFilter(self)
        input_row.addWidget(self._input)
        send_btn = QPushButton("Send")
        send_btn.setFixedWidth(52)
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)
        root.addLayout(input_row)

        hint = QLabel("Ctrl+Enter to send")
        hint.setStyleSheet("color:#666; font-size:10px;")
        root.addWidget(hint)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if (event.key() == Qt.Key.Key_Return and
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self._send()
                return True
        return super().eventFilter(obj, event)

    def set_page_context(self, context: str):
        self._page_context = context

    def set_model(self, model: str):
        self.model = model
        self._model_label.setText(f"Model: {model}")

    def set_host(self, host: str):
        self.host = host

    def _system_prompt(self) -> str:
        base = (
            "You are an expert civil engineering plan reviewer embedded inside MegaSwift, "
            "a water utility takeoff application. Answer questions concisely. "
            "Use plain text — no markdown headers or bullet symbols unless asked."
        )
        if self._page_context:
            base += f"\n\nCurrent page context: {self._page_context}"
        return base

    def _append(self, role: str, text: str):
        from PyQt6.QtGui import QTextCursor
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._display.setTextCursor(cursor)

        if role == "user":
            self._display.append(f"\n<b>You:</b> {text}")
        elif role == "assistant_start":
            self._display.append(f"\n<b>{self.model}:</b> ")
        elif role == "token":
            cursor = self._display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(text)
            self._display.setTextCursor(cursor)
        elif role == "error":
            self._display.append(f"\n<span style='color:#f88;'>Error: {text}</span>")

        self._display.ensureCursorVisible()

    def _send(self):
        if not OLLAMA_AVAILABLE:
            self._append("error", "ollama package not installed. Run: pip install ollama")
            return

        text = self._input.toPlainText().strip()
        if not text:
            return
        if self._thread and self._thread.isRunning():
            return

        self._input.clear()
        self._history.append({"role": "user", "content": text})
        self._append("user", text)
        self._append("assistant_start", "")
        self._bot_buf = ""

        messages = [{"role": "system", "content": self._system_prompt()}] + self._history

        self._worker = OllamaChatWorker(messages, self.model, self.host)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.token_received.connect(self._on_token)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    @pyqtSlot(str)
    def _on_token(self, token: str):
        self._bot_buf += token
        self._append("token", token)

    @pyqtSlot()
    def _on_finished(self):
        self._history.append({"role": "assistant", "content": self._bot_buf})
        self._thread.quit()
        self._thread.wait()

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        if "connection refused" in msg.lower() or "connect" in msg.lower():
            self._append("error", "Cannot reach Ollama. Is it running? Try: ollama serve")
        elif "model" in msg.lower() and "not found" in msg.lower():
            self._append("error", f"Model '{self.model}' not found. Run: ollama pull {self.model}")
        else:
            self._append("error", msg)
        self._thread.quit()
        self._thread.wait()

    def _clear(self):
        self._history.clear()
        self._display.clear()


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    _render_requested = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MegaSwift - Plan Takeoff")
        self.setMinimumSize(1200, 800)

        self._project = None
        self._pdf_doc = None
        self._current_page = 0
        self._project_path = None
        self._pending_page = None

        self._load_ollama_settings()
        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._start_render_thread()

    # ------------------------------------------------------------------
    # Render thread
    # ------------------------------------------------------------------

    def _start_render_thread(self):
        self._render_thread = QThread()
        self._render_worker = PageRenderWorker()
        self._render_worker.moveToThread(self._render_thread)
        self._render_requested.connect(self._render_worker.render)
        self._render_worker.page_ready.connect(self._on_page_ready)
        self._render_thread.start()

    def closeEvent(self, event):
        self._render_thread.quit()
        self._render_thread.wait()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.welcome = WelcomeScreen()
        self.welcome.open_pdf_requested.connect(self._new_project)
        self.welcome.open_project_requested.connect(self._open_project)
        self.welcome.pdf_dropped.connect(self._new_project_from_path)
        self.stack.addWidget(self.welcome)

        workspace = QWidget()
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.project_panel = ProjectPanel()
        self.project_panel.setMinimumWidth(180)
        self.project_panel.setMaximumWidth(300)
        self.project_panel.page_selected.connect(self._load_page)
        self.project_panel.page_rename_requested.connect(self._rename_page)

        self.viewer = PDFViewer()
        self.viewer.scale_set.connect(self._on_scale_set)

        self.chat_panel = ChatPanel()

        splitter.addWidget(self.project_panel)
        splitter.addWidget(self.viewer)
        splitter.addWidget(self.chat_panel)
        splitter.setStretchFactor(1, 1)   # viewer gets all extra space
        # Start with chat panel collapsed — user can drag it open
        splitter.setSizes([220, 900, 0])

        layout.addWidget(splitter)
        self.stack.addWidget(workspace)

        # Apply persisted Ollama settings to the chat panel
        self.chat_panel.set_model(self._ollama_model)
        self.chat_panel.set_host(self._ollama_host)

    # ------------------------------------------------------------------
    # Ollama settings persistence
    # ------------------------------------------------------------------

    _CONFIG_PATH = os.path.expanduser("~/.megaswift_config.json")

    def _load_ollama_settings(self):
        """Load saved Ollama model/host from config file."""
        if os.path.exists(self._CONFIG_PATH):
            try:
                with open(self._CONFIG_PATH) as f:
                    cfg = json.load(f)
                self._ollama_model = cfg.get("ollama_model", ChatPanel.DEFAULT_MODEL)
                self._ollama_host  = cfg.get("ollama_host",  ChatPanel.DEFAULT_HOST)
            except Exception:
                self._ollama_model = ChatPanel.DEFAULT_MODEL
                self._ollama_host  = ChatPanel.DEFAULT_HOST
        else:
            self._ollama_model = ChatPanel.DEFAULT_MODEL
            self._ollama_host  = ChatPanel.DEFAULT_HOST

    def _save_ollama_settings(self):
        try:
            cfg = {}
            if os.path.exists(self._CONFIG_PATH):
                with open(self._CONFIG_PATH) as f:
                    cfg = json.load(f)
            cfg["ollama_model"] = self._ollama_model
            cfg["ollama_host"]  = self._ollama_host
            with open(self._CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))

    def _configure_ollama(self):
        model, ok = QInputDialog.getText(
            self, "Ollama Settings", "Chat model name (e.g. llama3.2, mistral):",
            text=self._ollama_model,
        )
        if not ok:
            return
        host, ok = QInputDialog.getText(
            self, "Ollama Settings", "Ollama server URL:",
            text=self._ollama_host,
        )
        if not ok:
            return
        self._ollama_model = model.strip() or ChatPanel.DEFAULT_MODEL
        self._ollama_host  = host.strip()  or ChatPanel.DEFAULT_HOST
        self.chat_panel.set_model(self._ollama_model)
        self.chat_panel.set_host(self._ollama_host)
        self._save_ollama_settings()
        self.status.showMessage(
            f"Ollama: model={self._ollama_model}  host={self._ollama_host}"
        )

    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        new_action = QAction("New Project", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        open_action = QAction("Open Project", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        save_action = QAction("Save Project", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        save_as_action = QAction("Save Project As...", self)
        save_as_action.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        ollama_action = QAction("Ollama Settings…", self)
        ollama_action.setToolTip("Set the Ollama chat model and server URL")
        ollama_action.triggered.connect(self._configure_ollama)
        file_menu.addAction(ollama_action)

    def _build_toolbar(self):
        toolbar = QToolBar("Tools")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.scale_btn = QPushButton("Set Scale")
        self.scale_btn.setCheckable(True)
        self.scale_btn.setToolTip(
            "Click two points on a known distance to calibrate the page scale.\n"
            "Only one scale line per page — setting a new one replaces the old."
        )
        self.scale_btn.clicked.connect(self._start_scale)
        toolbar.addWidget(self.scale_btn)

        self.dim_btn = QPushButton("Dimension")
        self.dim_btn.setCheckable(True)
        self.dim_btn.setToolTip("Click two points to measure distance (scale must be set first)")
        self.dim_btn.clicked.connect(self._start_dimension)
        toolbar.addWidget(self.dim_btn)

        toolbar.addSeparator()

        rename_btn = QPushButton("Rename Page")
        rename_btn.setToolTip("Rename the current page (or double-click in sidebar)")
        rename_btn.clicked.connect(self._rename_current_page)
        toolbar.addWidget(rename_btn)

        toolbar.addSeparator()

        auto_name_btn = QPushButton("Auto Name Pages")
        auto_name_btn.setToolTip(
            "Read embedded text from the bottom-right corner of each page\n"
            "and use it to name pages automatically."
        )
        auto_name_btn.clicked.connect(self._auto_name_pages)
        toolbar.addWidget(auto_name_btn)

        auto_scale_btn = QPushButton("Auto Scale")
        auto_scale_btn.setToolTip(
            "Scan the current page for an embedded scale (e.g. 1\"=20')\n"
            "and apply it automatically."
        )
        auto_scale_btn.clicked.connect(self._auto_scale_page)
        toolbar.addWidget(auto_scale_btn)

        toolbar.addSeparator()

        self.chat_btn = QPushButton("Chat")
        self.chat_btn.setCheckable(True)
        self.chat_btn.setToolTip("Toggle Ollama chat panel")
        self.chat_btn.clicked.connect(self._toggle_chat)
        toolbar.addWidget(self.chat_btn)

    def _toggle_chat(self):
        splitter = self.chat_panel.parent()
        if not isinstance(splitter, QSplitter):
            return
        sizes = splitter.sizes()
        if sizes[2] < 10:
            splitter.setSizes([sizes[0], sizes[1] - 320, 320])
            self.chat_btn.setChecked(True)
        else:
            splitter.setSizes([sizes[0], sizes[1] + sizes[2], 0])
            self.chat_btn.setChecked(False)

    def _build_statusbar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.scale_label = QLabel("Scale: not set")
        self.status.addPermanentWidget(self.scale_label)

    # ------------------------------------------------------------------
    # Project actions
    # ------------------------------------------------------------------

    def _show_workspace(self):
        self.stack.setCurrentIndex(1)

    @staticmethod
    def _extract_page_names(doc) -> list[str]:
        """
        Try to pull meaningful page names from the PDF in this order:
          1. Table of contents (bookmarks) — civil plan sets almost always have these
          2. PDF page labels (e.g. "C-1", "i", "A")
          3. Fall back to "Page N"
        """
        count = len(doc)
        names = [f"Page {i + 1}" for i in range(count)]

        # 1. Table of contents: [[level, title, page_number (1-indexed)], ...]
        toc = doc.get_toc()
        for entry in toc:
            _level, title, page_num = entry[0], entry[1], entry[2]
            idx = page_num - 1
            if 0 <= idx < count and title.strip():
                # Only take the first TOC entry per page
                if names[idx] == f"Page {idx + 1}":
                    names[idx] = title.strip()

        # 2. PDF page labels for any pages not covered by TOC
        for i in range(count):
            if names[i] == f"Page {i + 1}":
                try:
                    label = doc.get_page_label(i)
                    if label and label.strip():
                        names[i] = label.strip()
                except Exception:
                    pass

        return names

    def _new_project_from_path(self, pdf_path: str):
        self._new_project(pdf_path=pdf_path)

    def _new_project(self, pdf_path: str = ""):
        if not pdf_path:
            pdf_path, _ = QFileDialog.getOpenFileName(
                self, "Select PDF File", "", "PDF Files (*.pdf)"
            )
        if not pdf_path:
            return

        project_name, ok = QInputDialog.getText(
            self, "New Project", "Enter a name for this project:"
        )
        if not ok or not project_name.strip():
            return

        self._pdf_doc = fitz.open(pdf_path)
        page_count = len(self._pdf_doc)
        page_names = self._extract_page_names(self._pdf_doc)

        self._project = {
            "name": project_name.strip(),
            "pdf_path": pdf_path,
            "pages": [{"name": page_names[i], "index": i, "measurements": []}
                      for i in range(page_count)],
            "scale_feet_per_pixel": None,
        }

        self._project_path = None
        self._current_page = 0
        self.project_panel.load_project(self._project["name"], self._project["pages"])
        self._show_workspace()
        self._load_page(0)
        self.setWindowTitle(f"MegaSwift - {self._project['name']}")
        self.status.showMessage(
            f"Project '{self._project['name']}' created — {page_count} pages loaded."
        )
        self._save_project_as()

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "MegaSwift Projects (*.mswift)"
        )
        if not path:
            return

        with open(path, "r") as f:
            self._project = json.load(f)

        for page in self._project.get("pages", []):
            page.setdefault("measurements", [])

        self._project_path = path
        pdf_path = self._project.get("pdf_path", "")

        if not os.path.exists(pdf_path):
            alt = os.path.join(os.path.dirname(path), os.path.basename(pdf_path))
            if os.path.exists(alt):
                pdf_path = alt
                self._project["pdf_path"] = pdf_path
            else:
                QMessageBox.warning(
                    self, "PDF Not Found",
                    f"Could not locate:\n{pdf_path}\n\nPlease find it manually."
                )
                pdf_path, _ = QFileDialog.getOpenFileName(
                    self, "Locate PDF", "", "PDF Files (*.pdf)"
                )
                if not pdf_path:
                    return
                self._project["pdf_path"] = pdf_path

        self._pdf_doc = fitz.open(pdf_path)

        scale = self._project.get("scale_feet_per_pixel")
        if scale:
            self.viewer.set_scale(scale)
            self.scale_label.setText(f"Scale: {scale:.6f} ft/px")

        self.project_panel.load_project(self._project["name"], self._project["pages"])
        self._current_page = 0
        self._show_workspace()
        self._load_page(0)
        self.setWindowTitle(f"MegaSwift - {self._project['name']}")
        self.status.showMessage(f"Project '{self._project['name']}' opened.")

    def _save_project(self):
        if not self._project:
            return
        if not self._project_path:
            self._save_project_as()
        else:
            self._write_project(self._project_path)

    def _save_project_as(self):
        if not self._project:
            return
        default_name = self._project["name"].replace(" ", "_") + ".mswift"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", default_name, "MegaSwift Projects (*.mswift)"
        )
        if path:
            self._project_path = path
            self._write_project(path)

    def _write_project(self, path: str):
        self._save_current_page_measurements()
        if self.viewer.get_scale():
            self._project["scale_feet_per_pixel"] = self.viewer.get_scale()
        with open(path, "w") as f:
            json.dump(self._project, f, indent=2)
        self.status.showMessage(f"Project saved: {path}")

    # ------------------------------------------------------------------
    # Page actions
    # ------------------------------------------------------------------

    def _save_current_page_measurements(self):
        if self._project:
            self._project["pages"][self._current_page]["measurements"] = (
                self.viewer.get_measurements()
            )

    def _load_page(self, index: int):
        if not self._project:
            return
        self._save_current_page_measurements()
        self._pending_page = index
        page_name = self._project["pages"][index]["name"]
        self.status.showMessage(f"Loading: {page_name}...")
        self._render_requested.emit(self._project["pdf_path"], index)

    def _on_page_ready(self, pixmap: QPixmap, page_index: int):
        if page_index != self._pending_page:
            return
        if pixmap.isNull():
            self.status.showMessage("Error rendering page.")
            return

        self._current_page = page_index
        self.viewer.load_page(pixmap)

        saved = self._project["pages"][page_index].get("measurements", []) if self._project else []
        self.viewer.load_measurements(saved)

        page_name = (
            self._project["pages"][page_index]["name"]
            if self._project else f"Page {page_index + 1}"
        )
        self.status.showMessage(
            f"Viewing: {page_name}  |  Drag endpoints to adjust  •  Click to select  •  Delete to remove"
        )

        # Update chat context so the model knows which page is open
        project_name = self._project.get("name", "") if self._project else ""
        scale = self.viewer.get_scale()
        scale_str = f"{scale:.6f} ft/px" if scale else "not set"
        self.chat_panel.set_page_context(
            f"Project: {project_name}  |  Page {page_index + 1} of "
            f"{len(self._project['pages'])}: '{page_name}'  |  Scale: {scale_str}"
        )

    def _rename_page(self, index: int):
        if not self._project:
            return
        current_name = self._project["pages"][index]["name"]
        new_name, ok = QInputDialog.getText(
            self, "Rename Page", "New page name:", text=current_name
        )
        if ok and new_name.strip():
            self._project["pages"][index]["name"] = new_name.strip()
            self.project_panel.update_page_name(index, new_name.strip())
            self.status.showMessage(f"Page renamed to '{new_name.strip()}'")

    def _rename_current_page(self):
        self._rename_page(self._current_page)

    def _auto_name_pages(self):
        """
        Read embedded text from the bottom-right corner of every page
        and use it to rename pages in the sidebar.

        The bottom-right corner is where civil plan sets almost always print
        the sheet number (e.g. "C-1", "W-3", "1 of 12"). We clip to the
        bottom 20% / right 35% of each page to isolate that region.

        Pages where no text is found keep their existing name.
        """
        if not self._project or not self._pdf_doc:
            QMessageBox.warning(self, "No Project", "Open a project first.")
            return

        doc = self._pdf_doc
        updated = 0

        for i, page_data in enumerate(self._project["pages"]):
            page = doc[i]
            w = page.rect.width
            h = page.rect.height

            # Clip rectangle: bottom 5% of height, rightmost 5% of width — flush with corner
            clip = fitz.Rect(w * 0.95, h * 0.95, w, h)

            # Extract words with their positions from only that region
            words = page.get_text("words", clip=clip)

            text = ""
            if words:
                words_sorted = sorted(words, key=lambda wd: (round(wd[1] / 10), wd[0]))
                text = " ".join(wd[4] for wd in words_sorted).strip()

            if text:
                page_data["name"] = text
                self.project_panel.update_page_name(i, text)
                updated += 1

        if updated:
            msg = f"Auto Name: updated {updated} of {len(self._project['pages'])} pages."
        else:
            msg = "Auto Name: no sheet identifiers found in embedded text."

        self.status.showMessage(msg)

    def _auto_scale_page(self):
        """
        Scan the current page for an embedded scale expression and apply it.

        Civil plans almost always print the scale in the title block as text like:
            1" = 20'    1"=40'    1" = 20'-0"    SCALE: 1"=30'    1:240

        We search the full bottom 25% of the page (the title block band) for any
        of those patterns, calculate feet_per_pixel, and apply it exactly as if
        the user had set it manually with the Set Scale tool.

        PIXELS_PER_DRAWING_INCH: our render matrix is 2x at 72 DPI = 144 px/inch.
        """
        if not self._project or not self._pdf_doc:
            QMessageBox.warning(self, "No Project", "Open a project first.")
            return

        PIXELS_PER_DRAWING_INCH = 144  # 72 DPI base × 2x render matrix

        page = self._pdf_doc[self._current_page]
        w, h = page.rect.width, page.rect.height

        # Search the full-width bottom 25% — title block spans the whole bottom
        clip = fitz.Rect(0, h * 0.75, w, h)
        text = page.get_text(clip=clip)

        feet_per_inch = self._parse_scale_text(text)

        if feet_per_inch is None:
            self.status.showMessage(
                "Auto Scale: no scale found in embedded text. "
                "Try setting the scale manually with 'Set Scale'."
            )
            return

        feet_per_pixel = feet_per_inch / PIXELS_PER_DRAWING_INCH

        # Apply — same path as manual Set Scale
        self.viewer.set_scale(feet_per_pixel)
        if self._project:
            self._project["scale_feet_per_pixel"] = feet_per_pixel
        self.scale_label.setText(f"Scale: {feet_per_pixel:.6f} ft/px")
        self.status.showMessage(
            f"Auto Scale: detected 1\" = {feet_per_inch:.0f}' — scale applied successfully."
        )

    @staticmethod
    def _parse_scale_text(text: str):
        """
        Parse common US civil drawing scale formats from raw page text.
        Returns the real-world feet represented by 1 drawing inch, or None.

        Handles:
            1" = 20'          → 20.0
            1"=20'            → 20.0
            1" = 20'-0"       → 20.0
            SCALE: 1"=30'     → 30.0
            1:240             → 20.0  (240 inches ÷ 12)
            1:480             → 40.0
        """
        # Normalise — collapse whitespace, upper-case
        t = re.sub(r'\s+', ' ', text.upper())

        # Pattern A: 1" = 20'  /  1"=20'  /  1" = 20'-0"
        # Accepts straight or curly quote variants
        m = re.search(
            r'1\s*["\u201c\u201d\u2033]\s*=\s*(\d+(?:\.\d+)?)\s*[\'\u2018\u2019\u2032]',
            t
        )
        if m:
            return float(m.group(1))

        # Pattern B: ratio format  1:240
        m = re.search(r'\b1\s*:\s*(\d{2,})\b', t)
        if m:
            ratio_inches = int(m.group(1))
            return ratio_inches / 12.0

        return None

    # ------------------------------------------------------------------
    # Scale / Dimension tools
    # ------------------------------------------------------------------

    def _start_scale(self):
        if not self._project:
            self.scale_btn.setChecked(False)
            QMessageBox.warning(self, "No Project", "Open or create a project first.")
            return

        distance, ok = QInputDialog.getDouble(
            self, "Set Scale",
            "Enter the known real-world distance (in feet):",
            value=10.0, min=0.01, max=99999.0, decimals=2
        )
        if not ok:
            self.scale_btn.setChecked(False)
            return

        self.viewer.set_mode(PDFViewer.MODE_SCALE, known_distance=distance)
        self.dim_btn.setChecked(False)
        self.status.showMessage(
            f"Scale mode — click START of the {distance:.2f} ft reference, then END."
        )

    def _start_dimension(self):
        if not self._project:
            self.dim_btn.setChecked(False)
            QMessageBox.warning(self, "No Project", "Open or create a project first.")
            return
        if not self.viewer.get_scale():
            self.dim_btn.setChecked(False)
            QMessageBox.warning(self, "Scale Not Set", "Please set the scale before measuring.")
            return

        self.viewer.set_mode(PDFViewer.MODE_DIMENSION)
        self.scale_btn.setChecked(False)
        self.status.showMessage("Dimension mode — click START point, then END point.")

    def _on_scale_set(self, feet_per_pixel: float):
        self.scale_btn.setChecked(False)
        if self._project:
            self._project["scale_feet_per_pixel"] = feet_per_pixel
        self.scale_label.setText(f"Scale: {feet_per_pixel:.6f} ft/px")
        self.status.showMessage(
            "Scale set. Drag the orange line endpoints to fine-tune."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MegaSwift")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
