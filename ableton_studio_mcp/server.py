"""Command-line entry point.

    ableton-studio-mcp            run the MCP server (stdio)
    ableton-studio-mcp install    put the control surface into Live
    ableton-studio-mcp doctor     check the whole setup
    ableton-studio-mcp --version
"""

from __future__ import annotations

import logging
import sys

from . import __version__


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    command, rest = (args[0], args[1:]) if args else ("", [])
    if command == "install":
        from .install import main as install
        sys.exit(install(rest))
    if command == "doctor":
        from .doctor import main as doctor
        sys.exit(doctor(rest))
    if command in ("-V", "--version"):
        print(f"ableton-studio-mcp {__version__}")
        return
    if command in ("-h", "--help"):
        print(__doc__.strip())
        return

    # stdout carries the MCP protocol: logs go to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from . import tools  # noqa: F401  (registers every tool)
    from .app import mcp
    mcp.run()


if __name__ == "__main__":
    main()
