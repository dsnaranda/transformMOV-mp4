import sys
import os
import subprocess
import re

import imageio_ffmpeg as ffmpeg

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QListWidget, QFileDialog, QLabel, QProgressBar,
    QMessageBox
)

from PySide6.QtCore import Qt, QThread, Signal


class DropList(QListWidget):

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):

        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):

        for url in event.mimeData().urls():

            path = url.toLocalFile()

            if path.lower().endswith(".mov"):
                self.addItem(path)


class ConverterThread(QThread):

    file_progress = Signal(int)
    total_progress = Signal(int)
    finished = Signal()

    def __init__(self, files, output_folder):
        super().__init__()

        self.files = files
        self.output_folder = output_folder
        self.ffmpeg_path = ffmpeg.get_ffmpeg_exe()

    def get_duration(self, file):

        cmd = [
            self.ffmpeg_path,
            "-i",
            file
        ]

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

        total_files = len(self.files)

        for index, file in enumerate(self.files):

            duration = self.get_duration(file)

            name = os.path.splitext(os.path.basename(file))[0]
            output = os.path.join(self.output_folder, name + ".mp4")

            cmd = [
                self.ffmpeg_path,
                "-i",
                file,
                "-vcodec",
                "libx264",
                "-acodec",
                "aac",
                "-preset",
                "fast",
                output
            ]

            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True
            )

            for line in process.stderr:

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

                            self.file_progress.emit(percent)

            process.wait()

            total_percent = int(((index + 1) / total_files) * 100)

            self.total_progress.emit(total_percent)

        self.finished.emit()


class Window(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Conversor MOV → MP4")
        self.resize(600, 450)

        layout = QVBoxLayout()

        self.label = QLabel("Arrastra archivos .MOV aquí")
        layout.addWidget(self.label)

        self.list_files = DropList()
        layout.addWidget(self.list_files)

        btn_add = QPushButton("Agregar archivos")
        btn_add.clicked.connect(self.add_files)
        layout.addWidget(btn_add)

        self.file_progress = QProgressBar()
        self.file_progress.setFormat("Progreso archivo: %p%")
        layout.addWidget(self.file_progress)

        self.total_progress = QProgressBar()
        self.total_progress.setFormat("Progreso total: %p%")
        layout.addWidget(self.total_progress)

        btn_convert = QPushButton("Convertir")
        btn_convert.clicked.connect(self.convert)
        layout.addWidget(btn_convert)

        self.setLayout(layout)

    def add_files(self):

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar videos",
            "",
            "Videos (*.mov)"
        )

        for f in files:
            self.list_files.addItem(f)

    def convert(self):

        if self.list_files.count() == 0:

            QMessageBox.warning(
                self,
                "Error",
                "No hay archivos para convertir"
            )

            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta destino"
        )

        if not folder:
            return

        files = []

        for i in range(self.list_files.count()):
            files.append(self.list_files.item(i).text())

        self.thread = ConverterThread(files, folder)

        self.thread.file_progress.connect(self.file_progress.setValue)
        self.thread.total_progress.connect(self.total_progress.setValue)

        self.thread.finished.connect(self.finish_message)

        self.thread.start()

    def finish_message(self):

        QMessageBox.information(
            self,
            "Completado",
            "Todos los videos fueron convertidos"
        )


if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = Window()
    window.show()

    sys.exit(app.exec())