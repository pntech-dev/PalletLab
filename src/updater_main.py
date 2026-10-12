"""Small standalone updater that can replace the application's onedir folder."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QProgressBar, QVBoxLayout


class InstallWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_install = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, package: Path, app_dir: Path, pid: int) -> None:
        super().__init__()
        self.package, self.app_dir, self.pid = package, app_dir, pid

    def run(self) -> None:
        try:
            self.progress.emit(10, "Ожидание завершения PalletLab…")
            while _running(self.pid):
                time.sleep(0.2)
            staging = self.app_dir.with_name(self.app_dir.name + ".new")
            backup = self.app_dir.with_name(self.app_dir.name + ".previous")
            shutil.rmtree(staging, ignore_errors=True)
            self.progress.emit(35, "Распаковка обновления…")
            with zipfile.ZipFile(self.package) as archive:
                archive.extractall(staging)
            extracted = staging / "PalletLab"
            if not extracted.is_dir():
                raise RuntimeError("Архив обновления имеет неверную структуру.")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            self.progress.emit(70, "Установка новой версии…")
            self.app_dir.rename(backup)
            extracted.rename(self.app_dir)
            shutil.rmtree(backup, ignore_errors=True)
            self.progress.emit(100, "Обновление установлено.")
            self.finished_install.emit(str(self.app_dir / "PalletLab.exe"))
        except Exception as exc:
            self.failed.emit(str(exc))


def _running(pid: int) -> bool:
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259
    except Exception:
        return False


class UpdaterDialog(QDialog):
    def __init__(self, package: Path, app_dir: Path, pid: int) -> None:
        super().__init__()
        self.setWindowTitle("Обновление PalletLab")
        self.setMinimumWidth(380)
        self.label = QLabel("Подготовка обновления…")
        self.bar = QProgressBar()
        self.close_button, self.open_button = QPushButton("Закрыть"), QPushButton("Открыть")
        self.open_button.setEnabled(False)
        self.close_button.clicked.connect(self.reject)
        self.open_button.clicked.connect(self._open)
        layout = QVBoxLayout(self); layout.addWidget(self.label); layout.addWidget(self.bar)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(self.close_button); buttons.addWidget(self.open_button); layout.addLayout(buttons)
        self.executable = ""
        self.worker = InstallWorker(package, app_dir, pid)
        self.worker.progress.connect(lambda value, text: (self.bar.setValue(value), self.label.setText(text)))
        self.worker.finished_install.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, executable: str) -> None:
        self.executable = executable; self.open_button.setEnabled(True)

    def _failed(self, message: str) -> None:
        self.label.setText("Не удалось установить обновление: " + message); self.close_button.setText("Закрыть")

    def _open(self) -> None:
        subprocess.Popen([self.executable], cwd=str(Path(self.executable).parent)); self.accept()


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--package", required=True); parser.add_argument("--app-dir", required=True); parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    app = QApplication([]); dialog = UpdaterDialog(Path(args.package), Path(args.app_dir), args.pid); dialog.show(); return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
