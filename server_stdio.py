"""Stdio entry point — same server, stdio transport.
This is what Claude Code launches via .mcp.json."""
from server import mcp


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
