import sys


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--step-import":
        from palletlab.importers.step_import_worker import main
        raise SystemExit(main(sys.argv[2]))
    from palletlab.ui.main_window import run
    raise SystemExit(run())
