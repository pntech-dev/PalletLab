import sys


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--step-import":
        from palletlab.importers.step_import_worker import main
        raise SystemExit(main(sys.argv[2]))
    if len(sys.argv) == 2 and sys.argv[1] == "--smoke-test":
        # Used by the release workflow to verify the frozen executable can
        # import the full 3D viewport before publishing it.
        import importlib
        import traceback
        from pathlib import Path

        report_path = Path("palletlab-smoke-test-error.log")
        try:
            report_path.write_text(
                "Reached PalletLab smoke-test entry point.\n", encoding="utf-8"
            )
            importlib.import_module("palletlab.visualization.pallet_view")
        except BaseException:
            report_path.write_text(
                report_path.read_text(encoding="utf-8") + traceback.format_exc(),
                encoding="utf-8",
            )
            raise
        raise SystemExit(0)
    from palletlab.ui.main_window import run
    raise SystemExit(run())
