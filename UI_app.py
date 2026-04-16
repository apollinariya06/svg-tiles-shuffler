"""SVG Tiles Shuffler - PySide6 Desktop App."""

import sys
import subprocess

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QRectF
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QSplitter, QLabel, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QSlider, QFileDialog, QLineEdit,
    QGroupBox, QTabWidget, QTextEdit, QGraphicsView, QGraphicsScene,
)
from PySide6.QtSvgWidgets import QGraphicsSvgItem


SCRIPT = Path(__file__).parent / "svg-tiles-shuffler.py"
PAPER_SIZES = ["(none)", "a6", "a5", "a4", "a3", "a2", "letter", "legal", "tabloid", "custom"]

# Unit presets — slider uses integers internally; 'scale' converts to real values.
# Real value = slider_value / scale.  E.g. cm with scale=10: slider 15 → 1.5 cm.
UNIT_CONFIG = {
    "mm": {"gap_max": 50,  "gap_default": 5,  "margin_max": 50,  "margin_default": 10, "scale": 1},
    "cm": {"gap_max": 50,  "gap_default": 5,  "margin_max": 50, "margin_default": 10, "scale": 10},
    "in": {"gap_max": 20,  "gap_default": 2,  "margin_max": 20,  "margin_default": 4,  "scale": 10},
    "px": {"gap_max": 200, "gap_default": 20, "margin_max": 200, "margin_default": 40, "scale": 1},
}


# ======================================================================
# Worker thread
# ======================================================================
class Worker(QThread):
    finished = Signal(str)   # output SVG path
    error = Signal(str)      # error message
    log = Signal(str)        # stdout/stderr

    def __init__(self, cmd, cwd):
        super().__init__()
        self.cmd = cmd
        self.cwd = cwd

    def run(self):
        try:
            proc = subprocess.run(
                self.cmd, capture_output=True, text=True,
                cwd=self.cwd, timeout=120,
            )
            if proc.stdout:
                self.log.emit(proc.stdout)
            if proc.returncode != 0:
                self.error.emit(proc.stderr or f"Exit code {proc.returncode}")
                return
            out_files = [
                f for f in Path(self.cwd).glob("*.svg")
                if "_mosaic" in f.name or "_shuffled" in f.name
            ]
            if out_files:
                out = max(out_files, key=lambda f: f.stat().st_mtime)
                self.finished.emit(str(out))
            else:
                self.error.emit("No output SVG found.")
        except subprocess.TimeoutExpired:
            self.error.emit("Timed out (120s).")
        except Exception as e:
            self.error.emit(str(e))


