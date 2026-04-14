"""
LeCroy oscilloscope MCP server — full implementation.

HTTP entry point (for mcp dev inspector):
    python server.py

Stdio entry point (for Claude Code):
    python server_stdio.py

Transport convention
--------------------
Every tool docstring ends with a Transport line so callers know the
underlying mechanism and can reason about reliability and ordering:

  Transport: SCPI          — direct IEEE 488.2 / SCPI command
  Transport: SCPI (binary) — SCPI with binary block data transfer
  Transport: VBS           — VBS automation (app.* object hierarchy)
  Transport: local         — no instrument communication (client-side only)

Prefer SCPI tools for anything time-critical or high-frequency.
Use VBS tools for features that have no SCPI equivalent (e.g. WaveSource).
scope_query / scope_write are SCPI-only escape hatches — do not use them
to send raw VBS strings; use the dedicated scope_wavesource_* tools instead.
"""

import csv
import json
import os
import sys
import threading
from datetime import datetime
from importlib.metadata import version as _pkg_version, PackageNotFoundError

try:
    _SERVER_VERSION = _pkg_version("lecroy-mcp")
except PackageNotFoundError:
    _SERVER_VERSION = "unknown"

from mcp.server.fastmcp import FastMCP
from oscilloscope import LeCroyScope, InstrumentError
import docs as _docs

mcp = FastMCP("lecroy-scope")

# Optional env vars for auto-connect and scan hint (set in .mcp.json env block)
_HOST     = os.environ.get("LECROY_HOST")      # e.g. "192.168.1.111"
_RESOURCE = os.environ.get("LECROY_RESOURCE")  # e.g. "USB0::0x05FF::0x1023::12345::INSTR"
_SUBNET   = os.environ.get("LECROY_SUBNET")    # e.g. "192.168.1.0/24"

# Probe configuration — keyed by channel number 1–4.
#   dict  {"ratio": float, "unit": str} — probe is connected, ATTN applied at connect
#   None  — engineer explicitly marked channel as not connected (LECROY_PROBE_Cn=none)
#   missing key — engineer left it unspecified
#
# Format: LECROY_PROBE_C1=10        (10× voltage probe)
#         LECROY_PROBE_C2=1         (1× voltage probe)
#         LECROY_PROBE_C3=none      (nothing connected)
#         LECROY_PROBE_C4=0.1,A     (current probe, 100 mV/A — future)
def _parse_probe_env(val: str) -> "dict | None":
    if val.strip().lower() == "none":
        return None
    parts = val.split(",")
    ratio = float(parts[0].strip())
    unit  = parts[1].strip() if len(parts) > 1 else "V"
    return {"ratio": ratio, "unit": unit}

_PROBES: "dict[int, dict | None]" = {}
for _ch_n in (1, 2, 3, 4):
    _env_val = os.environ.get(f"LECROY_PROBE_C{_ch_n}")
    if _env_val is not None:
        _PROBES[_ch_n] = _parse_probe_env(_env_val)

# Module-level singleton — one persistent VISA connection per server process.
_scope = LeCroyScope()

# Serializes all VISA access across threads.
# FastMCP runs sync tools in a thread executor, so parallel MCP calls become
# parallel threads sharing the same VISA connection. Without this lock, a
# binary waveform/screenshot transfer can interleave with a text query and
# corrupt both responses (or crash the server process entirely).
_visa_lock = threading.Lock()


