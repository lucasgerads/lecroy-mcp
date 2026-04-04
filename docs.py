"""
LeCroy oscilloscope SCPI reference documentation.

Content is extracted from:
  - MAUI Oscilloscopes Remote Control and Automation Manual
  - WaveSurfer 3000Z Operator's Manual

Exposed as MCP resources and via the scope_help tool.
"""

# Maps topic slug → (title, content)
DOCS: dict[str, tuple[str, str]] = {}

DOCS["overview"] = (
    "LeCroy SCPI Overview",
    """\
LeCroy SCPI Overview
====================

Communication
-------------
LeCroy MAUI oscilloscopes accept SCPI commands over:
  - TCP/IP (VXI-11): TCPIP0::<ip>::inst0::INSTR
  - USBTMC:          USB0::0x05FF::<product>::<serial>::INSTR

After connecting, always send *IDN? first to confirm communication.

Command formats
---------------
Most commands have a long form and a short (abbreviated) form:
  C1:VOLT_DIV 0.5    ←→    C1:VDIV 0.5
  TRIG_MODE AUTO     ←→    TRMD AUTO
  BANDWIDTH_LIMIT?   ←→    BWL?

Channel prefix: C1 through Cn (n = 4 on WaveSurfer 3000Z, up to 8 on HDO/MDA/WR).
External trigger inputs: EX, EX5, EX10, ETM10 (model-dependent).

Response headers
----------------
COMM_HEADER SHORT   — abbreviated headers (default)
COMM_HEADER LONG    — full headers
COMM_HEADER OFF     — suppress headers (raw values only)

Byte order (for binary waveform transfers)
-----------------------------------------
COMM_ORDER LO       — little-endian (recommended for x86 hosts)
COMM_ORDER HI       — big-endian (network byte order)

Model detection
---------------
Call *IDN? after connecting. Response:
  *IDN LECROY,<model>,<serial>,<firmware>
The MCP server uses the model string to select a capability profile that
captures channel count, coupling command name, valid values, and optional
features. Use scope_capabilities to inspect the active profile.

Status registers
----------------
*CLS                — clear all status registers
ALL_STATUS?         — read STB, ESR, INR, DDR, CMR, EXR, URR simultaneously
INR?                — internal state change register (bit 0 = new acquisition ready)

IEEE 488.2 block data format
-----------------------------
Binary responses use #N<length><data> header:
  # — literal hash
  N — one digit giving the number of length digits that follow
  <length> — N decimal digits giving the byte count of <data>
Example: #7 0001024 <1024 bytes>
Strip this header before interpreting binary waveform or screenshot data.
""")

DOCS["channel"] = (
    "Channel Configuration Commands",
    """\
Channel Configuration Commands
==============================

Vertical scale  (VDIV / VOLT_DIV)
----------------------------------
Set:   C<n>:VDIV <value>[V]     e.g. C1:VDIV 500E-3
Query: C<n>:VDIV?
Value includes probe attenuation.  Typical range: 1 mV/div – 10 V/div.

Vertical offset  (OFST / OFFSET)
---------------------------------
Set:   C<n>:OFST <value>[V]     e.g. C1:OFST -1.5
Query: C<n>:OFST?
Offset accounts for probe attenuation.  Positive offset shifts trace down.

Input coupling  (CPL / COUPLING)
---------------------------------
WaveSurfer 3000/3000Z (and other modern MAUI scopes):
  Set:   C<n>:CPL <mode>       e.g. C1:CPL D1M
  Query: C<n>:CPL?
  Valid modes:
    D1M — DC, 1 MΩ input (most common)
    D50 — DC, 50 Ω input (RF / high-frequency signals)
    A1M — AC, 1 MΩ (blocks DC component)
    GND — internally grounded (zero-volt reference)

Older / HDO models may use COUP instead of CPL with different value names
(DC, AC, GND, DC50).  The MCP server selects the correct command from the
model profile automatically.

Bandwidth limit  (BWL / BANDWIDTH_LIMIT)
-----------------------------------------
Set (all channels):  BWL C1,<mode>,C2,<mode>,...
Set (one channel):   BWL C<n>,<mode>
Query:               BWL?   (returns all channels)
Valid modes (model-dependent):
  OFF     — full bandwidth
  20MHZ   — 20 MHz low-pass filter
  200MHZ  — 200 MHz (not available on WaveSurfer 3000Z)
  500MHZ, 1GHZ, 2GHZ, 3GHZ, 4GHZ, 6GHZ — high-BW models only

Probe attenuation  (ATTN / ATTENUATION)
-----------------------------------------
Set:   C<n>:ATTN <factor>      e.g. C1:ATTN 10
Query: C<n>:ATTN?
Valid factors: 1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 10000

Trace visibility  (TRA / TRACE)
---------------------------------
Set:   C<n>:TRA <state>        e.g. C1:TRA ON
Query: C<n>:TRA?
Valid: ON, OFF

Signal inversion  (INVS / INVERT)   [not on WaveSurfer 3000Z]
--------------------------------------------------------------
Set:   C<n>:INVS <state>       e.g. C1:INVS ON
Query: C<n>:INVS?
Valid: ON, OFF

Vertical unit  (UNIT)   [not on WaveSurfer 3000Z]
--------------------------------------------------
Set:   C<n>:UNIT <unit>        e.g. C1:UNIT A
Query: C<n>:UNIT?
Valid: V (volts), A (amperes), W (watts), U (user)
""")

