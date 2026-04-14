"""
LeCroy oscilloscope VISA/SCPI interface.
Full implementation with model-aware capability profiles.
"""

import re
import pyvisa
from dataclasses import dataclass
from typing import Optional


class InstrumentError(Exception):
    """Raised when the oscilloscope is unreachable or returns an error."""


# =============================================================================
# Model capability profiles
# =============================================================================

@dataclass(frozen=True)
class ModelProfile:
    """Describes the capabilities of a specific LeCroy oscilloscope family."""

    family:          str           # Human-readable family name
    channels:        int           # Number of analog input channels
    bandwidth_mhz:   int           # Maximum analog bandwidth in MHz
    bits:            int           # ADC vertical resolution (8 or 12)
    coupling_cmd:    str           # SCPI coupling command: "CPL" or "COUP"
    coupling_values: frozenset     # Valid coupling argument strings
    bwlimit_values:  frozenset     # Valid bandwidth-limit argument strings
    max_memory_kpts: int           # Maximum acquisition memory in kilo-samples
    math_channels:   int           # Number of math function channels (F1–Fn)
    has_invs:        bool          # INVS (invert) command supported
    has_unit:        bool          # UNIT command supported
    has_sara:        bool          # SARA? sample-rate query supported
    has_wavesource:  bool = False  # Built-in WaveSource generator (VBS app.WaveSource.*)
    notes:           str = ""      # Free-text notes / caveats


# Coupling value sets
_CPL_MODERN  = frozenset({"D1M", "D50", "A1M", "GND"})  # MAUI CPL command
_COUP_LEGACY = frozenset({"DC", "AC", "GND", "DC50"})    # older COUP command

# Bandwidth limit sets
_BWL_NONE = frozenset({"OFF"})
_BWL_20   = frozenset({"OFF", "20MHZ"})
_BWL_200  = frozenset({"OFF", "20MHZ", "200MHZ"})
_BWL_FULL = frozenset({"OFF", "20MHZ", "200MHZ", "FULL"})