def _apply_probe_config() -> None:
    """Send ATTN (and UNIT for non-voltage probes) to the scope for every configured channel.

    Called once after connect — either auto-connect at startup or manual scope_connect.
    Channels marked 'none' are skipped (no signal present, nothing to configure).
    """
    for ch_n, probe in _PROBES.items():
        if probe is None:
            continue
        try:
            _scope.set_attenuation(ch_n, probe["ratio"])
            if probe.get("unit", "V") != "V":
                _scope.set_unit(ch_n, probe["unit"])
            print(f"Probe C{ch_n}: ratio={probe['ratio']}, unit={probe.get('unit','V')}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"Probe config C{ch_n} failed: {e}", file=sys.stderr, flush=True)


def _probe_warning(channel: int) -> str:
    """Return a warning string if the channel is explicitly marked as not connected, else ''."""
    if _PROBES.get(channel) is None and channel in _PROBES:
        return f"WARNING: C{channel} is marked as not connected (LECROY_PROBE_C{channel}=none) — data may be noise.\n"
    return ""


# Auto-connect if a host or resource string was provided via environment.
if _RESOURCE:
    try:
        _scope.connect(_RESOURCE)
        print(f"Auto-connected to {_RESOURCE}", file=sys.stderr, flush=True)
        _apply_probe_config()
    except Exception as e:
        print(f"Auto-connect failed ({_RESOURCE}): {e}", file=sys.stderr, flush=True)
elif _HOST:
    try:
        _scope.connect(f"TCPIP0::{_HOST}::inst0::INSTR")
        print(f"Auto-connected to {_HOST}", file=sys.stderr, flush=True)
        _apply_probe_config()
    except Exception as e:
        print(f"Auto-connect failed ({_HOST}): {e}", file=sys.stderr, flush=True)


def _run(fn):
    """Execute fn() under the VISA lock, catch errors, return a string Claude can read."""
    with _visa_lock:
        try:
            result = fn()
            return str(result) if result is not None else "OK"
        except InstrumentError as e:
            return f"ERROR: {e}"
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as e:
            # Catch asyncio.CancelledError and any other non-fatal BaseException
            # so they don't propagate out and kill the server process.
            print(f"_run caught {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            return f"ERROR ({type(e).__name__}): {e}"


# =============================================================================
# Documentation resources  (browsable reference material)
# =============================================================================

@mcp.resource("lecroy://docs/index")
def _res_index() -> str:
    """Index of all LeCroy SCPI documentation topics."""
    return _docs.help_index()

@mcp.resource("lecroy://docs/overview")
def _res_overview() -> str:
    """LeCroy SCPI overview: communication, syntax, headers, binary data format."""
    return _docs.get_topic("overview")

@mcp.resource("lecroy://docs/channel")
def _res_channel() -> str:
    """Channel commands: VDIV, OFST, CPL/COUP, BWL, ATTN, TRA, INVS, UNIT."""
    return _docs.get_topic("channel")

@mcp.resource("lecroy://docs/timebase")
def _res_timebase() -> str:
    """Timebase commands: TDIV, TRDL, MSIZ, ILVD, SEQ."""
    return _docs.get_topic("timebase")

@mcp.resource("lecroy://docs/trigger")
def _res_trigger() -> str:
    """Trigger commands: TRMD, TRLV, TRSL, TRCP, TRSE, FRTR and advanced types."""
    return _docs.get_topic("trigger")

@mcp.resource("lecroy://docs/acquisition")
def _res_acquisition() -> str:
    """Acquisition control: ARM, STOP, WAIT, INR?, single-shot sequence."""
    return _docs.get_topic("acquisition")

@mcp.resource("lecroy://docs/measurement")
def _res_measurement() -> str:
    """Automated measurements: PAVA, PACU, full parameter list, state codes."""
    return _docs.get_topic("measurement")

@mcp.resource("lecroy://docs/waveform")
def _res_waveform() -> str:
    """Waveform transfer: COMM_FORMAT, COMM_ORDER, WF?, WFSU, INSPECT?, WAVEDESC scaling."""
    return _docs.get_topic("waveform")

@mcp.resource("lecroy://docs/math")
def _res_math() -> str:
    """Math functions: equations, FFT, INTG, DIFF, AVGS, ERES."""
    return _docs.get_topic("math")

@mcp.resource("lecroy://docs/cursor")
def _res_cursor() -> str:
    """Cursor commands: CRS, CRST, CRVA, CRMS."""
    return _docs.get_topic("cursor")

@mcp.resource("lecroy://docs/screenshot")
def _res_screenshot() -> str:
    """Screenshot commands: HCSU setup, SCDP capture, IEEE 488.2 header stripping."""
    return _docs.get_topic("screenshot")

@mcp.resource("lecroy://docs/system")
def _res_system() -> str:
    """System commands: *IDN?, *RST, *CAL?, BUZZ, DATE, panel lock, setup save/recall."""
    return _docs.get_topic("system")

@mcp.resource("lecroy://docs/wavesource")
def _res_wavesource() -> str:
    """WaveSource generator: VBS properties, shapes, frequency, amplitude, load."""
    return _docs.get_topic("wavesource")


@mcp.tool()
def scope_help(topic: str = "") -> str:
    """Look up LeCroy SCPI documentation by topic.

    Call with no argument (or topic="") to see the list of available topics.

    Args:
        topic: One of: overview, channel, timebase, trigger, acquisition,
               measurement, waveform, math, cursor, screenshot, system.
               Leave empty to list all topics.

    Transport: local
    """
    if not topic:
        return _docs.help_index()
    content = _docs.get_topic(topic)
    if content is None:
        return (
            f"Unknown topic: '{topic}'\n\n"
            + _docs.help_index()
        )
    return content


# =============================================================================
# Connection
# =============================================================================

@mcp.tool()
def scope_list_resources() -> str:
    """List all VISA instrument resources visible on this computer (LAN and USB).

    Use this to find the resource string for scope_connect.
    A LAN-connected LeCroy typically appears as:
        TCPIP0::192.168.1.111::inst0::INSTR
    A USB-connected LeCroy typically appears as:
        USB0::0x05FF::0x1023::<serial>::INSTR

    If nothing appears, try scope_scan to search the network directly.

    Transport: local
    """
    try:
        resources = LeCroyScope.list_resources()
        if not resources:
            return (
                "No VISA resources found. Check the oscilloscope is powered on and connected.\n"
                "Try scope_scan to search the network, or connect directly:\n"
                "  scope_connect('TCPIP0::192.168.1.111::inst0::INSTR')"
            )
        return "\n".join(resources)
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def scope_scan(subnet: str = "") -> str:
    """Scan the network for LeCroy oscilloscopes.

    More reliable than scope_list_resources for LAN-connected scopes —
    probes each host directly rather than relying on broadcast discovery.

    Scans all hosts in the subnet for port 111 (VXI-11 portmapper) in
    parallel, then queries *IDN? on responsive hosts and filters for LeCroy
    instruments.

    Args:
        subnet: CIDR subnet to scan, e.g. '192.168.1.0/24'.
                Defaults to LECROY_SUBNET env var if set, otherwise
                auto-detected from the local network interface.

    Transport: local (TCP socket probe + SCPI *IDN? per candidate)
    """
    import socket
    import ipaddress
    from concurrent.futures import ThreadPoolExecutor, as_completed

    effective_subnet = subnet or _SUBNET

    if effective_subnet:
        subnets_to_scan = [effective_subnet]
    else:
        # Auto-detect: collect all active IPv4 interfaces and derive /24 subnets
        subnets_to_scan = []
        try:
            import psutil  # optional — fall back gracefully if not installed
            for addrs in psutil.net_if_addrs().values():
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        net = ipaddress.ip_network(addr.address + "/24", strict=False)
                        subnets_to_scan.append(str(net))
        except ImportError:
            pass

        if not subnets_to_scan:
            # Fallback: use default-route interface only
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                subnets_to_scan = [str(ipaddress.ip_network(local_ip + "/24", strict=False))]
            except Exception as e:
                return f"ERROR: Could not determine local subnet: {e}\nProvide a subnet explicitly, e.g. scope_scan('192.168.1.0/24')"

    # Scan all subnets in parallel
    all_results = []
    seen = set()
    with ThreadPoolExecutor(max_workers=len(subnets_to_scan)) as ex:
        futures = {ex.submit(LeCroyScope.scan_network, s): s for s in subnets_to_scan}
        for f in as_completed(futures):
            try:
                for resource, idn in f.result():
                    if resource not in seen:
                        seen.add(resource)
                        all_results.append((resource, idn))
            except Exception:
                pass

    scanned = ", ".join(subnets_to_scan)

    if not all_results:
        return f"No LeCroy oscilloscopes found (scanned: {scanned})."

    lines = [f"Found {len(all_results)} LeCroy instrument(s) (scanned: {scanned}):"]
    for resource, idn in all_results:
        lines.append(f"  {resource}")
        lines.append(f"    {idn}")
    lines.append("\nUse scope_connect('<resource string>') to connect.")
    return "\n".join(lines)


@mcp.tool()
def scope_connect(resource_string: str) -> str:
    """Connect to the LeCroy oscilloscope at the given VISA resource address.

    Args:
        resource_string: VISA address, e.g. 'TCPIP0::192.168.1.111::inst0::INSTR'

    Returns the IDN string on success.

    Transport: local (opens VISA session, then queries *IDN? via SCPI)
    """
    def _connect():
        result = _scope.connect(resource_string)
        _apply_probe_config()
        return result
    return _run(_connect)


@mcp.tool()
def scope_disconnect() -> str:
    """Disconnect from the oscilloscope. Safe to call even if not connected.

    Transport: local
    """
    _scope.disconnect()
    return "Disconnected."


@mcp.tool()
def scope_connection_status() -> str:
    """Check whether the server has an active VISA connection and identify the scope.

    Transport: local (connection check) + SCPI (*IDN? if connected)
    """
    if not _scope.is_connected:
        return (
            "Not connected.\n"
            "1. Call scope_list_resources to discover instruments.\n"
            "2. Call scope_connect with the resource string."
        )
    def _status():
        lines = [
            f"Connected: {_scope._resource_string}",
            f"IDN: {_scope.identify()}",
            f"lecroy-mcp version: {_SERVER_VERSION}",
        ]
        if _PROBES:
            lines.append("Probe config:")
            for ch_n in (1, 2, 3, 4):
                if ch_n not in _PROBES:
                    continue
                probe = _PROBES[ch_n]
                if probe is None:
                    lines.append(f"  C{ch_n}: not connected")
                else:
                    unit = probe.get("unit", "V")
                    lines.append(f"  C{ch_n}: {probe['ratio']}× probe ({unit})")
        return "\n".join(lines)
    return _run(_status)


@mcp.tool()
def scope_capabilities() -> str:
    """Return the detected model profile for the connected oscilloscope.

    Shows family name, channel count, bandwidth, ADC resolution, supported
    coupling values, bandwidth-limit values, memory depth, math channels,
    and which optional features (invert, unit, SARA) are available.

    Connect with scope_connect first; the profile is detected from *IDN?.

    Transport: local (reads cached profile set during scope_connect)
    """
    if not _scope.is_connected:
        return "Not connected. Call scope_connect first."
    return _run(lambda: json.dumps(_scope.get_capabilities(), indent=2))


# =============================================================================
# Raw SCPI access
# =============================================================================

@mcp.tool()
def scope_query(command: str) -> str:
    """Send any SCPI query command and return the response.

    Escape hatch for SCPI commands not covered by dedicated tools.
    Use dedicated tools whenever one exists — they handle edge cases,
    model differences, and response parsing correctly.
    Do NOT use this to send raw VBS strings; use scope_wavesource_*
    and other VBS-backed tool groups instead.

    Args:
        command: SCPI query string, e.g. 'C1:VDIV?' or 'TRMD?'

    Transport: SCPI
    """
    return _run(lambda: _scope.query(command))


@mcp.tool()
def scope_write(command: str) -> str:
    """Send any SCPI write command (no response expected).

    Escape hatch for SCPI commands not covered by dedicated tools.
    Use dedicated tools whenever one exists — they handle edge cases,
    model differences, and response parsing correctly.
    Do NOT use this to send raw VBS strings; use scope_wavesource_*
    and other VBS-backed tool groups instead.

    Args:
        command: SCPI command string, e.g. 'C1:VDIV 0.5' or 'TRIG_MODE AUTO'

    Transport: SCPI
    """
    return _run(lambda: _scope.write(command))


# =============================================================================
# System
# =============================================================================

@mcp.tool()
def scope_identify() -> str:
    """Query the oscilloscope identification string (*IDN?).

    Returns make, model, serial number, and firmware version.

    Transport: SCPI
    """
    return _run(_scope.identify)


@mcp.tool()
def scope_reset() -> str:
    """Reset the oscilloscope to factory defaults (*RST).

    WARNING: This clears all waveforms, measurements and settings.

    Transport: SCPI
    """
    return _run(_scope.reset)


@mcp.tool()
def scope_auto_setup() -> str:
    """Run AUTO_SETUP to automatically scale vertical, horizontal and trigger.

    The scope will adjust all settings to best display the connected signals.

    Transport: SCPI
    """
    return _run(_scope.auto_setup)


@mcp.tool()
def scope_calibrate() -> str:
    """Run self-calibration (*CAL?) and return the result status.

    Transport: SCPI
    """
    return _run(_scope.calibrate)


@mcp.tool()
def scope_get_date() -> str:
    """Query the oscilloscope internal date and time.

    Transport: SCPI
    """
    return _run(_scope.get_date)


@mcp.tool()
def scope_beep() -> str:
    """Trigger the oscilloscope audible beeper. Useful for confirming operations.

    Transport: SCPI
    """
    return _run(_scope.beep)


@mcp.tool()
def scope_set_panel_lock(locked: bool) -> str:
    """Lock or unlock the oscilloscope front-panel controls.

    Args:
        locked: True to lock (prevent accidental adjustment), False to unlock.

    Transport: SCPI
    """
    return _run(lambda: _scope.set_panel_lock(locked))


# =============================================================================
# Channel configuration
# =============================================================================

@mcp.tool()
def scope_channel_info(channel: int) -> str:
    """Get all current settings for a channel in one call.

    Returns vertical scale, offset, coupling, bandwidth limit, invert,
    trace visibility, unit, and configured probe (from LECROY_PROBE_Cn env var).

    Args:
        channel: Channel number 1–4

    Transport: SCPI
    """
    def _fmt():
        info = _scope.get_channel_info(channel)
        lines = [f"Channel {channel} settings:"]
        for k, v in info.items():
            lines.append(f"  {k:14s}: {v}")
        if channel in _PROBES:
            probe = _PROBES[channel]
            if probe is None:
                lines.append(f"  configured probe: not connected")
            else:
                unit = probe.get("unit", "V")
                lines.append(f"  configured probe: {probe['ratio']}× ({unit})")
        return _probe_warning(channel) + "\n".join(lines)
    return _run(_fmt)


@mcp.tool()
def scope_configure_channel(
    channel: int,
    vdiv: float = None,
    offset: float = None,
    coupling: str = None,
    bwlimit: str = None,
    invert: bool = None,
    trace: bool = None,
    unit: str = None,
) -> str:
    """Configure one or more settings for a channel in a single call.

    All parameters except channel are optional — only the provided ones are applied.

    Probe attenuation (ATTN) is set automatically from the LECROY_PROBE_Cn
    environment variable at connect time and cannot be changed here — it
    reflects the physical probe and is the engineer's responsibility.

    Args:
        channel:  Channel number 1–4
        vdiv:     Vertical scale in V/div, e.g. 0.1 = 100 mV/div, 1.0 = 1 V/div
        offset:   Vertical offset in volts (positive shifts trace down)
        coupling: D1M (DC 1MΩ), D50 (DC 50Ω), A1M (AC 1MΩ), or GND
        bwlimit:  Bandwidth limit: OFF (full BW), 20MHZ, 200MHZ.
                  High-BW models also support 500MHZ, 1GHZ, etc.
                  Use scope_capabilities to see valid values for the connected scope.
        invert:   True to invert the signal polarity, False for normal
        trace:    True to show the channel trace, False to hide it
        unit:     Vertical unit: V (volts), A (amperes), W (watts), U (user)

    Transport: SCPI
    """
    def _apply():
        applied = []
        if vdiv     is not None: _scope.set_vdiv(channel, vdiv);         applied.append(f"vdiv={vdiv}")
        if offset   is not None: _scope.set_offset(channel, offset);     applied.append(f"offset={offset}")
        if coupling is not None: _scope.set_coupling(channel, coupling);  applied.append(f"coupling={coupling}")
        if bwlimit  is not None: _scope.set_bwlimit(channel, bwlimit);   applied.append(f"bwlimit={bwlimit}")
        if invert   is not None: _scope.set_invert(channel, invert);     applied.append(f"invert={invert}")
        if trace    is not None: _scope.set_trace(channel, trace);       applied.append(f"trace={trace}")
        if unit     is not None: _scope.set_unit(channel, unit);         applied.append(f"unit={unit}")
        if not applied:
            return "No parameters specified — nothing changed."
        return _probe_warning(channel) + f"C{channel}: " + ", ".join(applied)
    return _run(_apply)


# =============================================================================
# Timebase
# =============================================================================

@mcp.tool()
def scope_timebase_info() -> str:
    """Get all current timebase settings in one call.

    Returns time/div, trigger delay, sample rate, and memory size.

    Transport: SCPI
    """
    def _fmt():
        info = _scope.get_timebase_info()
        lines = ["Timebase settings:"]
        for k, v in info.items():
            lines.append(f"  {k:14s}: {v}")
        return "\n".join(lines)
    return _run(_fmt)


@mcp.tool()
def scope_set_tdiv(seconds_per_div: float) -> str:
    """Set the time base (time per division).

    Args:
        seconds_per_div: Time/div in seconds.
            Examples: 1e-9 (1 ns), 1e-6 (1 µs), 1e-3 (1 ms), 1.0 (1 s)

    Transport: SCPI
    """
    return _run(lambda: _scope.set_tdiv(seconds_per_div))


@mcp.tool()
def scope_set_trigger_delay(seconds: float) -> str:
    """Set the trigger delay (horizontal position offset).

    Args:
        seconds: Delay in seconds. Positive = trigger point moves left,
                 negative = trigger point moves right.

    Transport: SCPI
    """
    return _run(lambda: _scope.set_trigger_delay(seconds))


@mcp.tool()
def scope_set_memory_size(size: str) -> str:
    """Set the acquisition memory depth (record length).

    Args:
        size: Memory depth — one of: 500, 1K, 10K, 25K, 50K, 100K, 250K,
              500K, 1M, 2.5M, 5M, 10M, 25M.  Available sizes are model-dependent;
              WaveSurfer 3000Z maximum is 10M.  Larger = more detail, slower transfer.

    Transport: SCPI
    """
    return _run(lambda: _scope.set_memory_size(size))


# =============================================================================
# Trigger
# =============================================================================

@mcp.tool()
def scope_trigger_info() -> str:
    """Get all current trigger settings in one call.

    Returns trigger mode, source/type configuration, and level per channel.

    Transport: SCPI
    """
    def _fmt():
        info = _scope.get_trigger_info()
        lines = ["Trigger settings:"]
        for k, v in info.items():
            lines.append(f"  {k:20s}: {v}")
        return "\n".join(lines)
    return _run(_fmt)


@mcp.tool()
def scope_configure_trigger(
    mode: str = None,
    source: str = None,
    slope: str = None,
    level: float = None,
) -> str:
    """Configure trigger mode, source, slope, and/or level in a single call.

    All parameters are optional — only the provided ones are applied.
    For complex trigger types (pulse width, window, TV, etc.) use scope_write.

    If level is provided without source, it is applied to C1. To set the level
    on a different channel, always pass source together with level.

    Args:
        mode:   Trigger mode: AUTO (free-running), NORM (wait for trigger),
                SINGLE (one capture then stop), STOP (stop acquisition)
        source: Trigger source: C1, C2, C3, C4, EX, EX5, or LINE
        slope:  Edge slope: POS (rising), NEG (falling), or EITHER
        level:  Trigger threshold in volts

    Transport: SCPI
    """
    import re as _re
    def _apply():
        applied = []
        if mode is not None:
            _scope.set_trigger_mode(mode)
            applied.append(f"mode={mode}")
        if source is not None:
            _scope.set_trigger_source(source, slope or "POS")
            applied.append(f"source={source}" + (f" slope={slope}" if slope else ""))
        if level is not None:
            # Derive channel from source if it's C1–C4, else default to C1
            ch_num = 1
            if source is not None:
                m = _re.match(r"[Cc](\d+)", source)
                if m:
                    ch_num = int(m.group(1))
            _scope.set_trigger_level(ch_num, level)
            applied.append(f"level={level}V on C{ch_num}")
        if not applied:
            return "No parameters specified — nothing changed."
        return "Trigger: " + ", ".join(applied)
    return _run(_apply)


@mcp.tool()
def scope_force_trigger() -> str:
    """Force an immediate trigger event (FRTR).

    Useful when in NORM mode and the signal hasn't triggered yet.

    Transport: SCPI
    """
    return _run(_scope.force_trigger)


# =============================================================================
# Acquisition control
# =============================================================================

@mcp.tool()
def scope_arm() -> str:
    """Arm the trigger (ARM). Start waiting for a trigger event.

    Use scope_get_acquisition_status to poll for completion.

    Transport: SCPI
    """
    return _run(_scope.arm)


@mcp.tool()
def scope_stop() -> str:
    """Stop acquisition immediately (STOP).

    Transport: SCPI
    """
    return _run(_scope.stop)


@mcp.tool()
def scope_get_acquisition_status() -> str:
    """Query the current acquisition and trigger state.

    Returns the trigger mode (TRMD?) and internal state register (INR?).
    INR bit 0 set (value & 1 == 1) means a new waveform was acquired since
    the last INR read.  Note: SAMPLE_STATUS? is not supported on WS3000Z.

    Transport: SCPI
    """
    return _run(_scope.get_acquisition_status)


# =============================================================================
# Measurements (PAVA)
# =============================================================================

@mcp.tool()
def scope_setup_measurements(channel: int, params: list[str] | None = None) -> str:
    """Configure the scope's measurement panel (P1–P6) for a channel.

    PAVA measurements only return valid values for parameters that are active
    in one of the six display slots. Call this once after connecting to a
    channel with a new signal. The scope_measure and scope_measure_all tools
    will also auto-configure if they detect an invalid result, but calling
    this explicitly sets up the display panel for that channel.

    Args:
        channel: Channel number 1–4
        params:  List of up to 6 parameter names to show in the panel.
                 Defaults to ['PKPK', 'FREQ', 'MEAN', 'RMS', 'RISE', 'DUTY'].
                 Valid names: MEAN MAX MIN PKPK FREQ PERIOD RMS RISE FALL
                              WIDTH DUTY BASE TOP AMPL OVSP UNDSP PHASE DELAY AREA

    Transport: SCPI (PACU)
    """
    def _setup():
        _scope.setup_measurements(channel, params)
        active = params or ["PKPK", "FREQ", "MEAN", "RMS", "RISE", "DUTY"]
        return f"Measurement panel configured for C{channel}: {', '.join(active[:6])}"
    return _run(_setup)


@mcp.tool()
def scope_measure(channel: int, param: str) -> str:
    """Get a single automated measurement from a channel.

    Args:
        channel: Channel number 1–4
        param:   One of:
                   MEAN   — mean (average) voltage
                   MAX    — maximum voltage
                   MIN    — minimum voltage
                   PKPK   — peak-to-peak voltage
                   FREQ   — frequency
                   PERIOD — period
                   RMS    — RMS voltage
                   RISE   — rise time (10%–90%)
                   FALL   — fall time (90%–10%)
                   WIDTH  — pulse width (positive)
                   DUTY   — duty cycle
                   BASE   — base voltage level
                   TOP    — top voltage level
                   AMPL   — amplitude (top – base)
                   OVSP   — overshoot (positive)
                   UNDSP  — undershoot
                   PHASE  — phase difference
                   DELAY  — delay
                   AREA   — area under curve

    Returns the value with units as reported by the oscilloscope.

    Transport: SCPI (PAVA)
    """
    return _run(lambda: _scope.measure(channel, param))


@mcp.tool()
def scope_measure_all(channel: int) -> str:
    """Get all automated measurements for a channel in one call.

    Queries MEAN, MAX, MIN, PKPK, FREQ, PERIOD, RMS, RISE, FALL,
    WIDTH, DUTY, BASE, TOP, AMPL, OVSP, UNDSP, PHASE, DELAY, AREA.

    Args:
        channel: Channel number 1–4

    Transport: SCPI (PAVA)
    """
    def _fmt():
        results = _scope.measure_all(channel)
        lines = [f"Channel {channel} measurements:"]
        for k, v in sorted(results.items()):
            lines.append(f"  {k:8s}: {v}")
        return "\n".join(lines)
    return _run(_fmt)


# =============================================================================
# Math functions
# =============================================================================

@mcp.tool()
def scope_set_math(func: int, equation: str) -> str:
    """Define a math waveform function.

    Available operators (all MAUI scopes):

      Arithmetic:
        ABS(C1)            absolute value
        INVERT(-C1)        negation
        SQR(C1)            square
        SQRT(C1)           square root
        RECIPROCAL(C1)     1/x
        RESC(C1)           rescale (scale + offset + change units)
        C1+C2              sum of two channels
        C1-C2              difference
        C1*C2              product
        C1/C2              ratio

      Signal processing:
        FFT(C1)            Fast Fourier Transform — use TYPE parameter to select
                           POWERSPECTRUM (dBm), MAGNITUDE, PHASE, REAL, IMAGINARY.
                           WINDOW options: VONHANN, HAMMING, FLATTOP,
                           BLACKMANHARRIS, RECTANGULAR.
                           Example: EQN,"FFT(C1)",TYPE,POWERSPECTRUM,WINDOW,VONHANN
        INTG(C1)           integral
        DERI(C1)           derivative (adjacent-sample subtraction)
        AVG(C1)            averaging — add AVERAGETYPE,SUMMED or CONTINUOUS
        ERES(C1)           enhanced resolution (smoothing, 0.5–3 extra bits)

      Envelope / extrema:
        FLOOR(C1)          minimum value at each X over N sweeps
        ROOF(C1)           maximum value at each X over N sweeps

      Parameter-based (use a measurement parameter Pn as source):
        TREND(P1)          trend plot of parameter values over time
        HIST(P1)           histogram of parameter values

      Display only:
        ZOOMONLY(C1)       zoom display without computation

    After setting an FFT, use scope_set_math_zoom to zoom the frequency axis.

    Args:
        func:     Math function number 1–4
        equation: Math expression string, e.g. 'FFT(C1)' or 'C1+C2'

    Transport: SCPI
    """
    return _run(lambda: _scope.set_math(func, equation))


@mcp.tool()
def scope_set_math_trace(func: int, visible: bool) -> str:
    """Show or hide a math function trace.

    Args:
        func:    Math function number 1–4
        visible: True to show, False to hide

    Transport: SCPI
    """
    return _run(lambda: _scope.set_math_trace(func, visible))


@mcp.tool()
def scope_math_info(func: int) -> str:
    """Get the definition and display state of a math function.

    Args:
        func: Math function number 1–4

    Transport: SCPI
    """
    def _fmt():
        info = _scope.get_math_info(func)
        lines = [f"Math F{func}:"]
        for k, v in info.items():
            lines.append(f"  {k:12s}: {v}")
        return "\n".join(lines)
    return _run(_fmt)


@mcp.tool()
def scope_set_math_zoom(func: int, center: float, per_div: float) -> str:
    """Set the horizontal display zoom for a math trace.

    Useful for zooming into a specific frequency range on an FFT trace without
    changing the FFT computation itself.

    Units depend on the math function type:
      - FFT traces: Hz (e.g. center=1250, per_div=250 shows 0–2500 Hz on 10 divs)
      - Time-domain math traces: seconds

    Args:
        func:    Math function number 1–4
        center:  Center value (Hz for FFT, seconds for time-domain math)
        per_div: Scale per division

    Transport: VBS (app.Math.Fn.Zoom.HorCenter, app.Math.Fn.Zoom.HorScale)
    """
    return _run(lambda: _scope.set_math_zoom(func, center, per_div))


@mcp.tool()
def scope_math_zoom_info(func: int) -> str:
    """Read the current horizontal zoom settings for a math trace.

    Args:
        func: Math function number 1–4

    Transport: VBS (app.Math.Fn.Zoom.HorCenter, app.Math.Fn.Zoom.HorScale)
    """
    def _fmt():
        z = _scope.get_math_zoom(func)
        return f"Math F{func} zoom:\n  center : {z['center']}\n  per_div: {z['per_div']}"
    return _run(_fmt)


# =============================================================================
# Memory / Reference waveforms
# =============================================================================

@mcp.tool()
def scope_store_waveform(source: str, slot: int) -> str:
    """Store a waveform to internal memory.

    Args:
        source: Waveform to store — 'C1', 'C2', 'C3', 'C4', 'F1'–'F4'
        slot:   Memory slot 1–4

    Transport: SCPI
    """
    return _run(lambda: _scope.store_waveform(source, slot))


@mcp.tool()
def scope_recall_waveform(slot: int, dest: str) -> str:
    """Recall a waveform from internal memory.

    Args:
        slot: Memory slot 1–4 to recall from
        dest: Destination, e.g. 'C1' (overlays the recalled waveform on C1)

    Transport: SCPI
    """
    return _run(lambda: _scope.recall_waveform(slot, dest))


# =============================================================================
# Cursors
# =============================================================================

@mcp.tool()
def scope_cursor_info() -> str:
    """Query current cursor measurements from the oscilloscope.

    Transport: SCPI
    """
    return _run(_scope.get_cursor_info)


@mcp.tool()
def scope_set_cursor_type(cursor_type: str) -> str:
    """Set the cursor type.

    Args:
        cursor_type: HREL (relative horizontal), VREL (relative vertical),
                     HREF (absolute horizontal), VREF (absolute vertical),
                     or OFF to disable cursors.

    Transport: SCPI
    """
    return _run(lambda: _scope.set_cursor_type(cursor_type))


# =============================================================================
# Screenshot
# =============================================================================

@mcp.tool()
def scope_screenshot(image_format: str = "PNG", area: str = "DSOWINDOW", background: str = "WHITE") -> str:
    """Capture the oscilloscope screen and save as a timestamped image file.

    Files are always saved to a 'screenshots/' subfolder with an auto-generated
    filename, e.g.: screenshots/scope_20260329_153042.png
    The full path is returned so you know exactly where the file landed.

    Args:
        image_format: BMP, JPEG, PNG, or TIFF (default PNG)
        area:         DSOWINDOW (default), GRIDAREAONLY, or FULLSCREEN
        background:   WHITE (default) or BLACK to preserve the dark screen theme

    Transport: SCPI (HARDCOPY_SETUP + SCREEN_DUMP, binary read)
    """
    def _save():
        import io
        import os
        from PIL import Image
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(os.getcwd(), "screenshots")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, f"scope_{ts}.{image_format.lower()}")
        data = _scope.get_screenshot(image_format, area, background)
        # Normalize to standard RGB PNG so the Anthropic API can always read it
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.save(dest, image_format.upper())
        return f"Screenshot saved to {dest} ({os.path.getsize(dest):,} bytes)"
    return _run(_save)


# =============================================================================
# Waveform capture
# =============================================================================

@mcp.tool()
def scope_get_waveform(channel: int, max_points: int = 10000) -> str:
    """Capture waveform data from a channel and save it as a .npz file.

    Use this when you need the time-domain signal (plotting, export, detailed
    analysis). For scalar results like peak voltage, frequency, or RMS, prefer
    scope_measure — it is faster and uses all scope points without any transfer.

    Stops the scope before transferring so the acquisition is frozen.
    The scope remains stopped after capture — call scope_arm to resume.

    Saves to a 'waveforms/' subfolder with an auto-generated filename,
    e.g.: waveforms/C1_20260329_153042.npz

    Returns JSON with the file path and metadata — the raw voltage values
    are not embedded in the result. Load the file in Python with:
        import numpy as np
        d = np.load('/path/to/file.npz')
        time_s, voltage_v = d['time_s'], d['voltage_v']

    Args:
        channel:    Channel number 1–4
        max_points: Maximum samples to capture (default 10000, evenly downsampled).

    Transport: SCPI (binary WF? DAT1 transfer + INSPECT? WAVEDESC scaling)
    """
    def _save():
        import numpy as np
        warn = _probe_warning(channel)
        _scope.stop()
        data = _scope.get_waveform(channel, max_points)
        voltages = data["voltages"]
        dt = data["sample_interval_s"]
        time_arr = [round(i * dt, 12) for i in range(len(voltages))]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(os.getcwd(), "waveforms")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, f"C{channel}_{ts}.npz")
        np.savez(dest, time_s=time_arr, voltage_v=voltages)
        return warn + json.dumps({
            "data_file":        dest,
            "channel":          channel,
            "num_points":       len(voltages),
            "sample_interval_s": dt,
            "traces":           ["time_s", "voltage_v"],
        })
    return _run(_save)