DOCS["timebase"] = (
    "Timebase & Acquisition Memory Commands",
    """\
Timebase & Acquisition Memory Commands
=======================================

Time per division  (TDIV / TIME_DIV)
--------------------------------------
Set:   TDIV <value>[NS|US|MS|S|KS]   e.g. TDIV 500US  or  TDIV 1E-3
Query: TDIV?
Unit suffix is optional; default is seconds.  Examples:
  1 ns/div  → TDIV 1E-9
  100 µs/div → TDIV 1E-4
  10 ms/div  → TDIV 1E-2
  1 s/div   → TDIV 1

Trigger delay  (TRDL / TRIG_DELAY)
-------------------------------------
Set:   TRDL <value>            e.g. TRDL -5E-3
Query: TRDL?
Positive delay moves the trigger point left (post-trigger data).
Negative delay moves it right (pre-trigger data).
Range: -10000×TDIV to +10×TDIV.

Memory depth  (MSIZ / MEMORY_SIZE)
------------------------------------
Set:   MSIZ <size>             e.g. MSIZ 10K
Query: MSIZ?
Valid sizes: 500, 1K, 10K, 25K, 50K, 100K, 250K, 500K, 1M, 2.5M, 5M, 10M, 25M
(Available sizes are model-dependent.  WaveSurfer 3000Z maximum: 10 Mpts.)
Larger memory = more detail but slower waveform transfer.

Interleaved sampling  (ILVD / INTERLEAVED)
-------------------------------------------
Set:   ILVD <mode>             e.g. ILVD ON
Query: ILVD?
Valid: ON, OFF
ON enables Random Interleaved Sampling (RIS) which increases effective
sample rate.  Not available in Sequence mode.

Sequence mode  (SEQ / SEQUENCE)
---------------------------------
Set:   SEQ <mode>[,<segments>[,<max_size>]]
Query: SEQ?
Valid mode: ON, OFF
Enables capture of multiple triggered events in rapid succession.

Sample rate
-----------
Query: SARA?
Not supported on WaveSurfer 3000Z firmware 11.2.x.
Calculate from waveform INSPECT? HORIZ_INTERVAL instead.
""")

