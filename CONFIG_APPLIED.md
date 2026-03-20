# E220 Module Configuration (2026-03-21)

## Status: ✅ SUCCESSFULLY APPLIED

### Configuration Settings
```
Address:               0
Channel:               30 (930.125 MHz)
UART Baud Rate:        115200 bps (index 7)
UART Parity:           8N1 (index 0)
Air Data Rate:         62.5 kbps (index 5)
Transmission Power:    27 dBm (index 1)
Packet Length:         240 bytes (index 0)
Wake-up Time:          500 ms (index 0)
Fixed Transmission:    Disabled
Listen Before Talk:    Disabled
Data RSSI:             Disabled
Software Mode Switch:  Disabled
```

### Applied Via
```bash
python e220-configurator.py --cli --port /dev/ttyUSB0 --baudrate 9600 write \
  --address 0 \
  --channel 30 \
  --uart-baud 7 \
  --parity 0 \
  --air-rate 5 \
  --power 1 \
  --packet 0 \
  --wake-time 0
```

### Verification
Configuration verified via read-back command:
```bash
python e220-configurator.py --cli --port /dev/ttyUSB0 --baudrate 9600 read
```

All parameters match applied values. Configuration saved to flash.

### Notes
- Device connected at `/dev/ttyUSB0`
- Configuration baudrate: 9600 bps
- Module firmware quirk: Echoes 0xC1 on writes (accepted)
- M0/M1 pins must be set to 0/0 for normal operation (not automated via GPIO)
