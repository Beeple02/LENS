"""Entry point for LENS. Runs the TUI app or dispatches CLI commands."""

from __future__ import annotations

import sys


def main() -> None:
    """Main entry point for the `lens` CLI command."""
    from lens.config import ensure_dirs
    from lens.db.store import init_db

    ensure_dirs()
    init_db()

    if len(sys.argv) > 1:
        # Delegate to Typer CLI
        from lens.cli import app
        app()
    else:
        # Launch the TUI
        from lens.app import LensApp
        LensApp().run()


if __name__ == "__main__":
    main()