@mcp.tool()
def scope_capture_channels(channels: list, max_points: int = 10000) -> str:
    """Capture multiple channels atomically and save to a single .npz file.

    Use this when you need time-domain signals from multiple channels (plotting,
    cross-channel analysis, export). For scalar results like peak voltage or
    frequency, prefer scope_measure — no waveform transfer needed.

    Stops the scope before transferring so the acquisition is frozen during
    the read. All channels are read within a single VISA lock hold (one COMM
    setup, sequential reads), so the waveforms come from the same snapshot.
    The scope remains stopped after capture — call scope_arm to resume.

    Saves to 'waveforms/' with an auto-generated filename,
    e.g.: waveforms/C3F1_20260329_153042.npz

    The .npz file contains arrays: time_s, c3, f1, ... (one per channel).
    Analog channels use keys like c1, c2; math channels use f1, f2, etc.

    Load in Python with:
        import numpy as np
        d = np.load('/path/to/file.npz')
        time_s, c3, f1 = d['time_s'], d['c3'], d['f1']

    Args:
        channels:   List of analog channel numbers (e.g. [1, 2]) and/or math
                    channel strings (e.g. ["F1", "F2"]). Mixed lists are supported,
                    e.g. [3, "F1"] captures C3 and the F1 math trace together.
        max_points: Maximum samples per channel (default 10000, evenly downsampled).

    Transport: SCPI (binary WF? DAT1 transfer + INSPECT? WAVEDESC scaling)
    """
    def _save():
        import numpy as np
        # Warn for any integer channels explicitly marked as not connected
        warnings = "".join(
            _probe_warning(c) for c in channels if isinstance(c, int)
        )
        _scope.stop()
        waveforms = _scope.get_waveforms(channels, max_points)
        dt = waveforms[0]["sample_interval_s"]
        n  = waveforms[0]["num_points"]
        time_arr = [round(i * dt, 12) for i in range(n)]
        arrays = {"time_s": time_arr}
        for wf in waveforms:
            ch = wf["channel"]
            key = str(ch).lower() if isinstance(ch, str) else f"c{ch}"
            arrays[key] = wf["voltages"]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        def _tag(c):
            return str(c).upper() if isinstance(c, str) else f"C{c}"
        ch_tag = "".join(_tag(c) for c in channels)
        folder = os.path.join(os.getcwd(), "waveforms")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, f"{ch_tag}_{ts}.npz")
        np.savez(dest, **arrays)
        def _key(c):
            return str(c).lower() if isinstance(c, str) else f"c{c}"
        return warnings + json.dumps({
            "data_file":        dest,
            "channels":         channels,
            "num_points":       n,
            "sample_interval_s": dt,
            "traces":           ["time_s"] + [_key(c) for c in channels],
        })
    return _run(_save)


