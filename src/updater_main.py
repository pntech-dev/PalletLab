"""Small standalone updater that can replace the application's onedir folder."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
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
            deadline = time.monotonic() + 3
            while _running(self.pid) and time.monotonic() < deadline:
                time.sleep(0.2)
            if _running(self.pid):
                self.progress.emit(15, "Закрытие PalletLab…")
                _terminate(self.pid)
                deadline = time.monotonic() + 10
                while _running(self.pid) and time.monotonic() < deadline:
                    time.sleep(0.2)
            if _running(self.pid):
                raise RuntimeError("Не удалось завершить PalletLab. Закройте программу и повторите обновление.")
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
            _replace_application_directory(self.app_dir, backup, extracted)
            shutil.rmtree(backup, ignore_errors=True)
            self.progress.emit(100, "Обновление установлено.")
            self.finished_install.emit(str(self.app_dir / "PalletLab.exe"))
        except Exception as exc:
            self.failed.emit(str(exc))


def _running(pid: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _terminate(pid: int) -> None:
    """Force-close the old application only after its graceful shutdown timed out."""
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(0x0001 | 0x100000, False, pid)
    if not handle:
        raise RuntimeError("Не удалось получить доступ к процессу PalletLab.")
    try:
        if not kernel32.TerminateProcess(handle, 0):
            raise RuntimeError("Не удалось завершить PalletLab.")
    finally:
        kernel32.CloseHandle(handle)


def _kernel32():
    """Return kernel32 with pointer-size-safe signatures for process handles."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _replace_application_directory(app_dir: Path, backup: Path, extracted: Path) -> None:
    """Replace the onedir build, allowing Windows to release files after exit."""
    last_error: OSError | None = None
    for _ in range(25):
        try:
            app_dir.rename(backup)
            try:
                extracted.rename(app_dir)
            except OSError:
                backup.rename(app_dir)
                raise
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.4)
    raise RuntimeError(
        "PalletLab всё ещё использует файлы установки. Закройте программу и повторите обновление."
    ) from last_error


class UpdaterDialog(QDialog):
    def __init__(self, package: Path, app_dir: Path, pid: int) -> None:
        super().__init__()
        self.setWindowTitle("Обновление PalletLab")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(460)
        self.label = QLabel("Подготовка обновления…")
        self.label.setWordWrap(True)
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
        self.label.setText("Не удалось установить обновление: " + message)
        self.label.setWordWrap(True)
        self.close_button.setText("Закрыть")

    def _open(self) -> None:
        subprocess.Popen([self.executable], cwd=str(Path(self.executable).parent)); self.accept()


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--package", required=True); parser.add_argument("--app-dir", required=True); parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    app = QApplication([]); dialog = UpdaterDialog(Path(args.package), Path(args.app_dir), args.pid); dialog.show(); return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