# Registry: list of (IDN-model-prefix, ModelProfile) pairs.
# Checked in order — more specific prefixes should come before shorter ones.
_PROFILE_REGISTRY: list[tuple[str, ModelProfile]] = [

    # ── WaveSurfer 3000Z ─────────────────────────────────────────────────────
    ("WS30", ModelProfile(
        family="WaveSurfer 3000Z",
        channels=4, bandwidth_mhz=500, bits=8,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_20,
        max_memory_kpts=10_000, math_channels=4,
        has_invs=False, has_unit=False, has_sara=False, has_wavesource=True,
        notes="BWL query returns all channels at once. "
              "INVS/UNIT/SARA not supported on firmware 11.x.",
    )),

    # ── WaveSurfer 4000HD ────────────────────────────────────────────────────
    ("WS4", ModelProfile(
        family="WaveSurfer 4000HD",
        channels=4, bandwidth_mhz=1000, bits=12,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_200,
        max_memory_kpts=50_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── HDO4000A ─────────────────────────────────────────────────────────────
    ("HDO4", ModelProfile(
        family="HDO4000A",
        channels=4, bandwidth_mhz=1000, bits=12,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_200,
        max_memory_kpts=250_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── HDO6000B ─────────────────────────────────────────────────────────────
    ("HDO6", ModelProfile(
        family="HDO6000B",
        channels=4, bandwidth_mhz=2000, bits=12,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_200,
        max_memory_kpts=500_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── HDO8000A — 8 channels ────────────────────────────────────────────────
    ("HDO8", ModelProfile(
        family="HDO8000A",
        channels=8, bandwidth_mhz=2000, bits=12,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_200,
        max_memory_kpts=500_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── MDA800A — 8-channel motor drive analyser ─────────────────────────────
    ("MDA8", ModelProfile(
        family="MDA800A",
        channels=8, bandwidth_mhz=1000, bits=12,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_200,
        max_memory_kpts=250_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── WavePro HD ───────────────────────────────────────────────────────────
    ("WP", ModelProfile(
        family="WavePro HD",
        channels=4, bandwidth_mhz=8000, bits=12,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_FULL,
        max_memory_kpts=5_000_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── WaveRunner 8000 / 8000HD ─────────────────────────────────────────────
    ("WR8", ModelProfile(
        family="WaveRunner 8000",
        channels=4, bandwidth_mhz=4000, bits=12,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_200,
        max_memory_kpts=500_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── WaveRunner 6000 ──────────────────────────────────────────────────────
    ("WR6", ModelProfile(
        family="WaveRunner 6000",
        channels=4, bandwidth_mhz=1000, bits=8,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_200,
        max_memory_kpts=32_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),

    # ── SDA (Serial Data Analyser) ───────────────────────────────────────────
    ("SDA", ModelProfile(
        family="SDA",
        channels=4, bandwidth_mhz=20000, bits=8,
        coupling_cmd="CPL", coupling_values=_CPL_MODERN,
        bwlimit_values=_BWL_FULL,
        max_memory_kpts=256_000, math_channels=4,
        has_invs=True, has_unit=True, has_sara=False,
    )),
]

# Fallback for unrecognised models — conservative safe defaults
DEFAULT_PROFILE = ModelProfile(
    family="Unknown LeCroy",
    channels=4, bandwidth_mhz=0, bits=8,
    coupling_cmd="CPL", coupling_values=_CPL_MODERN,
    bwlimit_values=_BWL_200,
    max_memory_kpts=10_000, math_channels=4,
    has_invs=False, has_unit=False, has_sara=False,
    notes="Model not in registry — using conservative defaults. "
          "Some commands may not be supported.",
)

# PAVA parameters valid across all models
VALID_PAVA_PARAMS = frozenset({
    "MEAN", "MAX", "MIN", "PKPK", "FREQ", "PERIOD", "RMS",
    "RISE", "FALL", "WIDTH", "DUTY", "BASE", "TOP", "AMPL",
    "OVSP", "UNDSP", "PHASE", "DELAY", "AREA",
})

VALID_TRIG_MODES = frozenset({"AUTO", "NORM", "SINGLE", "STOP"})
VALID_SLOPES     = frozenset({"POS", "NEG", "EITHER"})
VALID_UNITS      = frozenset({"V", "A", "W", "U"})


def detect_profile(model_string: str) -> ModelProfile:
    """Return the ModelProfile for the given IDN model field.

    Matches by prefix in registry order. Falls back to DEFAULT_PROFILE.
    """
    model_upper = model_string.upper()
    for prefix, profile in _PROFILE_REGISTRY:
        if model_upper.startswith(prefix.upper()):
            return profile
    return DEFAULT_PROFILE


# =============================================================================
# Instrument class
# =============================================================================

class LeCroyScope:
    """
    VISA/SCPI interface for LeCroy oscilloscopes (MAUI firmware).

    Connection is lazy: instantiating does not open VISA.
    Call connect() before using any instrument methods.

    After connect(), self.profile contains the detected ModelProfile with
    all capability information for the connected instrument.
    """

    def __init__(self, resource_string: Optional[str] = None):
        self._rm: Optional[pyvisa.ResourceManager] = None
        self._inst = None
        self._resource_string = resource_string
        self._idn: Optional[str] = None
        self._model: Optional[str] = None
        self.profile: ModelProfile = DEFAULT_PROFILE

    # =========================================================================
    # Connection management
    # =========================================================================

    def connect(self, resource_string: Optional[str] = None) -> str:
        """Open VISA connection, detect model profile, return IDN string."""
        if resource_string:
            self._resource_string = resource_string
        if not self._resource_string:
            raise InstrumentError("No resource string provided.")

        self._rm = pyvisa.ResourceManager("@py")
        self._inst = self._rm.open_resource(self._resource_string)
        self._inst.timeout = 10000
        self._inst.write_termination = "\n"
        self._inst.read_termination = "\n"

        self._idn = self.query("*IDN?")
        self._model = self._parse_model(self._idn)
        self.profile = detect_profile(self._model)
        return self._idn

    def disconnect(self) -> None:
        """Close VISA connection gracefully."""
        for obj in (self._inst, self._rm):
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass
        self._inst = None
        self._rm = None
        self._idn = None
        self._model = None
        self.profile = DEFAULT_PROFILE

    @property
    def is_connected(self) -> bool:
        return self._inst is not None

    def _require_connected(self) -> None:
        if not self.is_connected:
            raise InstrumentError(
                "Not connected. Call connect() first with a VISA resource string."
            )

    @staticmethod
    def _parse_model(idn: str) -> str:
        """Extract the model field from an IDN string.

        Format: '*IDN LECROY,<MODEL>,<SERIAL>,<FIRMWARE>'
        """
        s = idn.strip()
        if s.upper().startswith("*IDN"):
            s = s[4:].strip()
        parts = s.split(",")
        return parts[1].strip() if len(parts) >= 2 else s

    def get_capabilities(self) -> dict:
        """Return a summary of the connected instrument's capabilities."""
        p = self.profile
        return {
            "model":           self._model or "unknown",
            "idn":             self._idn or "not connected",
            "family":          p.family,
            "channels":        p.channels,
            "bandwidth_mhz":   p.bandwidth_mhz,
            "bits":            p.bits,
            "coupling_cmd":    p.coupling_cmd,
            "coupling_values": sorted(p.coupling_values),
            "bwlimit_values":  sorted(p.bwlimit_values),
            "max_memory_kpts": p.max_memory_kpts,
            "math_channels":   p.math_channels,
            "has_invs":        p.has_invs,
            "has_unit":        p.has_unit,
            "has_sara":        p.has_sara,
            "notes":           p.notes,
        }

    # =========================================================================
    # Resource discovery
    # =========================================================================

    @staticmethod
    def list_resources() -> list[str]:
        """Return all VISA resources visible on this PC (LAN and USB)."""
        rm = pyvisa.ResourceManager("@py")
        resources = list(rm.list_resources())
        rm.close()
        return resources

    @staticmethod
    def scan_network(subnet: str, timeout_s: float = 0.5) -> list[tuple[str, str]]:
        """Scan a subnet for LeCroy oscilloscopes via VXI-11.

        Probes all hosts in the subnet for port 111 (Sun RPC portmapper,
        always open on VXI-11 instruments) in parallel, then queries *IDN?
        on each responsive host. Returns only LeCroy instruments.

        Args:
            subnet:    CIDR notation, e.g. '192.168.1.0/24'
            timeout_s: Socket probe timeout per host (default 0.5 s)

        Returns:
            List of (resource_string, idn) tuples for each LeCroy found.
        """
        import ipaddress
        import socket
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def probe(ip: str) -> str | None:
            try:
                s = socket.socket()
                s.settimeout(timeout_s)
                s.connect((ip, 111))
                s.close()
                return ip
            except Exception:
                return None

        network = ipaddress.ip_network(subnet, strict=False)
        responsive = []
        with ThreadPoolExecutor(max_workers=64) as ex:
            futures = {ex.submit(probe, str(ip)): ip for ip in network.hosts()}
            for f in as_completed(futures):
                result = f.result()
                if result:
                    responsive.append(result)

        found = []
        for ip in responsive:
            resource = f"TCPIP0::{ip}::inst0::INSTR"
            try:
                rm = pyvisa.ResourceManager("@py")
                inst = rm.open_resource(resource)
                inst.timeout = 2000
                inst.write_termination = "\n"
                inst.read_termination = "\n"
                idn = inst.query("*IDN?").strip()
                inst.close()
                rm.close()
                if "LECROY" in idn.upper():
                    found.append((resource, idn))
            except Exception:
                pass
        return found

    # =========================================================================
    # Raw SCPI access
    # =========================================================================

    def _ch(self, channel: int) -> str:
        """Validate channel number against the profile and return prefix like 'C1'."""
        n = self.profile.channels
        if channel not in range(1, n + 1):
            raise InstrumentError(
                f"Invalid channel {channel}. "
                f"{self.profile.family} has channels 1–{n}."
            )
        return f"C{channel}"

    def _fn(self, func: int) -> str:
        """Validate math function number and return prefix like 'F1'."""
        n = self.profile.math_channels
        if func not in range(1, n + 1):
            raise InstrumentError(f"Invalid math function {func}. Must be 1–{n}.")
        return f"F{func}"

    def _trace(self, channel) -> str:
        """Return SCPI prefix for an analog channel (int → 'C1') or math channel (str 'F1' → 'F1')."""
        if isinstance(channel, str) and channel.upper().startswith("F"):
            try:
                func_num = int(channel[1:])
            except ValueError:
                raise InstrumentError(f"Invalid math channel: {channel!r}")
            return self._fn(func_num)
        return self._ch(int(channel))

    def _mem(self, slot: int) -> str:
        """Validate memory slot (1–4) and return prefix like 'M1'."""
        if slot not in (1, 2, 3, 4):
            raise InstrumentError(f"Invalid memory slot {slot}. Must be 1–4.")
        return f"M{slot}"

    def query(self, cmd: str) -> str:
        """Send a SCPI query and return the stripped response string."""
        self._require_connected()
        return self._inst.query(cmd).strip()

    def write(self, cmd: str) -> None:
        """Send a SCPI write command (no response expected)."""
        self._require_connected()
        self._inst.write(cmd)

    # =========================================================================
    # System / Identity
    # =========================================================================

    def identify(self) -> str:
        return self.query("*IDN?")

    def reset(self) -> None:
        self.write("*RST")

    def calibrate(self) -> str:
        return self.query("*CAL?")

    def auto_setup(self) -> None:
        self.write("AUTO_SETUP")

    def get_date(self) -> str:
        return self.query("DATE?")

    def beep(self) -> None:
        self.write("BUZZER BEEP")

    def set_panel_lock(self, locked: bool) -> None:
        self.write(f"PANEL_LOCK {'ON' if locked else 'OFF'}")

    # =========================================================================
    # Channel configuration
    # =========================================================================

    def get_channel_info(self, channel: int) -> dict:
        """Return all readable settings for a channel."""
        ch = self._ch(channel)
        keys = {
            "vdiv":        f"{ch}:VDIV?",
            "offset":      f"{ch}:OFST?",
            "coupling":    f"{ch}:{self.profile.coupling_cmd}?",
            "bwlimit":     "BWL?",
            "trace":       f"{ch}:TRA?",
        }
        if self.profile.has_invs:
            keys["invert"] = f"{ch}:INVS?"
        if self.profile.has_unit:
            keys["unit"] = f"{ch}:UNIT?"
        result = {}
        for k, cmd in keys.items():
            try:
                result[k] = self.query(cmd)
            except Exception:
                result[k] = "N/A"
        return result

    def set_vdiv(self, channel: int, volts_per_div: float) -> None:
        self.write(f"{self._ch(channel)}:VDIV {volts_per_div:.6E}")

    def set_offset(self, channel: int, offset_volts: float) -> None:
        self.write(f"{self._ch(channel)}:OFST {offset_volts:.6E}")

    def set_coupling(self, channel: int, coupling: str) -> None:
        """Set input coupling. Valid values depend on the model (see scope_capabilities)."""
        coupling = coupling.upper()
        valid = self.profile.coupling_values
        if coupling not in valid:
            raise InstrumentError(
                f"Invalid coupling '{coupling}' for {self.profile.family}. "
                f"Choose from: {', '.join(sorted(valid))}"
            )
        self.write(f"{self._ch(channel)}:{self.profile.coupling_cmd} {coupling}")

    def set_bwlimit(self, channel: int, bwl: str) -> None:
        """Set bandwidth limit. Valid values depend on the model."""
        bwl = bwl.upper()
        valid = self.profile.bwlimit_values
        if bwl not in valid:
            raise InstrumentError(
                f"Invalid bandwidth limit '{bwl}' for {self.profile.family}. "
                f"Choose from: {', '.join(sorted(valid))}"
            )
        self.write(f"{self._ch(channel)}:BWL {bwl}")

    def set_invert(self, channel: int, on: bool) -> None:
        if not self.profile.has_invs:
            raise InstrumentError(f"Invert not supported on {self.profile.family}.")
        self.write(f"{self._ch(channel)}:INVS {'ON' if on else 'OFF'}")

    def set_trace(self, channel: int, on: bool) -> None:
        self.write(f"{self._ch(channel)}:TRA {'ON' if on else 'OFF'}")

    def set_attenuation(self, channel: int, factor: float) -> None:
        self.write(f"{self._ch(channel)}:ATTN {factor:g}")

    def set_unit(self, channel: int, unit: str) -> None:
        if not self.profile.has_unit:
            raise InstrumentError(f"UNIT command not supported on {self.profile.family}.")
        unit = unit.upper()
        if unit not in VALID_UNITS:
            raise InstrumentError(f"Invalid unit '{unit}'. Choose from: {', '.join(sorted(VALID_UNITS))}")
        self.write(f"{self._ch(channel)}:UNIT {unit}")

    # =========================================================================
    # Timebase
    # =========================================================================

    def get_timebase_info(self) -> dict:
        keys = {"tdiv": "TDIV?", "trig_delay": "TRDL?", "memory_size": "MSIZ?"}
        result = {}
        for k, cmd in keys.items():
            try:
                result[k] = self.query(cmd)
            except Exception:
                result[k] = "N/A"
        return result

    def set_tdiv(self, seconds_per_div: float) -> None:
        self.write(f"TDIV {seconds_per_div:.6E}")

    def set_trigger_delay(self, seconds: float) -> None:
        self.write(f"TRDL {seconds:.6E}")

    def set_memory_size(self, size: str) -> None:
        self.write(f"MSIZ {size}")

    # =========================================================================
    # Trigger
    # =========================================================================

    def get_trigger_info(self) -> dict:
        result = {}
        for k, cmd in {"mode": "TRIG_MODE?", "select": "TRIG_SELECT?"}.items():
            try:
                result[k] = self.query(cmd)
            except Exception:
                result[k] = "N/A"
        for ch in range(1, self.profile.channels + 1):
            try:
                result[f"c{ch}_trig_level"] = self.query(f"C{ch}:TRIG_LEVEL?")
            except Exception:
                result[f"c{ch}_trig_level"] = "N/A"
        return result

    def set_trigger_mode(self, mode: str) -> None:
        mode = mode.upper()
        if mode not in VALID_TRIG_MODES:
            raise InstrumentError(f"Invalid trigger mode '{mode}'. Choose from: {', '.join(sorted(VALID_TRIG_MODES))}")
        self.write(f"TRIG_MODE {mode}")

    def set_trigger_source(self, source: str, slope: str = "POS") -> None:
        """Configure edge trigger: source (C1–Cn, EX, EX5, LINE) and slope (POS/NEG/EITHER)."""
        source = source.upper()
        slope = slope.upper()
        if slope not in VALID_SLOPES:
            raise InstrumentError(f"Invalid slope '{slope}'. Choose from: {', '.join(sorted(VALID_SLOPES))}")
        self.write(f"TRIG_SELECT EDGE,SR,{source},SL,{slope},HT,OFF")

    def set_trigger_level(self, channel: int, level_volts: float) -> None:
        self.write(f"{self._ch(channel)}:TRIG_LEVEL {level_volts:.6E}")

    def force_trigger(self) -> None:
        self.write("FRTR")

    # =========================================================================
    # Acquisition control
    # =========================================================================

    def arm(self) -> None:
        self.write("ARM")

    def stop(self) -> None:
        self.write("STOP")

    def get_acquisition_status(self) -> str:
        trmd = self.query("TRMD?")
        inr  = self.query("INR?")
        return f"{trmd}  |  {inr}"

    # =========================================================================
    # Measurements (PAVA)
    # =========================================================================

    def setup_measurements(self, channel: int, params: list[str] | None = None) -> None:
        """Configure the scope's measurement panel (P1–P6) for a channel."""
        ch = self._ch(channel)
        if params is None:
            params = ["PKPK", "FREQ", "MEAN", "RMS", "RISE", "DUTY"]
        for slot, param in enumerate(params[:6], start=1):
            param = param.upper()
            if param not in VALID_PAVA_PARAMS:
                raise InstrumentError(f"Unknown parameter '{param}'.")
            self.write(f"PACU {slot},{param},{ch}")

    def measure(self, channel: int, param: str) -> str:
        """Query a single PAVA measurement. Auto-configures PACU slot if needed."""
        param = param.upper()
        if param not in VALID_PAVA_PARAMS:
            raise InstrumentError(
                f"Unknown parameter '{param}'. Valid: {', '.join(sorted(VALID_PAVA_PARAMS))}"
            )
        ch = self._ch(channel)
        result = self.query(f"{ch}:PAVA? {param}")
        if ",IV" in result:
            self.write(f"PACU 1,{param},{ch}")
            result = self.query(f"{ch}:PAVA? {param}")
        return result

    def measure_all(self, channel: int) -> dict[str, str]:
        """Query all standard PAVA measurements for a channel."""
        ch = self._ch(channel)
        results = {}
        for param in sorted(VALID_PAVA_PARAMS):
            try:
                self.write(f"PACU 1,{param},{ch}")
                results[param] = self.query(f"{ch}:PAVA? {param}")
            except Exception as e:
                results[param] = f"ERROR: {e}"
        return results

    # =========================================================================
    # Math functions (F1–Fn)
    # =========================================================================

    def set_math(self, func: int, equation: str) -> None:
        self.write(f"{self._fn(func)}:DEF EQN,'{equation}'")

    def set_math_trace(self, func: int, on: bool) -> None:
        self.write(f"{self._fn(func)}:TRA {'ON' if on else 'OFF'}")

    def get_math_info(self, func: int) -> dict:
        fn = self._fn(func)
        result = {}
        for k, cmd in {"definition": f"{fn}:DEF?", "trace": f"{fn}:TRA?", "vdiv": f"{fn}:VDIV?"}.items():
            try:
                result[k] = self.query(cmd)
            except Exception:
                result[k] = "N/A"
        return result

    def set_math_zoom(self, func: int, center: float, per_div: float) -> None:
        """Set horizontal display zoom for a math trace via VBS."""
        self._require_connected()
        self._fn(func)  # validate
        self._inst.write(f"VBS 'app.Math.F{func}.Zoom.HorCenter = {center}'")
        self._inst.write(f"VBS 'app.Math.F{func}.Zoom.HorScale = {per_div}'")

    def get_math_zoom(self, func: int) -> dict:
        """Read horizontal display zoom settings for a math trace via VBS."""
        self._require_connected()
        self._fn(func)  # validate
        center  = self._inst.query(f"VBS? 'Return=app.Math.F{func}.Zoom.HorCenter'").strip()
        per_div = self._inst.query(f"VBS? 'Return=app.Math.F{func}.Zoom.HorScale'").strip()
        return {"center": center, "per_div": per_div}

    # =========================================================================
    # Memory / Reference waveforms
    # =========================================================================

    def store_waveform(self, source: str, slot: int) -> None:
        self.write(f"STO {source.upper()},{self._mem(slot)}")

    def recall_waveform(self, slot: int, dest: str) -> None:
        self.write(f"RCL {self._mem(slot)},{dest.upper()}")

    # =========================================================================
    # Cursors
    # =========================================================================

    def get_cursor_info(self) -> str:
        return self.query("CURSOR_MEASURE?")

    def set_cursor_type(self, cursor_type: str) -> None:
        self.write(f"CURSOR_TYPE {cursor_type.upper()}")

    # =========================================================================
    # Screenshot
    # =========================================================================

    def get_screenshot(self, image_format: str = "PNG", area: str = "DSOWINDOW", background: str = "WHITE") -> bytes:
        """Capture the screen and return raw image bytes.

        Some firmware versions prefix the image with an IEEE 488.2 block header:
            #N<N digits giving byte count><image bytes>
        Others return raw image bytes directly.  Both are handled.

        Requires pyvisa-py backend (@py) — NI-VISA behaves differently and
        breaks the multi-read sequence used here.
        """
        self._require_connected()
        self._inst.write(
            f"HARDCOPY_SETUP DEV,{image_format.upper()},FORMAT,LANDSCAPE,"
            f"BCKG,{background.upper()},DEST,REMOTE,AREA,{area.upper()}"
        )
        self._inst.write("SCREEN_DUMP")

        lead = self._inst.read_bytes(2)

        if lead[0:1] == b"#":
            # IEEE 488.2 block header: #N<length><data>
            n_digits = int(chr(lead[1]))
            byte_count = int(self._inst.read_bytes(n_digits))
            return self._inst.read_bytes(byte_count)
        else:
            # Raw image bytes (firmware 11.2.x — no header)
            rest = self._inst.read_raw()
            return lead + rest

    # =========================================================================
    # Waveform capture
    # =========================================================================

    def get_waveform(self, channel: int, max_points: int = 10000) -> dict:
        """Capture waveform samples via binary transfer (single channel).

        Returns dict: channel, num_points, sample_interval_s,
        voltages (list of floats), vertical_gain, vertical_offset.
        """
        return self.get_waveforms([channel], max_points)[0]

    def get_waveforms(self, channels: list, max_points: int = 10000) -> list:
        """Capture one or more channels in a single VISA setup sequence.

        Sets COMM_ORDER and COMM_FORMAT once, then reads each channel in
        sequence. Reading all channels within one call guarantees they come
        from the same acquisition snapshot (no new trigger between reads).
        For absolute alignment on a fast-running scope, stop acquisition
        first with scope_stop.

        Returns a list of dicts, one per channel, each containing:
          channel, num_points, sample_interval_s, voltages (list),
          vertical_gain, vertical_offset.
        """
        self._require_connected()
        self._inst.write("COMM_ORDER LO")
        self._inst.write("COMM_FORMAT DEF9,WORD,BIN")

        def _parse(desc, key):
            m = re.search(rf"{key}\s*:\s*([+-]?\d+\.?\d*[eE]?[+-]?\d*)", desc, re.IGNORECASE)
            return float(m.group(1)) if m else 0.0

        results = []
        for channel in channels:
            ch = self._trace(channel)
            self._inst.write(f"{ch}:TRA ON")

            raw = self._inst.query_binary_values(
                f"{ch}:WF? DAT1",
                datatype="h",
                is_big_endian=False,
                container=list,
            )

            desc = self._inst.query(f"{ch}:INSPECT? WAVEDESC").strip()

            v_gain = _parse(desc, "VERTICAL_GAIN")
            v_off  = _parse(desc, "VERTICAL_OFFSET")
            h_int  = _parse(desc, "HORIZ_INTERVAL")

            step = max(1, len(raw) // max_points)
            samples = raw[::step]
            voltages = [round(s * v_gain - v_off, 6) for s in samples]

            results.append({
                "channel":           channel,
                "num_points":        len(voltages),
                "sample_interval_s": h_int * step,
                "voltages":          voltages,
                "vertical_gain":     v_gain,
                "vertical_offset":   v_off,
            })

        return results

    # =========================================================================
    # WaveSource built-in generator  (VBS automation — not raw SCPI)
    # =========================================================================

    def _require_wavesource(self) -> None:
        if not self.profile.has_wavesource:
            raise InstrumentError(
                f"{self.profile.family} does not have a WaveSource generator "
                "(or it is not confirmed in the model profile)."
            )

    def _vbs_get(self, prop: str) -> str:
        """Read a VBS automation property."""
        return self.query(f"VBS? 'Return={prop}'").strip()

    def _vbs_set(self, prop: str, value: str) -> None:
        """Set a VBS automation property."""
        self.write(f"VBS '{prop} = {value}'")

    def get_wavesource_info(self) -> dict:
        self._require_connected()
        self._require_wavesource()
        enabled_raw = self._vbs_get("app.WaveSource.Enable")
        return {
            "enabled":    enabled_raw != "0",
            "shape":      self._vbs_get("app.WaveSource.Shape"),
            "frequency":  self._vbs_get("app.WaveSource.Frequency"),
            "amplitude":  self._vbs_get("app.WaveSource.Amplitude"),
            "offset":     self._vbs_get("app.WaveSource.Offset"),
            "load":       self._vbs_get("app.WaveSource.Load"),
            "duty_cycle": self._vbs_get("app.WaveSource.DutyCycle"),
            "symmetry":   self._vbs_get("app.WaveSource.Symmetry"),
        }

    def wavesource_enable(self, on: bool) -> None:
        self._require_connected()
        self._require_wavesource()
        # VBScript True = -1, False = 0
        self._vbs_set("app.WaveSource.Enable", "-1" if on else "0")

    def wavesource_set_frequency(self, hz: float) -> None:
        self._require_connected()
        self._require_wavesource()
        self._vbs_set("app.WaveSource.Frequency", str(hz))

    def wavesource_set_shape(self, shape: str) -> None:
        self._require_connected()
        self._require_wavesource()
        self._vbs_set("app.WaveSource.Shape", f'"{shape}"')

    def wavesource_set_amplitude(self, vpp: float) -> None:
        self._require_connected()
        self._require_wavesource()
        self._vbs_set("app.WaveSource.Amplitude", str(vpp))

    def wavesource_set_offset(self, volts: float) -> None:
        self._require_connected()
        self._require_wavesource()
        self._vbs_set("app.WaveSource.Offset", str(volts))

    def wavesource_set_load(self, load: str) -> None:
        self._require_connected()
        self._require_wavesource()
        self._vbs_set("app.WaveSource.Load", f'"{load}"')

    def wavesource_set_duty_cycle(self, pct: float) -> None:
        self._require_connected()
        self._require_wavesource()
        self._vbs_set("app.WaveSource.DutyCycle", str(pct))

    def wavesource_set_symmetry(self, pct: float) -> None:
        self._require_connected()
        self._require_wavesource()
        self._vbs_set("app.WaveSource.Symmetry", str(pct))

    # =========================================================================
    # Serial Decode  (VBS — app.SerialDecode.Decode1 / Decode2)
    # =========================================================================

    @staticmethod
    def _parse_column_state(col_state: str) -> dict:
        """Parse pipe-delimited ColumnState into {name: 1-based visible-column index}.

        Example input: "Idx=On|Time=On|Data=On|Width=Off"
        Returns: {"Idx": 1, "Time": 2, "Data": 3}
        Only columns with state "On" are counted; off columns are skipped.
        """
        col_map: dict = {}
        visible_idx = 1
        for entry in col_state.strip().split("|"):
            if "=" not in entry:
                continue
            name, state = entry.split("=", 1)
            if state.strip().lower() == "on":
                col_map[name.strip()] = visible_idx
                visible_idx += 1
        return col_map

    def decode_read(self, decoder: int = 1) -> dict:
        """Read UART (or other protocol) decoded data from the SerialDecode table.

        Uses the VBS Table API:
          app.SerialDecode.Decode{n}.Out.Result.Rows
          app.SerialDecode.Decode{n}.Out.Result.Columns
          app.SerialDecode.Decode{n}.Decode.ColumnState  — pipe-delimited On/Off list
          app.SerialDecode.Decode{n}.Out.Result.CellValue(row, col)(0,0)

        Returns a dict with:
          rows      — number of decoded frames/bytes
          columns   — number of visible columns
          col_map   — {column-name: 1-based index} from ColumnState
          time_s    — list of timestamps (float) for each row, empty if no Time column
          data      — list of byte values (int) for each row, empty if no Data column
          raw_rows  — list of {col_name: raw_string} for every visible column
        """
        self._require_connected()
        base = f"app.SerialDecode.Decode{decoder}.Out.Result"

        def _q(expr: str) -> str:
            return self._inst.query(f"VBS? 'Return={expr}'").strip()

        rows_raw = _q(f"{base}.Rows")
        cols_raw = _q(f"{base}.Columns")
        try:
            rows = int(rows_raw.split()[-1])
            cols = int(cols_raw.split()[-1])
        except (ValueError, IndexError) as e:
            raise InstrumentError(
                f"SerialDecode.Decode{decoder}: could not read table dimensions "
                f"(rows={rows_raw!r}, cols={cols_raw!r}): {e}"
            )

        if rows == 0:
            return {"rows": 0, "columns": cols, "col_map": {}, "time_s": [], "data": [], "raw_rows": []}

        col_state_raw = _q(f"app.SerialDecode.Decode{decoder}.Decode.ColumnState")
        col_map = self._parse_column_state(col_state_raw)

        time_col = col_map.get("Time")
        data_col = col_map.get("Data")

        time_s: list = []
        data: list = []
        raw_rows: list = []

        for row in range(1, rows + 1):
            row_dict: dict = {}
            for name, col_idx in col_map.items():
                raw = _q(f"{base}.CellValue({row},{col_idx})(0,0)")
                # VBS returns e.g. "VBS 3.14159" or just "3.14159" — take last token
                row_dict[name] = raw.split()[-1] if raw.split() else raw
            raw_rows.append(row_dict)

            if time_col is not None:
                raw_t = _q(f"{base}.CellValue({row},{time_col})(0,0)")
                try:
                    time_s.append(float(raw_t.split()[-1]))
                except (ValueError, IndexError):
                    time_s.append(None)

            if data_col is not None:
                raw_d = _q(f"{base}.CellValue({row},{data_col})(0,0)")
                try:
                    data.append(int(float(raw_d.split()[-1])))
                except (ValueError, IndexError):
                    data.append(None)

        return {
            "rows": rows,
            "columns": cols,
            "col_map": col_map,
            "time_s": time_s,
            "data": data,
            "raw_rows": raw_rows,
        }