@mcp.tool()
def scope_save_waveform_csv(channel: int, max_points: int = 10000) -> str:
    """Capture a waveform and save it as a timestamped CSV file ready for post-processing.

    Files are always saved to a 'waveforms/' subfolder next to the server
    with an auto-generated filename, e.g.: waveforms/C1_20260329_153042.csv
    The full path is returned so you know exactly where the file landed.

    The CSV has two columns: time_s and voltage_v. Metadata lines starting
    with # at the top are ignored by pandas (use comment='#').

    Example Python usage:
        import pandas as pd
        df = pd.read_csv('waveforms/C1_20260329_153042.csv', comment='#')
        df.plot(x='time_s', y='voltage_v')

    Args:
        channel:    Channel number 1–4
        max_points: Maximum samples to save (default 10000).

    Transport: SCPI (binary WF? DAT1 transfer + INSPECT? WAVEDESC scaling)
    """
    def _save():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(os.getcwd(), "waveforms")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, f"C{channel}_{ts}.csv")

        data = _scope.get_waveform(channel, max_points)
        voltages = data["voltages"]
        dt = data["sample_interval_s"]
        idn = _scope.identify()

        with open(dest, "w", newline="") as f:
            writer = csv.writer(f)
            f.write(f"# instrument: {idn}\n")
            f.write(f"# channel: C{channel}\n")
            f.write(f"# captured: {datetime.now().isoformat(timespec='seconds')}\n")
            f.write(f"# num_points: {data['num_points']}\n")
            f.write(f"# sample_interval_s: {dt}\n")
            f.write(f"# vertical_gain: {data['vertical_gain']}\n")
            f.write(f"# vertical_offset: {data['vertical_offset']}\n")
            writer.writerow(["time_s", "voltage_v"])
            for i, v in enumerate(voltages):
                writer.writerow([round(i * dt, 12), v])

        return f"Saved {data['num_points']:,} samples to {dest}"

    return _run(_save)