DOCS["trigger"] = (
    "Trigger Commands",
    """\
Trigger Commands
================

Trigger mode  (TRMD / TRIG_MODE)
-----------------------------------
Set:   TRMD <mode>
Query: TRMD?
Valid modes:
  AUTO   — free-running; always displays a trace even without a trigger
  NORM   — waits for a valid trigger event before capturing
  SINGLE — arms, waits for one trigger event, then stops
  STOP   — stops acquisition immediately

Edge trigger source & slope  (TRSE / TRIG_SELECT)
--------------------------------------------------
Set edge trigger:
  TRSE EDGE,SR,C<n>[,HT,TI,HV,0]   e.g. TRSE EDGE,SR,C1
Query: TRSE?

Trigger slope  (TRSL / TRIG_SLOPE)
-------------------------------------
Set:   C<n>:TRSL <slope>       e.g. C1:TRSL POS
Query: C<n>:TRSL?
Valid: POS (rising edge), NEG (falling edge)

Trigger level  (TRLV / TRIG_LEVEL)
-------------------------------------
Set:   C<n>:TRLV <volts>V      e.g. C1:TRLV 1.5V
Query: C<n>:TRLV?
Also valid for EX, EX5, EX10 sources.

Trigger coupling  (TRCP / TRIG_COUPLING)
------------------------------------------
Set:   C<n>:TRCP <mode>        e.g. C1:TRCP DC
Query: C<n>:TRCP?
Valid: AC, DC, HFREJ (high-frequency reject), LFREJ (low-frequency reject)

Force trigger  (FRTR / FORCE_TRIGGER)
---------------------------------------
Command: FRTR
Forces one acquisition immediately.  Useful when in NORM mode without a signal.

Advanced trigger types  (TRSE)
--------------------------------
TRIG_SELECT supports many trigger types beyond simple edge:
  EDGE        — standard edge trigger
  GLITCH      — pulse shorter or longer than a threshold
  INTERVAL    — time between edges
  RUNT        — pulse that doesn't reach full amplitude
  SLEW_RATE   — edge with dV/dt above/below threshold
  TV          — video trigger (NTSC, PAL, SECAM, HDTV)
  DROPOUT     — no edge for a specified time
  PATTERN     — logic pattern across multiple channels
  WIDTH       — pulse width within a range

Pattern trigger  (TRPA / TRIG_PATTERN)
-----------------------------------------
Set:   TRPA [C<n>,<state>,...],STATE,<cond>
Valid state: L (low), H (high)
Valid cond: AND, NAND, OR, NOR
""")

DOCS["acquisition"] = (
    "Acquisition Control Commands",
    """\
Acquisition Control Commands
=============================

Arm  (ARM / ARM_ACQUISITION)
------------------------------
Command: ARM
Arms the trigger system and begins waiting for a trigger event.
Equivalent to pressing the Run button.

Stop  (STOP)
-------------
Command: STOP
Stops acquisition immediately, regardless of trigger state.
Equivalent to pressing the Stop button.

Wait  (WAIT)
-------------
Command: WAIT [<timeout_seconds>]
Prevents new commands until the current acquisition completes.
Optional timeout in seconds.  Useful for single-shot captures:
  ARM ; WAIT 5 ; C1:WF? DAT1

Force trigger  (FRTR / FORCE_TRIGGER)
---------------------------------------
Command: FRTR
Forces an immediate trigger event without waiting for the source condition.

Single acquisition
------------------
Recommended sequence for a clean single capture:
  1. TRMD SINGLE
  2. ARM
  3. Poll INR? until bit 0 is set (value & 1 == 1), or use WAIT
  4. Read waveform: C1:WF? DAT1

Acquisition status
------------------
Query: INR?
INR is the Internal state change Register.  Key bits:
  bit 0 (value 1)  — new waveform acquired since last read
  bit 9 (value 512) — pass/fail test completed

Query: TRMD?
Returns current trigger mode: AUTO, NORM, SINGLE, or STOP.

Note: SAMPLE_STATUS? is not supported on WaveSurfer 3000Z firmware 11.2.x.
""")

DOCS["measurement"] = (
    "Automated Measurements (PAVA / PACU)",
    """\
Automated Measurements (PAVA / PACU)
======================================

How PAVA measurements work
---------------------------
PAVA (Parameter Value) returns the current value of a waveform measurement.
However, PAVA only returns valid values for parameters that have been
activated in one of the six measurement display slots (P1–P6).

To activate a parameter in slot 1:
  PACU 1,PKPK,C1
Then query it:
  C1:PAVA? PKPK

The scope_setup_measurements tool configures P1–P6 automatically.

PARAMETER_CUSTOM  (PACU)
--------------------------
Syntax:  PACU <slot>,<param>,<source>
  slot:   1–6 (display panel position)
  param:  measurement name (see list below)
  source: C1–C4, F1–F4, M1–M4, TA–TD
Example: PACU 3,FREQ,C2   → activate frequency measurement on C2 in slot 3

PARAMETER_VALUE  (PAVA)
-------------------------
Syntax:  <source>:PAVA? <param>
Response: <source>:PAVA <param>,<value>,<state>
State codes:
  OK  — valid measurement
  AV  — averaged value
  IV  — invalid (parameter not in an active PACU slot, or no signal)
  NP  — no pulse detected
  OF  — overflow
  UF  — underflow
  GT  — greater than display range
  LT  — less than display range
  OU  — both overflow and underflow

Full parameter list
--------------------
Timing:
  FREQ    — frequency (Hz)
  PERIOD  — period (s)
  RISE    — rise time 10–90% (s)
  FALL    — fall time 90–10% (s)
  RISE28  — rise time 20–80% (s)
  FALL82  — fall time 80–20% (s)
  WIDTH   — positive pulse width at 50% level (s)
  WIDN    — negative pulse width at 50% level (s)
  DUTY    — duty cycle (%)
  DELAY   — delay between two edges (s)
  PHASE   — phase difference (degrees)
  SKEW    — time from clock edge to data edge (s)

Voltage:
  MEAN    — mean (average) voltage (V)
  MAX     — maximum voltage (V)
  MIN     — minimum voltage (V)
  PKPK    — peak-to-peak voltage (V)
  RMS     — RMS voltage (V)
  BASE    — base voltage level (V)
  TOP     — top voltage level (V)
  AMPL    — amplitude = top – base (V)
  OVSP    — positive overshoot (%)
  OVSN    — negative overshoot (%)

Other:
  AREA    — area under curve (V·s)
  SDEV    — standard deviation (V)

Statistics (appended to any parameter):
  MEAN, MIN, MAX, SDEV available via the measurement statistics panel.
""")

