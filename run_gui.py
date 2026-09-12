"""Entry point for the packaged executable; PyInstaller cannot start a package submodule."""

from pubcardgen.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