# =============================================================================
# WaveSource built-in generator  (VBS automation — WS3000Z and similar)
# =============================================================================

@mcp.tool()
def scope_wavesource_info() -> str:
    """Get all current WaveSource generator settings.

    Returns shape, frequency, amplitude, offset, load, duty cycle,
    symmetry, and enabled state.

    Only available on models with has_wavesource=True (e.g. WaveSurfer 3000Z).
    Check scope_capabilities first.

    Transport: VBS (app.WaveSource.*)
    """
    def _fmt():
        info = _scope.get_wavesource_info()
        lines = ["WaveSource settings:"]
        for k, v in info.items():
            lines.append(f"  {k:12s}: {v}")
        return "\n".join(lines)
    return _run(_fmt)


@mcp.tool()
def scope_wavesource_enable(on: bool) -> str:
    """Enable or disable the WaveSource output.

    Args:
        on: True to enable output, False to disable.

    Transport: VBS (app.WaveSource.Enable)
    """
    return _run(lambda: _scope.wavesource_enable(on))


@mcp.tool()
def scope_wavesource_configure(
    shape: str = None,
    frequency: float = None,
    amplitude: float = None,
    offset: float = None,
    load: str = None,
    duty_cycle: float = None,
    symmetry: float = None,
) -> str:
    """Configure the WaveSource built-in generator in a single call.

    All parameters are optional — only the provided ones are applied.
    Only available on models with has_wavesource=True (e.g. WaveSurfer 3000Z).
    Check scope_capabilities first.

    Args:
        shape:      Waveform shape: Sine, Square, Triangle, Pulse, DC, Noise, Arb.
                    For sawtooth/ramp use Triangle with symmetry=0 or symmetry=100.
        frequency:  Output frequency in Hz, e.g. 1000.0 for 1 kHz
        amplitude:  Peak-to-peak amplitude in Vpp, e.g. 3.3 for 3.3 Vpp
        offset:     DC offset in volts
        load:       Output load: 'HiZ' (high impedance) or '50' (50 Ω termination)
        duty_cycle: Duty cycle in percent — Square and Pulse shapes only
        symmetry:   Symmetry in percent — Triangle shape only (50 = symmetric)

    Transport: VBS (app.WaveSource.*)
    """
    def _apply():
        applied = []
        if shape      is not None: _scope.wavesource_set_shape(shape);           applied.append(f"shape={shape}")
        if frequency  is not None: _scope.wavesource_set_frequency(frequency);   applied.append(f"frequency={frequency}Hz")
        if amplitude  is not None: _scope.wavesource_set_amplitude(amplitude);   applied.append(f"amplitude={amplitude}Vpp")
        if offset     is not None: _scope.wavesource_set_offset(offset);         applied.append(f"offset={offset}V")
        if load       is not None: _scope.wavesource_set_load(load);             applied.append(f"load={load}")
        if duty_cycle is not None: _scope.wavesource_set_duty_cycle(duty_cycle); applied.append(f"duty_cycle={duty_cycle}%")
        if symmetry   is not None: _scope.wavesource_set_symmetry(symmetry);     applied.append(f"symmetry={symmetry}%")
        if not applied:
            return "No parameters specified — nothing changed."
        return "WaveSource: " + ", ".join(applied)
    return _run(_apply)


