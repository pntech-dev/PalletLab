"""Small standalone updater that can replace the application's onedir folder."""

from __future__ import annotations

import argparse
import shutil
import stat
import subprocess
import tempfile
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
        staging: Path | None = None
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
            staging = Path(tempfile.mkdtemp(prefix="palletlab-update-", dir=self.app_dir.parent))
            self.progress.emit(35, "Распаковка обновления…")
            with zipfile.ZipFile(self.package) as archive:
                _safe_extract_update(archive, staging)
            extracted = staging / "PalletLab"
            if not extracted.is_dir():
                raise RuntimeError("Архив обновления имеет неверную структуру.")
            self.progress.emit(70, "Установка новой версии…")
            _install_application_files(self.app_dir, extracted)
            self.progress.emit(100, "Обновление установлено.")
            self.finished_install.emit(str(self.app_dir / "PalletLab.exe"))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)


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


def _install_application_files(app_dir: Path, extracted: Path) -> None:
    """Overlay the new build and restore every replaced file after a failure."""
    backup = Path(tempfile.mkdtemp(prefix="palletlab-backup-", dir=app_dir.parent))
    replaced: list[tuple[Path, Path | None]] = []
    try:
        for source in (path for path in extracted.rglob("*") if path.is_file()):
            destination = app_dir / source.relative_to(extracted)
            previous = backup / source.relative_to(extracted) if destination.exists() else None
            if previous is not None:
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, previous)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _replace_file(source, destination)
            replaced.append((destination, previous))
    except Exception:
        for destination, previous in reversed(replaced):
            if previous is None:
                destination.unlink(missing_ok=True)
            else:
                shutil.copy2(previous, destination)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def _safe_extract_update(archive: zipfile.ZipFile, destination: Path) -> None:
    """Extract only regular files under the expected update root."""
    root = destination.resolve()
    for item in archive.infolist():
        relative = Path(item.filename)
        target = (root / relative).resolve()
        is_link = stat.S_ISLNK(item.external_attr >> 16)
        if (is_link or relative.is_absolute() or ".." in relative.parts
                or (root not in target.parents and target != root)):
            raise RuntimeError("Архив обновления содержит недопустимый путь или ссылку.")
        if not relative.parts or relative.parts[0] not in {"PalletLab", "PalletLabUpdater"}:
            raise RuntimeError("Архив обновления имеет неверную структуру.")
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def _replace_file(source: Path, destination: Path) -> None:
    """Copy one file after Windows releases its final handle."""
    last_error: OSError | None = None
    for _ in range(75):
        try:
            shutil.copy2(source, destination)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.4)
    raise RuntimeError(f"Не удалось заменить файл {destination.name}.") from last_error


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
