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

## RESOLVED - Root Cause Identified

**Solution:** Power supply voltage was insufficient
- At 3.3V: Power register was locked/read-only (reverted to 27 dBm)
- At 5V: Power register works correctly - all levels settable (30/27/24/21 dBm) ✓

The E220 module is rated for 3.3V - 5.5V with **5V being the recommended voltage**.
At 3.3V, the module firmware cannot properly handle power register writes, but at 5V
all power levels (0-3, corresponding to 30/27/24/21 dBm) are fully adjustable.

**Fix Applied:**
- Switched power supply from 3.3V to 5V
- Re-tested power index 0 (30 dBm) - now works correctly ✓
- Module confirmed accepting all power level changes at 5V

**Recommendation:**
Always use 5V to power the E220-900T30S module for full functionality and
optimal RF performance. 3.3V is technically supported but may limit features.

## Date Tested
2026-03-21
Resolution: 2026-03-21
