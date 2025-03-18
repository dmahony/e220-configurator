# E220 LoRa Module Configurator - Quick Start Guide

This guide will help you quickly set up and start using the E220 LoRa Module Configurator for your EBYTE E220 series modules.

## 1. Installation

### Prerequisites
- Python 3.6 or higher installed
- USB-to-UART/TTL adapter for connecting to the E220 module

### Steps
1. Download the software:
   ```bash
   git clone https://github.com/username/e220-configurator.git
   cd e220-configurator
   ```

2. Install required dependencies:
   ```bash
   pip install pyserial
   ```

3. For Raspberry Pi GPIO support (optional):
   ```bash
   pip install RPi.GPIO
   ```

## 2. Hardware Connection

Connect your E220 module to your computer:

1. Standard connection (manual mode control):
   - USB-UART TX → E220 RX
   - USB-UART RX → E220 TX
   - USB-UART GND → E220 GND
   - USB-UART VCC (3.3V-5V) → E220 VCC
   - Set E220 M0 and M1 pins both HIGH for configuration mode

2. Raspberry Pi connection with GPIO (automatic mode control):
   - Same UART connections as above
   - Raspberry Pi GPIO pin (default: 16) → E220 M0
   - Raspberry Pi GPIO pin (default: 17) → E220 M1
   - Raspberry Pi GPIO pin (default: 22) → E220 AUX (optional)

## 3. Starting the Application

### GUI Mode
```bash
python e220_config.py
```

### CLI Mode
```bash
# Scan for available serial ports
python e220_config.py --cli scan-ports

# Read current configuration
python e220_config.py --cli --port COM3 read
```

## 4. Basic Configuration (GUI)

1. Connect to the module:
   - Select your COM port from the dropdown list
   - Set the baud rate (default: 9600)
   - Click "Connect"

2. Read current configuration:
   - After connecting, the application will attempt to read the current settings
   - If successful, all parameters will be populated in the interface

3. Modify settings:
   - Change parameters as needed in the "Basic Settings" tab
   - For more advanced options, use the "Advanced Settings" tab

4. Write configuration:
   - Click "Write to Module" to save changes
   - If changing the baud rate, you'll need to disconnect and reconnect at the new rate

5. Save your configuration:
   - Click "Save Config" to store your settings in a JSON file for future use

## 5. Common Configuration Scenarios

### Creating a Paired Set of Modules
To set up two modules to communicate with each other:

1. Set both modules to the same channel
2. Set both modules to the same air rate
3. For transparent transmission (default):
   - No address configuration needed
4. For fixed-point transmission:
   - Set unique addresses for each module
   - Set transmission mode to "Fixed Point"

### Optimizing for Long Range
For maximum transmission distance:

1. Set air rate to 2.4 kbps (rate index 0, 1, or 2)
2. Set transmit power to maximum (power index 0)
3. Use high-quality antennas

### Low Power Configuration
For battery-powered applications:

1. Set up WOR (Wake-on-Radio) mode:
   - One module as WOR transmitter (WOR role index 1)
   - Other module(s) as WOR receiver (WOR role index 0)
2. Increase WOR period to reduce power consumption
3. Reduce transmit power if range requirements allow

## 6. Command Line Examples

```bash
# Save current configuration to file
python e220_config.py --cli --port COM3 save-config -o myconfiguration.json

# Load configuration from file
python e220_config.py --cli --port COM3 load-config -i myconfiguration.json

# Set address and channel
python e220_config.py --cli --port COM3 write --address 1234 --channel 10

# Reset module
python e220_config.py --cli --port COM3 reset

# Factory reset
python e220_config.py --cli --port COM3 factory-reset

# Get help
python e220_config.py --help
```

## 7. Troubleshooting

- **Can't connect to module**
  - Verify correct COM port selected
  - Check that module is powered
  - Ensure M0 and M1 pins are both HIGH for configuration mode
  - Try a different baud rate

- **Module not responding to commands**
  - Disconnect and reconnect the module
  - Check TX/RX connections (may need to be swapped)
  - Try resetting the module

- **Changes don't take effect**
  - Some changes require a module reset
  - Verify that parameters were successfully written

## Next Steps

- Explore advanced features in the "Advanced Settings" tab
- Try the command console for direct AT command access
- Save your configurations for different use cases
