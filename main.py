import sys
import os
import subprocess
import re
from concurrent.futures import ThreadPoolExecutor

import imageio_ffmpeg as ffmpeg

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QLabel,
    QProgressBar, QMessageBox, QHBoxLayout, QHeaderView,
    QComboBox
)

from PySide6.QtCore import Qt, QThread, Signal


def format_size(path):
    size = os.path.getsize(path) / (1024 * 1024)
    return f"{size:.1f} MB"


class DropTable(QTableWidget):

    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):

        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):

        paths = []

        for url in event.mimeData().urls():
            paths.append(url.toLocalFile())

        self.files_dropped.emit(paths)


class WorkerThread(QThread):

    progress = Signal(int, int)
    status = Signal(str)
    finished = Signal(int)

    def __init__(self, index, file, output_folder, crf):
        super().__init__()

        self.index = index
        self.file = file
        self.output_folder = output_folder
        self.crf = crf

        self.ffmpeg_path = ffmpeg.get_ffmpeg_exe()
        self.process = None
        self.running = True

    def get_duration(self):

        cmd = [self.ffmpeg_path, "-i", self.file]

        process = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True
        )

        duration = None

        for line in process.stderr:

            if "Duration" in line:
                duration = line
                break

        process.kill()

        if duration:

            match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", duration)

            if match:

                h = float(match.group(1))
                m = float(match.group(2))
                s = float(match.group(3))

                return h * 3600 + m * 60 + s

        return 0

    def run(self):

        name = os.path.basename(self.file)

        duration = self.get_duration()

        output = os.path.join(
            self.output_folder,
            os.path.splitext(name)[0] + ".mp4"
        )

        cmd = [
            self.ffmpeg_path,
            "-i", self.file,
            "-vcodec", "libx264",
            "-crf", str(self.crf),
            "-preset", "fast",
            "-acodec", "aac",
            output
        ]

        self.process = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True
        )

        for line in self.process.stderr:

            if not self.running:
                self.process.terminate()
                return

            if "time=" in line:

                match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)

                if match:

                    h = float(match.group(1))
                    m = float(match.group(2))
                    s = float(match.group(3))

                    current = h * 3600 + m * 60 + s

                    if duration > 0:

                        percent = int((current / duration) * 100)

                        if percent > 100:
                            percent = 100

                        self.progress.emit(self.index, percent)

            speed_match = re.search(r"speed=\s*([0-9\.x]+)", line)

            if speed_match:
                self.status.emit(f"{name}  ({speed_match.group(1)})")

        self.process.wait()

        self.progress.emit(self.index, 100)
        self.finished.emit(self.index)

    def stop(self):

        self.running = False


class Window(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Batch Video Converter")
        self.resize(900, 600)

        self.files = {}
        self.workers = []
        self.running = False

        layout = QVBoxLayout()

        label = QLabel("Arrastra archivos o carpetas con videos .MOV")
        layout.addWidget(label)

        self.table = DropTable()
        self.table.setColumnCount(4)

        self.table.setHorizontalHeaderLabels(
            ["Archivo", "Tamaño", "Progreso", "Ruta"]
        )

        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )

        self.table.files_dropped.connect(self.process_paths)

        layout.addWidget(self.table)

        buttons = QHBoxLayout()

        add_btn = QPushButton("Agregar archivos")
        add_btn.clicked.connect(self.add_files)

        remove_btn = QPushButton("Eliminar")
        remove_btn.clicked.connect(self.remove_selected)

        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)

        layout.addLayout(buttons)

        self.quality = QComboBox()
        self.quality.addItems([
            "Alta calidad",
            "Balanceado",
            "Compacto"
        ])

        layout.addWidget(self.quality)

        self.total_progress = QProgressBar()
        layout.addWidget(self.total_progress)

        self.status = QLabel("Esperando archivos")
        layout.addWidget(self.status)

        control_buttons = QHBoxLayout()

        self.convert_btn = QPushButton("Convertir")
        self.convert_btn.clicked.connect(self.convert)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.cancel)

        control_buttons.addWidget(self.convert_btn)
        control_buttons.addWidget(self.cancel_btn)

        layout.addLayout(control_buttons)

        self.setLayout(layout)

    def process_paths(self, paths):

        mov_files = []

        for path in paths:

            if os.path.isfile(path) and path.lower().endswith(".mov"):
                mov_files.append(path)

            elif os.path.isdir(path):

                for root, _, files in os.walk(path):

                    for f in files:

                        if f.lower().endswith(".mov"):
                            mov_files.append(os.path.join(root, f))

        self.add_to_table(mov_files)

    def add_to_table(self, files):

        for file in files:

            if file in self.files:
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(file)))
            self.table.setItem(row, 1, QTableWidgetItem(format_size(file)))
            self.table.setItem(row, 3, QTableWidgetItem(file))

            progress = QProgressBar()
            progress.setValue(0)

            self.table.setCellWidget(row, 2, progress)

            self.files[file] = True

    def add_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar videos",
            "",
            "Videos (*.mov)"
        )

        self.add_to_table(files)

    def remove_selected(self):

        rows = sorted(
            set(index.row() for index in self.table.selectedIndexes()),
            reverse=True
        )

        for row in rows:

            path = self.table.item(row, 3).text()

            if path in self.files:
                del self.files[path]

            self.table.removeRow(row)

    def convert(self):

        if self.running:
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Carpeta destino"
        )

        if not folder:
            return

        quality_map = {
            "Alta calidad": 18,
            "Balanceado": 23,
            "Compacto": 28
        }

        crf = quality_map[self.quality.currentText()]

        self.running = True

        total = self.table.rowCount()

        for row in range(total):

            file = self.table.item(row, 3).text()

            worker = WorkerThread(row, file, folder, crf)

            worker.progress.connect(self.update_progress)
            worker.status.connect(self.status.setText)
            worker.finished.connect(self.file_finished)

            self.workers.append(worker)

            worker.start()

    def update_progress(self, row, percent):

        progress = self.table.cellWidget(row, 2)
        progress.setValue(percent)

        total = 0

        for r in range(self.table.rowCount()):
            total += self.table.cellWidget(r, 2).value()

        total = int(total / self.table.rowCount())

        self.total_progress.setValue(total)

    def file_finished(self, row):

        self.status.setText("Archivo terminado")

    def cancel(self):

        for worker in self.workers:
            worker.stop()

        self.running = False
        self.status.setText("Conversión cancelada")


if __name__ == "__main__":

    app = QApplication(sys.argv)

    app.setStyleSheet("""

    QWidget {
        background-color: #1e1e1e;
        color: white;
    }

    QPushButton {
        background-color: #2d2d2d;
        border: 1px solid #444;
        padding: 6px;
    }

    QPushButton:hover {
        background-color: #3a3a3a;
    }

    QTableWidget {
        background-color: #252526;
    }

    """)

    window = Window()
    window.show()

    sys.exit(app.exec())