DOCS["waveform"] = (
    "Waveform Transfer Commands",
    """\
Waveform Transfer Commands
===========================

Setup — byte order and format
-------------------------------
COMM_ORDER LO          → little-endian (recommended on x86 hosts)
COMM_ORDER HI          → big-endian

COMM_FORMAT DEF9,WORD,BIN   → binary, 16-bit signed integers (most efficient)
COMM_FORMAT DEF9,BYTE,BIN   → binary, 8-bit signed integers (faster, less resolution)

Always send COMM_ORDER and COMM_FORMAT before requesting waveform data.

Waveform query  (WF / WAVEFORM)
---------------------------------
Query: C<n>:WF? DAT1        — raw sample data
Query: C<n>:WF? DESC        — waveform descriptor (WAVEDESC block)
Query: C<n>:WF? TEXT        — text description of the waveform
Query: C<n>:WF? TIME        — time descriptor
Query: C<n>:WF? ALL         — complete waveform (DESC + TIME + DAT1 + DAT2)

The response is a binary block with an IEEE 488.2 #N<len><data> header.
Strip the header before passing data to numpy/struct.

Waveform setup  (WFSU / WAVEFORM_SETUP)
-----------------------------------------
Controls how many points are transmitted:
  WFSU SP,<sparsing>,NP,<num_points>,FP,<first_point>,SN,<segment>
  SP=0 → all points; SP=4 → every 4th point
  NP=0 → all points; NP=500 → first 500 points
  FP=0 → start at first sample
  SN=0 → all segments (sequence mode)
Query: WFSU?

Converting raw integers to volts
----------------------------------
From INSPECT? WAVEDESC:
  voltage = raw_sample × VERTICAL_GAIN − VERTICAL_OFFSET

Key WAVEDESC variables:
  VERTICAL_GAIN     — scaling factor (float)
  VERTICAL_OFFSET   — offset (float, volts)
  HORIZ_INTERVAL    — sample interval in seconds
  HORIZ_OFFSET      — trigger offset in seconds
  NOM_SUBARRAY_COUNT — number of samples in DAT1
  SWEEPS_PER_ACQ    — averages taken

INSPECT query  (INSP / INSPECT)
---------------------------------
Query: C<n>:INSPECT? "<variable>"
Example: C1:INSPECT? "VERTICAL_GAIN"
Response: <variable>: <value>
Use to retrieve individual WAVEDESC fields without parsing the full binary descriptor.

Storing to internal memory  (STO / STORE_WAVEFORM)
----------------------------------------------------
Store: STO C1,M1          → copy C1 to memory slot M1
Recall: RCL M1,C1         → recall M1 onto C1

Store to disk:
  STST C1,HDD,FILE,'waveform.trc'   → save .trc file
  RCST HDD,FILE,'waveform.trc',C1   → load .trc file
""")

