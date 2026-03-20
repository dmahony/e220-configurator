# E220 Module Hardware/Firmware Issues

## Issue 1: Transmit Power Register Write Failure

**Status:** CONFIRMED BUG / HARDWARE LIMITATION

**Description:**
The transmit power register (0x04, bits 7-6) cannot be modified on this E220 module.
All attempts to write power indices 0, 1, 2, or 3 result in the module returning 27 dBm.

**Testing Results:**
```
Write Index 0 (30 dBm) → Read Back: 27 dBm
Write Index 1 (27 dBm) → Read Back: 27 dBm  
Write Index 2 (24 dBm) → Read Back: 27 dBm
Write Index 3 (21 dBm) → Read Back: 27 dBm
```

**Evidence:**
- Module accepts the write command (echoes 0xC1 with correct data)
- Register write protocol executes without errors
- Subsequent reads show power has reverted/not changed
- Occurs consistently across all power indices

**Root Cause Options:**
1. E220 module firmware bug in power register handling
2. Hardware limitation specific to this module batch
3. E220-900T30S variant limitation (data sheet might show only fixed power output)

**Module Identifier:**
```
Device: CP2102 USB to UART at /dev/ttyUSB0
Registers: 00 00 E0 A4 53 1E 00 00
Power Register: 0x53 (bits 7-6 = 01 = 27 dBm, locked)
```

**Workaround:**
Module operates at fixed 27 dBm. No software workaround available.

**Recommendation:**
- Check E220 datasheet for power output specifications (may be single fixed output)
- Consider firmware update from eByte if available
- If multiple power levels required, test with different E220 batch/model

## Date Tested
2026-03-21