# ======================================================================
# SVG preview widget with zoom/pan
# ======================================================================
class SvgPreview(QGraphicsView):
    """SVG viewer that preserves aspect ratio."""

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setMinimumSize(300, 300)
        self.setRenderHints(
            self.renderHints()
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setStyleSheet("background-color: white;")
        self._item = None

    def load(self, path: str):
        self._scene.clear()
        self._item = QGraphicsSvgItem(path)
        self._scene.addItem(self._item)
        self._scene.setSceneRect(self._item.boundingRect())
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._item:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

# ======================================================================
# Main window
# ======================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVG Tiles Shuffler")
        self.setMinimumSize(1000, 700)
        self.setAcceptDrops(True)

        self.input_path = None
        self.output_path = None

        self.worker = None

        self._build_ui()
        self._connect_signals()
        self.statusBar().showMessage("Open an SVG file to get started.")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ---- Left: controls ----
        controls = QWidget()
        controls.setMinimumWidth(280)
        controls.setMaximumWidth(350)
        ctrl_layout = QVBoxLayout(controls)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)

        # Open button
        self.btn_open = QPushButton("Open SVG...")
        self.btn_open.setMinimumHeight(36)
        ctrl_layout.addWidget(self.btn_open)

        # Grid group
        grid_group = QGroupBox("Grid")
        grid_form = QFormLayout(grid_group)
        self.spin_n = QSpinBox()
        self.spin_n.setRange(2, 12)
        self.spin_n.setValue(4)
        grid_form.addRow("Size (n x n):", self.spin_n)
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 12)
        self.spin_rows.setValue(4)
        grid_form.addRow("Rows:", self.spin_rows)
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 12)
        self.spin_cols.setValue(4)
        grid_form.addRow("Cols:", self.spin_cols)
        self.chk_square = QCheckBox("Square tiles")
        grid_form.addRow(self.chk_square)
        ctrl_layout.addWidget(grid_group)

        # Paper group
        paper_group = QGroupBox("Paper")
        paper_form = QFormLayout(paper_group)
        self.cmb_paper = QComboBox()
        self.cmb_paper.addItems(PAPER_SIZES)
        paper_form.addRow("Size:", self.cmb_paper)
        self.chk_landscape = QCheckBox("Landscape")
        paper_form.addRow(self.chk_landscape)
        self.txt_custom_paper = QLineEdit()
        self.txt_custom_paper.setPlaceholderText("WxH (e.g. 200mmx300mm) - use mm, cm, in, px")
        paper_form.addRow(self.txt_custom_paper)
        self.txt_custom_paper.setVisible(False)
        ctrl_layout.addWidget(paper_group)

        # Spacing group
        spacing_group = QGroupBox("Spacing")
        spacing_form = QFormLayout(spacing_group)

        self.cmb_unit = QComboBox()
        self.cmb_unit.addItems(["mm", "cm", "in", "px"])
        spacing_form.addRow("Unit:", self.cmb_unit)

        self.slider_gap = QSlider(Qt.Horizontal)
        self.slider_gap.setRange(0, 30)
        self.slider_gap.setValue(5)
        self.slider_gap.setSingleStep(1)
        self.lbl_gap = QLabel("5 mm")
        self.lbl_gap.setMinimumWidth(50)
        gap_row = QHBoxLayout()
        gap_row.addWidget(self.slider_gap)
        gap_row.addWidget(self.lbl_gap)
        spacing_form.addRow("Gap:", gap_row)

        self.slider_margin = QSlider(Qt.Horizontal)
        self.slider_margin.setRange(0, 50)
        self.slider_margin.setValue(10)
        self.slider_margin.setSingleStep(1)
        self.lbl_margin = QLabel("10 mm")
        self.lbl_margin.setMinimumWidth(50)
        margin_row = QHBoxLayout()
        margin_row.addWidget(self.slider_margin)
        margin_row.addWidget(self.lbl_margin)
        spacing_form.addRow("Margin:", margin_row)

        ctrl_layout.addWidget(spacing_group)

        # Shuffle group
        shuffle_group = QGroupBox("Shuffle")
        shuffle_form = QFormLayout(shuffle_group)
        self.chk_shuffle = QCheckBox("Enable")
        shuffle_form.addRow(self.chk_shuffle)
        self.chk_no_rotate = QCheckBox("No rotation")
        self.chk_no_rotate.setEnabled(False)
        shuffle_form.addRow(self.chk_no_rotate)
        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 9999)
        self.spin_seed.setValue(42)
        self.spin_seed.setEnabled(False)
        self.chk_seed = QCheckBox("Fixed seed:")
        self.chk_seed.setEnabled(False)
        seed_row = QHBoxLayout()
        seed_row.addWidget(self.chk_seed)
        seed_row.addWidget(self.spin_seed)
        shuffle_form.addRow(seed_row)
        ctrl_layout.addWidget(shuffle_group)
        
        # Keep Tiles group
        keep_tiles_group = QGroupBox("Keep Tiles")
        keep_tiles_form = QFormLayout(keep_tiles_group)
        self.chk_keep_tiles = QCheckBox("Enable")
        keep_tiles_form.addRow(self.chk_keep_tiles)
        ctrl_layout.addWidget(keep_tiles_group)

        ctrl_layout.addStretch()

        # Generate + Save buttons
        self.btn_generate = QPushButton("Generate")
        self.btn_generate.setMinimumHeight(40)
        self.btn_generate.setEnabled(False)
        self.btn_generate.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; font-size: 14px; } QPushButton:disabled { background-color: #ccc; color: #666; }")
        ctrl_layout.addWidget(self.btn_generate)

        self.btn_save = QPushButton("Save SVG...")
        self.btn_save.setMinimumHeight(36)
        self.btn_save.setEnabled(False)
        ctrl_layout.addWidget(self.btn_save)

        # ---- Right: SVG previews ----
        self.tabs = QTabWidget()
        self.svg_input = SvgPreview()
        self.svg_result = SvgPreview()
        self.tabs.addTab(self.svg_input, "Input")
        self.tabs.addTab(self.svg_result, "Result")

        # Log panel
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        self.log_text.setVisible(False)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.tabs, 1)
        right_layout.addWidget(self.log_text)

        # Command preview
        self.cmd_label = QLabel("CLI command:")
        self.cmd_preview = QTextEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setMaximumHeight(50)
        right_layout.addWidget(self.cmd_label)
        right_layout.addWidget(self.cmd_preview)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(controls)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    def _connect_signals(self):
        self.btn_open.clicked.connect(self.open_file)
        self.btn_generate.clicked.connect(self.generate)
        self.btn_save.clicked.connect(self.save_file)

        self.slider_gap.valueChanged.connect(self._update_spacing_labels)
        self.slider_margin.valueChanged.connect(self._update_spacing_labels)
        self.cmb_unit.currentTextChanged.connect(self._on_unit_changed)

        self.chk_shuffle.toggled.connect(self.chk_no_rotate.setEnabled)
        self.chk_shuffle.toggled.connect(self.chk_seed.setEnabled)
        self.chk_seed.toggled.connect(self.spin_seed.setEnabled)

        # Sync n <-> rows/cols
        self.spin_n.valueChanged.connect(self.spin_rows.setValue)
        self.spin_n.valueChanged.connect(self.spin_cols.setValue)

        # Show/hide custom paper field
        self.cmb_paper.currentTextChanged.connect(
            lambda t: self.txt_custom_paper.setVisible(t == "custom")
        )

        # Update command preview on any change
        self.spin_n.valueChanged.connect(self._update_command_preview)
        self.spin_rows.valueChanged.connect(self._update_command_preview)
        self.spin_cols.valueChanged.connect(self._update_command_preview)
        self.chk_square.toggled.connect(self._update_command_preview)
        self.cmb_paper.currentTextChanged.connect(self._update_command_preview)
        self.txt_custom_paper.textChanged.connect(self._update_command_preview)
        self.chk_landscape.toggled.connect(self._update_command_preview)
        self.slider_gap.valueChanged.connect(self._update_command_preview)
        self.slider_margin.valueChanged.connect(self._update_command_preview)
        self.cmb_unit.currentTextChanged.connect(self._update_command_preview)
        self.chk_shuffle.toggled.connect(self._update_command_preview)
        self.chk_keep_tiles.toggled.connect(self._update_command_preview)
        self.chk_no_rotate.toggled.connect(self._update_command_preview)
        self.chk_seed.toggled.connect(self._update_command_preview)
        self.spin_seed.valueChanged.connect(self._update_command_preview)

        # Initial update
        self._update_command_preview()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SVG", "", "SVG files (*.svg)"
        )
        if path:
            self.load_svg(path)

    def load_svg(self, path):
        self.input_path = Path(path)
        self.svg_input.load(str(self.input_path))
        self.tabs.setCurrentIndex(0)
        self.btn_generate.setEnabled(True)
        self.statusBar().showMessage(f"Loaded: {self.input_path.name}")
        self.setWindowTitle(f"SVG Tiles Shuffler - {self.input_path.name}")
        self._update_command_preview()

    def _on_unit_changed(self, unit):
        """Update slider ranges and values when the unit changes."""
        cfg = UNIT_CONFIG[unit]
        self.slider_gap.setRange(0, cfg["gap_max"])
        self.slider_gap.setValue(cfg["gap_default"])
        self.slider_margin.setRange(0, cfg["margin_max"])
        self.slider_margin.setValue(cfg["margin_default"])
        self._update_spacing_labels()

    def _format_spacing(self, slider_value):
        """Format a slider value using the current unit and scale."""
        unit = self.cmb_unit.currentText()
        scale = UNIT_CONFIG[unit]["scale"]
        val = slider_value / scale
        if val == int(val):
            return f"{int(val)}{unit}"
        return f"{val:.1f}{unit}"

    def _update_spacing_labels(self):
        """Update the gap/margin labels with current value and unit."""
        unit = self.cmb_unit.currentText()
        scale = UNIT_CONFIG[unit]["scale"]
        gap_val = self.slider_gap.value() / scale
        margin_val = self.slider_margin.value() / scale
        fmt = lambda v: f"{int(v)}" if v == int(v) else f"{v:.1f}"
        self.lbl_gap.setText(f"{fmt(gap_val)} {unit}")
        self.lbl_margin.setText(f"{fmt(margin_val)} {unit}")
        self._update_command_preview()

    def build_command(self, input_svg):
        cmd = [sys.executable, str(SCRIPT), str(input_svg)]
        rows = self.spin_rows.value()
        cols = self.spin_cols.value()
        if rows == cols:
            cmd.append(str(rows))
        else:
            cmd += ["--rows", str(rows), "--cols", str(cols)]
        paper = self.cmb_paper.currentText()
        if paper == "custom":
            custom_val = self.txt_custom_paper.text().strip()
            if custom_val:
                cmd += ["--paper", custom_val]
        elif paper != "(none)":
            cmd += ["--paper", paper]
        if self.chk_landscape.isChecked():
            cmd.append("--landscape")
        if self.chk_square.isChecked():
            cmd.append("--square")
        gap_str = self._format_spacing(self.slider_gap.value())
        cmd += ["--gap", gap_str if self.slider_gap.value() > 0 else "0"]
        margin_str = self._format_spacing(self.slider_margin.value())
        cmd += ["--margin", margin_str if self.slider_margin.value() > 0 else "0"]
        if self.chk_shuffle.isChecked():
            cmd.append("--shuffle")
            if self.chk_no_rotate.isChecked():
                cmd.append("--no-rotate")
            if self.chk_seed.isChecked():
                cmd += ["--seed", str(self.spin_seed.value())]
        if self.chk_keep_tiles.isChecked():
            cmd.append("--keep-tiles")
        return cmd

    def _update_command_preview(self):
        """Update the CLI command preview in real time."""
        input_name = self.input_path.name if self.input_path else "input.svg"
        cmd = self.build_command(Path(input_name))
        # Replace python path and script path with short names
        cmd_str = " ".join(cmd)
        cmd_str = cmd_str.replace(str(SCRIPT), "svg-tiles-shuffler.py")
        import sys as _sys
        cmd_str = cmd_str.replace(_sys.executable, "python")
        self.cmd_preview.setPlainText(cmd_str)

    def generate(self):
        if not self.input_path:
            return

        self.btn_generate.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.log_text.clear()
        self.log_text.setVisible(False)
        self.statusBar().showMessage("Generating...")

        cmd = self.build_command(self.input_path)
        work_dir = str(self.input_path.parent)

        self.worker = Worker(cmd, work_dir)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.log.connect(self._on_log)
        self.worker.start()

    def _on_finished(self, out_path):
        self.output_path = Path(out_path)
        self.svg_result.load(str(self.output_path))
        self.tabs.setCurrentIndex(1)
        self.btn_generate.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.statusBar().showMessage(f"Done: {self.output_path.name}")

    def _on_error(self, msg):
        self.log_text.setVisible(True)
        self.log_text.setPlainText("ERROR:\n" + msg)
        self.btn_generate.setEnabled(True)
        self.statusBar().showMessage("Error.")

    def _on_log(self, text):
        self.log_text.setVisible(True)
        self.log_text.setPlainText(text)

    def save_file(self):
        if not self.output_path or not self.output_path.exists():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save SVG", str(self.output_path), "SVG files (*.svg)"
        )
        if path:
            shutil.copy2(self.output_path, path)
            self.statusBar().showMessage(f"Saved: {Path(path).name}")

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".svg"):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".svg"):
                self.load_svg(path)
                break

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        event.accept()



# ======================================================================
# Entry point
# ======================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon_path = Path(__file__).parent / "img/icon.png"
    app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