DOCS["math"] = (
    "Math Function Commands",
    """\
Math Function Commands
======================

Math channels: F1–F4 (WaveSurfer 3000Z supports 4 math functions).

Defining a math function
-------------------------
Syntax: <func>:DEF EQN,'<equation>'
Example: F1:DEF EQN,'C1+C2'
Query:   F1:DEF?

Common math equations
---------------------
Arithmetic:
  C1+C2        — sum
  C1-C2        — difference
  C1*C2        — product
  C1/C2        — quotient

Transforms:
  FFT(C1)      — Fast Fourier Transform (frequency domain)
  IFFT(F1)     — Inverse FFT
  INTG(C1)     — integral
  DIFF(C1)     — derivative / differentiation
  SQRT(C1)     — square root
  LOG(C1)      — log base 10
  EXP(C1)      — exponential
  ABS(C1)      — absolute value

Filtering:
  ERES(C1)     — enhanced resolution (low-pass filter + extra bits)
  DESKEW(C1,<delay>) — time-shift a waveform

Averaging:
  AVGS(C1)     — continuous averaging
  EAVG(C1)     — envelope averaging

Showing / hiding math traces
-----------------------------
Show: F<n>:TRA ON
Hide: F<n>:TRA OFF
Query: F<n>:TRA?

Reset sweep count
------------------
Command: F<n>:FRST    (FUNCTION_RESET)
Resets the sweep counter for averaging functions.
""")

DOCS["cursor"] = (
    "Cursor Commands",
    """\
Cursor Commands
===============

Cursor types  (CRS / CURSORS)
-------------------------------
Set:   CRS <type>[,<readout>]
Query: CRS?
Types:
  OFF   — cursors disabled
  HREL  — relative horizontal cursors (measures ΔX)
  HABS  — absolute horizontal cursors (measures X position)
  VREL  — relative vertical cursors (measures ΔY)
  VABS  — absolute vertical cursors (measures Y position)
Readouts: ABS, DELTA, SLOPE

Positioning cursors  (CRST / CURSOR_SET)
------------------------------------------
Set:   C<n>:CRST <cursor>,<position>
Valid cursors: HABS, HREF, HDIF, VABS, VREF, VDIF
Position: 0–10 DIV (horizontal), -3.99–3.99 DIV (vertical)
Example: C1:CRST HREF,3.5,HDIF,6.5   → place two H cursors at 3.5 and 6.5 div

Reading cursor values  (CRVA / CURSOR_VALUE)
----------------------------------------------
Query: C<n>:CRVA? [<mode>]
Mode: HABS, HREL, VABS, VREL
Returns measured value at cursor position (time or voltage).

Cursor/parameter measurement mode  (CRMS / CURSOR_MEASURE)
------------------------------------------------------------
Set:   CRMS <mode>[,<submode>]
Modes: CUST, FAIL, HABS, HPAR, HREL, OFF, PASS, VABS, VPAR, VREL
Query: CRMS?
""")

DOCS["screenshot"] = (
    "Screenshot / Hardcopy Commands",
    """\
Screenshot / Hardcopy Commands
================================

Setup  (HCSU / HARDCOPY_SETUP)
--------------------------------
Configure before capturing:
  HCSU DEV,<format>,FORMAT,<orient>,BCKG,<bg>,DEST,REMOTE,AREA,<area>
Parameters:
  DEV    format:  BMP, JPEG, PNG, TIFF
  FORMAT orient:  PORTRAIT, LANDSCAPE
  BCKG   bg:      BLACK, WHITE
  DEST:           PRINTER, CLIPBOARD, EMAIL, FILE, REMOTE
                  Use REMOTE to transfer image data to the controller over VISA.
  AREA:           DSOWINDOW    — oscilloscope window only (default)
                  GRIDAREAONLY — waveform grid only, no controls
                  FULLSCREEN   — entire desktop

Query: HCSU?

Capture  (SCDP / SCREEN_DUMP)
-------------------------------
Command: SCDP
After SCREEN_DUMP, read back the binary image data using read_raw().
The response starts with an IEEE 488.2 block header: #N<len><data>.
Strip the header before writing bytes to a file.

Example sequence:
  HCSU DEV,PNG,FORMAT,LANDSCAPE,BCKG,WHITE,DEST,REMOTE,AREA,DSOWINDOW
  SCDP
  <read raw bytes from VISA>
  <strip #N<len> header>
  <write remainder to .png file>
""")

