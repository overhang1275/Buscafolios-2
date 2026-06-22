from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QThread, QTimer, Qt, Slot
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QAbstractTableModel, QModelIndex

from busca_folios.duckdb_engine import (
    delimiter_value,
    detect_columns,
    duckdb_encoding,
    file_size_label,
    preview_file,
)
from busca_folios.models import FileConfig, SearchConfig, SearchStats
from busca_folios.worker import SearchWorker

LOGGER = logging.getLogger(__name__)


class DataFrameModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._data = None

    def set_frame(self, frame) -> None:
        self.beginResetModel()
        self._data = frame
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if self._data is None else len(self._data)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if self._data is None else len(self._data.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and self._data is not None:
            return str(self._data.iat[index.row(), index.column()])
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int):
        if role != Qt.ItemDataRole.DisplayRole or self._data is None:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._data.columns[section])
        return str(section)


class FilePanel(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("Selecciona un archivo TXT o CSV")
        self.size = QLabel("-")
        self.header = QCheckBox("Primera linea contiene encabezados")
        self.header.setChecked(True)
        self.separator = QComboBox()
        self.separator.addItems(["Coma (,)", "Pipe (|)", "Tabulacion", "Punto y coma (;)", "Personalizado"])
        self.custom_separator = QLineEdit()
        self.custom_separator.setMaximumWidth(70)
        self.custom_separator.setEnabled(False)
        self.encoding = QComboBox()
        self.encoding.addItems(["UTF-8", "Latin1", "ANSI"])
        self.folio_column = QComboBox()
        self.preview = QTableView()
        self.preview_model = DataFrameModel()
        self.preview.setModel(self.preview_model)
        self.preview.setMinimumHeight(170)
        self.preview.setAlternatingRowColors(True)

        browse = QPushButton("Seleccionar")
        browse.clicked.connect(self.select_file)
        self.separator.currentTextChanged.connect(
            lambda value: self.custom_separator.setEnabled(value == "Personalizado")
        )
        for widget in (self.header, self.separator, self.custom_separator, self.encoding):
            self._connect_reload_signal(widget)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(self.path)
        top.addWidget(browse)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addRow("Archivo", top)
        form.addRow("Tamano", self.size)
        form.addRow("", self.header)
        sep_row = QHBoxLayout()
        sep_row.setContentsMargins(0, 0, 0, 0)
        sep_row.setSpacing(8)
        sep_row.addWidget(self.separator)
        sep_row.addWidget(self.custom_separator)
        form.addRow("Separador", sep_row)
        form.addRow("Codificacion", self.encoding)
        form.addRow("Columna folio", self.folio_column)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(QLabel("Vista previa"))
        layout.addWidget(self.preview, stretch=1)

    def _connect_reload_signal(self, widget: QObject) -> None:
        if isinstance(widget, QCheckBox):
            widget.stateChanged.connect(lambda _state: self.reload_preview())
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(lambda _text: self.reload_preview())
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(lambda _index: self.reload_preview())
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(lambda _value: self.reload_preview())
        elif isinstance(widget, QPushButton):
            widget.clicked.connect(self.reload_preview)
        else:
            raise TypeError(f"Widget sin senal de recarga configurada: {type(widget).__name__}")

    def select_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar archivo", "", "Datos (*.csv *.txt);;Todos (*.*)"
        )
        if filename:
            self.path.setText(filename)
            self.size.setText(file_size_label(Path(filename)))
            self.reload_preview()

    def config(self) -> FileConfig:
        if not self.path.text():
            raise ValueError(f"Falta seleccionar archivo en {self.title()}")
        delimiter = delimiter_value(self.separator.currentText(), self.custom_separator.text())
        if not delimiter:
            raise ValueError("El separador personalizado no puede estar vacio")
        if not self.folio_column.currentText():
            raise ValueError(f"Falta seleccionar columna de folio en {self.title()}")
        return FileConfig(
            path=Path(self.path.text()),
            has_header=self.header.isChecked(),
            delimiter=delimiter,
            encoding=duckdb_encoding(self.encoding.currentText()),
            folio_column=self.folio_column.currentText(),
        )

    @Slot()
    def reload_preview(self) -> None:
        if not self.path.text():
            return
        try:
            config = FileConfig(
                path=Path(self.path.text()),
                has_header=self.header.isChecked(),
                delimiter=delimiter_value(self.separator.currentText(), self.custom_separator.text()),
                encoding=duckdb_encoding(self.encoding.currentText()),
                folio_column=self.folio_column.currentText() or "",
            )
            columns = detect_columns(config)
            current = self.folio_column.currentText()
            self.folio_column.clear()
            self.folio_column.addItems(columns)
            if current in columns:
                self.folio_column.setCurrentText(current)
            self.preview_model.set_frame(preview_file(config, 50))
            self.preview.resizeColumnsToContents()
        except Exception as exc:
            LOGGER.exception("Preview failed")
            QMessageBox.warning(self, "Vista previa", str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Busca Folios")
        self.resize(1280, 820)
        self.worker: SearchWorker | None = None
        self.thread: QThread | None = None
        self.output_dir: Path | None = None
        self.elapsed = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed)

        self.production = FilePanel("Archivo de produccion")
        self.folios = FilePanel("Folios de reposicion")
        self.start_row = QLineEdit()
        self.start_row.setPlaceholderText("Vacio = inicio")
        self.end_row = QLineEdit()
        self.end_row.setPlaceholderText("Vacio = fin")
        self.export_xlsx = QCheckBox("Tambien exportar XLSX")
        self.progress = QProgressBar()
        self.status = QLabel("Listo")
        self.elapsed_label = QLabel("00:00:00")
        self.stats = QLabel("-")
        self.metric_labels: dict[str, QLabel] = {}
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.start_button = QPushButton("Iniciar")
        self.cancel_button = QPushButton("Cancelar")
        self.open_button = QPushButton("Abrir carpeta de resultados")
        self.start_button.setObjectName("primaryButton")
        self.cancel_button.setObjectName("dangerButton")
        self.open_button.setObjectName("secondaryButton")
        self.cancel_button.setEnabled(False)
        self.open_button.setEnabled(False)

        self.start_button.clicked.connect(self.start_search)
        self.cancel_button.clicked.connect(self.cancel_search)
        self.open_button.clicked.connect(self.open_results)

        self._build_ui()
        self._style()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("appHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel("Busca Folios")
        title.setObjectName("appTitle")
        subtitle = QLabel("Busqueda masiva de folios con DuckDB")
        subtitle.setObjectName("appSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        files = QHBoxLayout()
        files.setSpacing(10)
        files.addWidget(self.production, stretch=1)
        files.addWidget(self.folios, stretch=1)
        root.addLayout(files, stretch=2)

        middle = QHBoxLayout()
        middle.setSpacing(10)
        middle.addWidget(self._range_group(), stretch=1)
        middle.addWidget(self._execution_group(), stretch=2)
        root.addLayout(middle)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(self._summary_group(), stretch=1)
        bottom.addWidget(self._log_group(), stretch=2)
        root.addLayout(bottom, stretch=1)

        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self.close)
        self.menuBar().addMenu("Archivo").addAction(exit_action)

    def _range_group(self) -> QGroupBox:
        group = QGroupBox("Rango y salida")
        grid = QGridLayout(group)
        grid.setContentsMargins(14, 18, 14, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("Registro inicial"), 0, 0)
        grid.addWidget(self.start_row, 0, 1)
        grid.addWidget(QLabel("Registro final"), 1, 0)
        grid.addWidget(self.end_row, 1, 1)
        grid.addWidget(self.export_xlsx, 2, 1)
        return group

    def _execution_group(self) -> QGroupBox:
        group = QGroupBox("Ejecucion")
        grid = QGridLayout(group)
        grid.setContentsMargins(14, 18, 14, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("Progreso"), 0, 0)
        grid.addWidget(self.progress, 0, 1, 1, 4)
        grid.addWidget(QLabel("Tiempo"), 1, 0)
        grid.addWidget(self.elapsed_label, 1, 1)
        grid.addWidget(QLabel("Estado"), 1, 2)
        grid.addWidget(self.status, 1, 3, 1, 2)
        grid.addWidget(self.start_button, 2, 2)
        grid.addWidget(self.cancel_button, 2, 3)
        grid.addWidget(self.open_button, 2, 4)
        return group

    def _summary_group(self) -> QGroupBox:
        group = QGroupBox("Resumen")
        grid = QGridLayout(group)
        grid.setContentsMargins(14, 18, 14, 14)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        metrics = [
            ("processed", "Procesados"),
            ("searched", "Folios"),
            ("found", "Encontrados"),
            ("missing", "No encontrados"),
            ("speed", "Reg/s"),
        ]
        for index, (key, label) in enumerate(metrics):
            card = QFrame()
            card.setObjectName("metricCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(10, 8, 10, 8)
            value = QLabel("0")
            value.setObjectName("metricValue")
            caption = QLabel(label)
            caption.setObjectName("metricCaption")
            layout.addWidget(value)
            layout.addWidget(caption)
            self.metric_labels[key] = value
            grid.addWidget(card, index // 2, index % 2)
        self.stats.setObjectName("statsNote")
        grid.addWidget(self.stats, 3, 0, 1, 2)
        return group

    def _log_group(self) -> QGroupBox:
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.addWidget(self.log)
        return group

    def _style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f6f9; color: #1f2937; font-size: 13px; }
            QMenuBar { background: #ffffff; color: #1f2937; border-bottom: 1px solid #d8dee8; }
            QLabel, QCheckBox { color: #1f2937; background: transparent; }
            #appHeader { background: #ffffff; border: 1px solid #d8dee8; border-radius: 6px; }
            #appTitle { color: #111827; font-size: 22px; font-weight: 700; }
            #appSubtitle { color: #667085; font-size: 12px; }
            QGroupBox { color: #111827; font-weight: 700; border: 1px solid #d8dee8; border-radius: 6px; margin-top: 10px; background: #ffffff; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #ffffff; }
            QLineEdit, QComboBox { color: #111827; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; padding: 6px 8px; min-height: 22px; }
            QLineEdit:read-only { background: #f8fafc; color: #334155; }
            QPlainTextEdit { color: #111827; background: #0f172a; color: #dbeafe; border: 1px solid #cbd5e1; border-radius: 4px; padding: 8px; font-family: Consolas, "Courier New", monospace; }
            QTableView { color: #111827; background: #ffffff; alternate-background-color: #f8fafc; gridline-color: #e5e7eb; border: 1px solid #cbd5e1; border-radius: 4px; }
            QHeaderView::section { background: #eef2f7; color: #111827; border: 0; border-right: 1px solid #d8dee8; padding: 6px; font-weight: 600; }
            QPushButton { border: 0; border-radius: 5px; padding: 8px 12px; font-weight: 700; min-height: 24px; }
            QPushButton#primaryButton { background: #2563eb; color: #ffffff; }
            QPushButton#primaryButton:hover { background: #1d4ed8; }
            QPushButton#dangerButton { background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }
            QPushButton#secondaryButton { background: #e2e8f0; color: #1f2937; }
            QPushButton:disabled { background: #e5e7eb; color: #94a3b8; border: 1px solid #d1d5db; }
            QProgressBar { color: #111827; border: 1px solid #cbd5e1; border-radius: 4px; text-align: center; background: #ffffff; min-height: 22px; }
            QProgressBar::chunk { background: #16a34a; border-radius: 3px; }
            #metricCard { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; }
            #metricValue { color: #111827; font-size: 20px; font-weight: 800; }
            #metricCaption { color: #667085; font-size: 11px; }
            #statsNote { color: #667085; }
            """
        )

    def parse_optional_int(self, widget: QLineEdit) -> int | None:
        text = widget.text().strip()
        if not text:
            return None
        value = int(text)
        if value < 0:
            raise ValueError("Los registros inicial/final no pueden ser negativos")
        return value

    def _next_run_output_dir(self) -> Path:
        root = Path.cwd() / "resultados_busca_folios"
        root.mkdir(parents=True, exist_ok=True)
        next_lot = 1
        for child in root.iterdir():
            if child.is_dir() and "_lote_" in child.name:
                lot_text = child.name.rsplit("_lote_", 1)[1]
                if lot_text.isdigit():
                    next_lot = max(next_lot, int(lot_text) + 1)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        while True:
            output_dir = root / f"{timestamp}_lote_{next_lot:03d}"
            try:
                output_dir.mkdir(parents=True, exist_ok=False)
                return output_dir
            except FileExistsError:
                next_lot += 1

    @Slot()
    def start_search(self) -> None:
        try:
            start = self.parse_optional_int(self.start_row)
            end = self.parse_optional_int(self.end_row)
            if start is not None and end is not None and end < start:
                raise ValueError("Registro final debe ser mayor o igual al inicial")
            production = self.production.config()
            folios = self.folios.config()
            self.output_dir = self._next_run_output_dir()
            config = SearchConfig(
                production=production,
                folios=folios,
                output_dir=self.output_dir,
                start_row=start,
                end_row=end,
                export_xlsx=self.export_xlsx.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Configuracion", str(exc))
            return

        self.log.clear()
        self.progress.setValue(0)
        self.status.setText("Procesando")
        self.stats.setText("-")
        for label in self.metric_labels.values():
            label.setText("0")
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.elapsed.restart()
        self.timer.start(1000)

        self.thread = QThread(self)
        self.worker = SearchWorker(config)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_done)
        self.thread.start()

    @Slot()
    def cancel_search(self) -> None:
        if self.worker:
            self.worker.cancel()
        self.cancel_button.setEnabled(False)

    @Slot(int, str)
    def on_progress(self, percent: int, message: str) -> None:
        self.progress.setValue(percent)
        self.status.setText(message)

    @Slot(str)
    def append_log(self, message: str) -> None:
        self.log.appendPlainText(message)

    @Slot(object)
    def on_finished(self, stats: SearchStats) -> None:
        self.timer.stop()
        self.update_elapsed()
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.open_button.setEnabled(True)
        self.status.setText("Finalizado")
        self.metric_labels["processed"].setText(f"{stats.processed_rows:,}")
        self.metric_labels["searched"].setText(f"{stats.searched_folios:,}")
        self.metric_labels["found"].setText(f"{stats.found:,}")
        self.metric_labels["missing"].setText(f"{stats.not_found:,}")
        self.metric_labels["speed"].setText(f"{stats.rows_per_second:,.0f}")
        self.stats.setText(
            f"Tiempo total: {stats.elapsed_seconds:,.2f}s"
        )

    @Slot(str)
    def on_failed(self, message: str) -> None:
        self.timer.stop()
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status.setText("Error")
        self.append_log(message)
        QMessageBox.critical(self, "Error", message)

    @Slot()
    def _thread_done(self) -> None:
        self.worker = None
        self.thread = None

    @Slot()
    def update_elapsed(self) -> None:
        if self.elapsed.isValid():
            seconds = self.elapsed.elapsed() // 1000
            self.elapsed_label.setText(str(timedelta(seconds=seconds)))

    @Slot()
    def open_results(self) -> None:
        if not self.output_dir:
            return
        path = str(self.output_dir)
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename="busca_folios.log",
    )
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
