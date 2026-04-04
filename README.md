# lecroy-mcp

MCP server for controlling LeCroy oscilloscopes via SCPI over LAN (VXI-11) or USB.
Tested on a WaveSurfer 3024Z with MAUI firmware.

## Requirements

- [uv](https://docs.astral.sh/uv/) installed
- A LeCroy oscilloscope connected over LAN or USB

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

## Connection options

### Option 1 — Pre-configure the IP address (recommended for LAN)

Set `LECROY_HOST` in the env block and the server auto-connects on startup:

```json
"env": {
  "PYTHONUNBUFFERED": "1",
  "LECROY_HOST": "192.168.1.111"
}
```

### Option 2 — Pre-configure a full resource string (LAN or USB)

Use `LECROY_RESOURCE` for full control, including USB connections:

```json
"env": {
  "PYTHONUNBUFFERED": "1",
  "LECROY_RESOURCE": "USB0::0x05FF::0x1023::12345::INSTR"
}
```

### Option 3 — Manual connection

Leave the env block as-is and connect from within the MCP session:

1. `scope_scan` — auto-detect LeCroy scopes on the local network
2. `scope_list_resources` — list all VISA resources (LAN + USB)
3. `scope_connect("TCPIP0::192.168.1.111::inst0::INSTR")` — connect directly

Optionally set `LECROY_SUBNET` to hint the scan range:

```json
"env": {
  "PYTHONUNBUFFERED": "1",
  "LECROY_SUBNET": "192.168.1.0/24"
}
```

## Usage

Once connected, you have tools for:

- Channel setup (scale, offset, coupling, bandwidth limit)
- Trigger configuration (mode, source, level, edge)
- Timebase and memory depth
- Automated measurements (PKPK, FREQ, RMS, RISE, DUTY, etc.)
- Waveform capture (JSON or CSV)
- Screenshots
- Math functions (FFT, INTG, DIFF, etc.)
- WaveSource built-in generator (WaveSurfer 3000Z and similar)

## Supported models

The server detects the connected model and adjusts commands accordingly.
Profiles are included for:

- WaveSurfer 3000Z / 4000HD
- HDO4000A / HDO6000B / HDO8000A
- WaveRunner 6000 / 8000
- WavePro HD
- MDA800A, SDA

Unknown models fall back to conservative defaults.

## Updating

With `uvx`, use the `@latest` tag to force the newest version:

```bash
uvx lecroy-mcp@latest
```

Or update the `args` in your `.mcp.json` to always pull the latest:

```json
"args": ["lecroy-mcp@latest"]
```

With pip:

```bash
pip install --upgrade lecroy-mcp
```

## Manual installation

If you prefer not to use `uvx`:

```bash
pip install lecroy-mcp
```

Then use `lecroy-mcp` as the command in your MCP config instead of `uvx lecroy-mcp`.

## Notes

- Requires `pyvisa-py` backend — NI-VISA is not supported (breaks screenshot capture)
- All VISA access is serialized via a threading lock; parallel MCP tool calls are safe