DOCS["system"] = (
    "System & Utility Commands",
    """\
System & Utility Commands
==========================

Identification  (*IDN?)
-------------------------
Query: *IDN?
Response: *IDN LECROY,<model>,<serial>,<firmware>
Example: *IDN LECROY,WAVESURFER3024Z,LCRY1234567,11.2.0

Reset  (*RST)
--------------
Command: *RST
Resets instrument to factory defaults.
Clears all waveforms, measurements, and non-stored settings.

Self-calibration  (*CAL?)
---------------------------
Query: *CAL?
Returns diagnostic code:
  0  — success
  1  — channel 1 error
  2  — channel 2 error
  4  — channel 3 error
  8  — channel 4 error
  16 — TDC failure
  32 — trigger failure
  64 — other failure

Options  (*OPT?)
-----------------
Query: *OPT?
Returns installed software/hardware options, or "0" if none.

Date and time  (DATE)
----------------------
Query: DATE?
Set from internet: DATE SNTP

Buzzer  (BUZZ / BUZZER)
------------------------
BUZZ BEEP     — short beep
BUZZ ON       — enable beep on trigger
BUZZ OFF      — disable trigger beep

Panel lock  (PNLK / PANEL_LOCK)   [not on all models]
-------------------------------------------------------
Set:   PNLK ON | OFF
Locks front-panel controls to prevent accidental changes during automation.

Save/recall panel setup
------------------------
Save to slot:    *SAV <n>     (n = 1 to max_panels)
Recall slot:     *RCL <n>     (n = 0 = factory default)
Recall factory:  *RCL 0
Save to file:    STPN DISK,HDD,FILE,'setup.lss'
Load from file:  RCPN DISK,HDD,FILE,'setup.lss'

Remote control diagnostics  (CHLP / COMM_HELP)
------------------------------------------------
CHLP EO,NO    — log errors only, reset off at power-on
CHLP FD,NO    — full dialog logging
CHLP OFF,NO   — disable logging
CHLP?         — query current setting
CHL?          — retrieve log contents (append CLR to clear after reading)

VBS automation  (VBS)
----------------------
LeCroy scopes expose a COM automation object in addition to raw SCPI:
  VBS 'app.Acquisition.Horizontal.HorScale = 0.001'
  VBS? 'Return=app.Acquisition.Horizontal.HorScale'
Raw SCPI (as used by this MCP server) is preferred for simplicity.
""")


DOCS["wavesource"] = (
    "WaveSource Built-in Generator (VBS automation)",
    """\
WaveSource Built-in Generator
==============================

The WaveSource is an optional built-in function generator available on
WaveSurfer 3000Z and other models.  It has no dedicated SCPI commands —
it is controlled exclusively via VBS automation (app.WaveSource.*).

Use scope_capabilities to check has_wavesource before using these tools.
The dedicated MCP tools (scope_wavesource_*) wrap the VBS calls below.

Properties (confirmed on WS3024Z firmware 11.2.0)
---------------------------------------------------
app.WaveSource.Enable       — -1 = on, 0 = off  (VBScript boolean)
app.WaveSource.Shape        — waveform type (string, see shapes below)
app.WaveSource.Frequency    — frequency in Hz (float)
app.WaveSource.Amplitude    — peak-to-peak amplitude in V (float)
app.WaveSource.Offset       — DC offset in V (float)
app.WaveSource.Load         — output load: "HiZ" or "50" (50 Ω)
app.WaveSource.DutyCycle    — duty cycle in % (float, Square/Pulse only)
app.WaveSource.Symmetry     — symmetry in % (float, Triangle only)
app.WaveSource.StdDev       — noise standard deviation (float, Noise only)

Waveform shapes
---------------
"Sine"     — sinusoidal
"Square"   — square wave (use DutyCycle to adjust)
"Triangle" — triangle wave (use Symmetry to adjust)
"Pulse"    — pulse (use DutyCycle for width)
"DC"       — constant DC level (set with Offset)
"Noise"    — pseudo-random noise (set StdDev for amplitude)
"Arb"      — arbitrary waveform from .csv file

Reading / writing via raw VBS
------------------------------
Query:  VBS? 'Return=app.WaveSource.Frequency'
Set:    VBS 'app.WaveSource.Frequency = 1000'
Set str: VBS 'app.WaveSource.Shape = "Sine"'

Note: scope_write("COMM_HEADER OFF") before raw VBS queries avoids
the "VBS" header prefix appearing in query responses.
""")


def get_topic(slug: str) -> str | None:
    """Return formatted documentation for a topic slug, or None if not found."""
    entry = DOCS.get(slug.lower())
    if entry is None:
        return None
    _title, content = entry
    return content


def all_slugs() -> list[str]:
    return list(DOCS.keys())


def help_index() -> str:
    lines = ["Available documentation topics:", ""]
    for slug, (title, _) in DOCS.items():
        lines.append(f"  {slug:15s} — {title}")
    lines.append("")
    lines.append("Use scope_help('<topic>') to read any of these topics.")
    return "\n".join(lines)
