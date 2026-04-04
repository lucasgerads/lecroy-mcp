# lecroy-mcp

MCP server for controlling LeCroy oscilloscopes via SCPI over LAN (VXI-11).
Tested on a WaveSurfer 3024Z with MAUI firmware.

## Requirements

- [uv](https://docs.astral.sh/uv/) installed
- A LeCroy oscilloscope connected over LAN
- The scope's IP address

## MCP configuration

Add to your MCP client config (e.g. Claude Code's `.mcp.json`):

```json
{
  "mcpServers": {
    "lecroy-scope": {
      "type": "stdio",
      "command": "uvx",
      "args": ["lecroy-mcp"],
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

`uvx` will automatically download and run the server — no manual installation needed.

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

## Manual installation

If you prefer not to use `uvx`:

```bash
pip install lecroy-mcp
```

Then use `lecroy-mcp` as the command in your MCP config instead of `uvx lecroy-mcp`.

## Notes

- Requires `pyvisa-py` backend — NI-VISA is not supported (breaks screenshot capture)
- All VISA access is serialized via a threading lock; parallel MCP tool calls are safe
