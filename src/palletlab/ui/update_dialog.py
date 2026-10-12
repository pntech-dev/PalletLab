"""Non-blocking update prompt for installed PalletLab builds."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QProgressBar, QVBoxLayout

from palletlab.update_service import Release, download_verified, fetch_newer_release
from palletlab.version import __version__


class CheckWorker(QThread):
    found = pyqtSignal(object)

    def run(self) -> None:
        try:
            self.found.emit(fetch_newer_release(__version__))
        except Exception:
            self.found.emit(None)


class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, release: Release) -> None:
        super().__init__(); self.release = release

    def run(self) -> None:
        try:
            path = download_verified(self.release, lambda received, total: self.progress.emit(int(received * 100 / total) if total else 0))
            self.done.emit(path)
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    def __init__(self, release: Release, parent=None) -> None:
        super().__init__(parent); self.release = release; self.setWindowTitle("Доступно обновление")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(460)
        self.label = QLabel(f"Доступна версия {release.version}.\n\nУстановить её сейчас?")
        self.label.setWordWrap(True)
        self.progress = QProgressBar(); self.progress.setTextVisible(True); self.progress.hide()
        self.install, self.later = QPushButton("Скачать и установить"), QPushButton("Позже")
        self.install.clicked.connect(self._download); self.later.clicked.connect(self.reject)
        layout = QVBoxLayout(self); layout.addWidget(self.label); layout.addWidget(self.progress)
        buttons = QHBoxLayout(); buttons.addStretch(); buttons.addWidget(self.later); buttons.addWidget(self.install); layout.addLayout(buttons)

    def _download(self) -> None:
        self.install.setEnabled(False); self.later.setEnabled(False); self.progress.show(); self.label.setText("Скачивание обновления…")
        self.worker = DownloadWorker(self.release); self.worker.progress.connect(self.progress.setValue); self.worker.done.connect(self._launch_updater); self.worker.failed.connect(self._failed); self.worker.start()

    def _launch_updater(self, package: Path) -> None:
        executable = Path(sys.executable)
        updater = executable.parent.parent / "Updater" / "PalletLabUpdater.exe"
        if not updater.exists():
            self._failed("Не найден компонент обновления. Установите новую версию через Setup."); return
        subprocess.Popen([str(updater), "--package", str(package), "--app-dir", str(executable.parent), "--pid", str(os.getpid())])
        self.accept()
        if self.parentWidget() is not None:
            self.parentWidget().window().close()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def _failed(self, message: str) -> None:
        self.label.setText("Не удалось загрузить обновление: " + message); self.label.setWordWrap(True); self.install.setEnabled(True); self.later.setEnabled(True)


def check_for_updates(parent) -> CheckWorker | None:
    if not getattr(sys, "frozen", False):
        return None
    worker = CheckWorker()
    worker.found.connect(lambda release: UpdateDialog(release, parent).exec_() if release else None)
    worker.start()
    return worker
