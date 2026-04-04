# lecroy-mcp

MCP server for controlling LeCroy oscilloscopes via SCPI over LAN (VXI-11).
Tested on a WaveSurfer 3024Z with MAUI firmware.

## Requirements

- Python 3.10+
- A LeCroy oscilloscope connected over LAN
- The scope's IP address

## Installation

```bash
pip install -e .
```

Or without installing:

```bash
pip install -r requirements.txt
```

## MCP configuration

Add to your MCP client config (e.g. Claude Code's `.mcp.json`):

```json
{
  "mcpServers": {
    "lecroy-scope": {
      "type": "stdio",
      "command": "lecroy-mcp",
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

If running without installing, point `command` at `server_stdio.py` directly:

```json
{
  "mcpServers": {
    "lecroy-scope": {
      "type": "stdio",
      "command": "python",
      "args": ["server_stdio.py"],
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

## Usage

Once connected to your MCP client, start with:

1. `scope_list_resources` — find the VISA address of your scope
2. `scope_connect("TCPIP0::192.168.1.x::inst0::INSTR")` — connect
3. `scope_identify` — confirm communication

From there you have tools for channel setup, trigger, timebase, measurements,
waveform capture, screenshots, math functions, and the built-in WaveSource
generator.

## Supported models

The server detects the connected model and adjusts commands accordingly.
Profiles are included for:

- WaveSurfer 3000Z / 4000HD
- HDO4000A / HDO6000B / HDO8000A
- WaveRunner 6000 / 8000
- WavePro HD
- MDA800A, SDA

Unknown models fall back to conservative defaults.

## Notes

- Requires `pyvisa-py` backend — NI-VISA is not supported (breaks screenshot capture)
- All VISA access is serialized via a threading lock; parallel MCP tool calls are safe