# =============================================================================
# Serial Decode  (VBS — app.SerialDecode)
# =============================================================================

@mcp.tool()
def scope_decode_read(decoder: int = 1) -> str:
    """Read decoded serial data from the scope's SerialDecode subsystem.

    The scope must already have a serial decode active (configured via its UI
    or scope_decode_configure_uart). Works with UART/RS-232, I2C, SPI, CAN,
    and any other protocol supported by the Decode option.

    Reads the decoded table row-by-row using the VBS Table API and saves the
    result to a timestamped .npz file so the raw data is not embedded in the
    response. The file contains:
      time_s  — float array, timestamp for each decoded frame/byte
      data    — uint8 array, decoded byte values

    Returns JSON with the file path and metadata. Load in Python with:
        import numpy as np
        d = np.load('/path/to/file.npz')
        times, data_bytes = d['time_s'], d['data']

    Note: row-by-row VBS queries are slow (~0.05 s each). Decodes with
    hundreds of rows will take 10–20 s. Keep this in mind for large captures.

    Args:
        decoder: Decode slot number — 1 or 2 (default 1)

    Transport: VBS (app.SerialDecode.Decode{n}.Out.Result.*)
    """
    def _save():
        import numpy as np
        result = _scope.decode_read(decoder)
        rows = result["rows"]
        if rows == 0:
            return json.dumps({
                "decoder": decoder,
                "num_frames": 0,
                "message": "Decode table is empty — trigger the scope first.",
            })

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(os.getcwd(), "decode")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, f"Decode{decoder}_{ts}.npz")

        arrays: dict = {}
        if result["time_s"]:
            arrays["time_s"] = np.array(
                [x if x is not None else float("nan") for x in result["time_s"]],
                dtype=float,
            )
        if result["data"]:
            arrays["data"] = np.array(
                [x if x is not None else 0 for x in result["data"]],
                dtype=np.uint8,
            )
        # Save every visible column as a string array for reference
        for col_name, col_idx in result["col_map"].items():
            col_values = [r.get(col_name, "") for r in result["raw_rows"]]
            arrays[f"col_{col_name.lower()}"] = np.array(col_values, dtype=object)

        np.savez(dest, **arrays)
        traces = list(arrays.keys())
        return json.dumps({
            "data_file":  dest,
            "decoder":    decoder,
            "num_frames": rows,
            "col_map":    result["col_map"],
            "traces":     traces,
        })
    return _run(_save)


# =============================================================================
# Entry point — HTTP transport (for `mcp dev server.py` inspector)
# =============================================================================

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
