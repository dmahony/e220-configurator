# E220-915MHz LoRa Module Configurator

A cross-platform application for configuring EBYTE E220 series LoRa modules. This tool provides both a GUI and CLI interface for complete module configuration and testing.

![E220 LoRa Module](https://i.imgur.com/example.jpg)

## Features

- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Dual Interface**: Both graphical (GUI) and command-line (CLI) interfaces
- **Complete Configuration**: Full access to all module parameters
- **Real-Time Testing**: Send and receive data directly from the interface
- **Parameter Saving/Loading**: Save configurations to files and load them later
- **Automatic Port Detection**: Automatically finds available serial ports
- **Optional GPIO Control**: Direct control of module pins on compatible hardware (e.g., Raspberry Pi)

## Supported Modules

- E220-400T22S/E220-400T30S (433MHz versions)
- E220-400T22D/E220-400T30D (433MHz versions) 
- E220-900T22S/E220-900T30S (868/915MHz versions)
- E220-900T22D/E220-900T30D (868/915MHz versions)

## Installation

### Prerequisites

- Python 3.6 or higher
- pip (Python package manager)

### Installing Dependencies

```bash
pip install pyserial
```

If you want to use the GUI:
```bash
pip install tk  # On some systems, tkinter is bundled with Python
```

For GPIO control on Raspberry Pi:
```bash
pip install RPi.GPIO
```

### Installing the Application

1. Clone this repository or download the source code:
```bash
git clone https://github.com/yourusername/e220-configurator.git
cd e220-configurator
```

2. Run the application:
```bash
python e220_configurator.py
```

## Hardware Connection

### Basic Connection (USB-to-Serial Adapter)

| E220 Module | USB-TTL Adapter | Notes |
|-------------|-----------------|-------|
| M0          | GPIO or GND/VCC | Pull HIGH for config mode |
| M1          | GPIO or GND/VCC | Pull HIGH for config mode |
| RXD         | TXD             | Cross-connected |
| TXD         | RXD             | Cross-connected |
| AUX         | GPIO (optional) | Status indicator |
| VCC         | 3.3V-5.5V       | Power supply (5V recommended) |
| GND         | GND             | Ground reference |

### Configuration Mode

To put the module in configuration mode (for parameter settings):
- Set M0 = HIGH
- Set M1 = HIGH

### Normal Operation Mode

For normal transparent transmission:
- Set M0 = LOW
- Set M1 = LOW

## Usage

### GUI Mode

1. Run the application without any arguments:
```bash
python e220_configurator.py
```

2. Select the serial port from the dropdown menu
3. Set the baud rate (default is 9600)
4. Click "Connect" to establish a connection with the module
5. Navigate through the tabs to configure settings:
   - **Basic Settings**: Address, channel, baud rate, parity, air rate, and transmit power
   - **Advanced Settings**: Transmission mode, wake-up time, packet length, and E220-specific features
   - **Monitor**: Monitor received data and send test messages

### CLI Mode

The configurator also offers a powerful command-line interface:

```bash
python e220_configurator.py --cli [options] command
```

Available commands:

- `read`: Read and display module parameters
```bash
python e220_configurator.py --cli --port COM3 read
python e220_configurator.py --cli --port /dev/ttyUSB0 read --output params.json
```

- `write`: Write parameters to the module
```bash
python e220_configurator.py --cli --port COM3 write --address 1234 --channel 23
python e220_configurator.py --cli --port COM3 write --input params.json
```

- `reset`: Reset the module
```bash
python e220_configurator.py --cli --port COM3 reset
```

- `factory-reset`: Reset the module to factory defaults
```bash
python e220_configurator.py --cli --port COM3 factory-reset
```

- `version`: Get module version information
```bash
python e220_configurator.py --cli --port COM3 version
```

- `save-config`: Save current module configuration to file
```bash
python e220_configurator.py --cli --port COM3 save-config --output config.json
```

- `load-config`: Load and apply configuration from file
```bash
python e220_configurator.py --cli --port COM3 load-config --input config.json
```

- `scan-ports`: Scan and display available serial ports
```bash
python e220_configurator.py --cli scan-ports
```

- `send-data`: Send data through the module
```bash
python e220_configurator.py --cli --port COM3 send-data --data "Hello LoRa!"
```

## Parameter Explanation

### Basic Parameters

- **Address (0-65535)**: Module address for fixed-point transmission
- **Channel (0-80)**: Frequency channel, calculated as 850.125MHz + Channel*1MHz for 915MHz modules
- **UART Baud Rate**: Communication speed between module and host
  - Options: 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200 bps
- **UART Parity**: Serial port parity setting
  - Options: 8N1, 8O1, 8E1
- **Air Rate**: Wireless transmission speed
  - Options: 2.4k, 4.8k, 9.6k, 19.2k, 38.4k, 62.5k bps
- **Transmit Power**: RF output power
  - Options: 30dBm (max), 27dBm, 24dBm, 21dBm

### Advanced Parameters

- **Transmission Mode**: 
  - Transparent: All serial data is transmitted as received
  - Fixed-Point: Data is transmitted with address and channel headers
- **Wake-up Time**: Period between wake-ups in WOR mode
  - Options: 500ms, 1000ms, 1500ms, 2000ms, 2500ms, 3000ms, 3500ms, 4000ms
- **Packet Length**: Maximum bytes per wireless packet
  - Options: 200 bytes, 128 bytes, 64 bytes, 32 bytes
- **Listen Before Talk (LBT)**: Check channel before transmitting
- **Ambient Noise RSSI**: Enable ambient noise RSSI monitoring
- **Data RSSI**: Append RSSI byte to received data
- **Software Mode Switching**: Enable mode switching via AT commands

## Operating Modes

The E220 module has 4 operating modes controlled by M0 and M1 pins:

- **Mode 0 (M0=0, M1=0)**: Normal mode - UART and wireless channels are open for transparent transmission
- **Mode 1 (M0=0, M1=1)**: WOR transmit mode - Sends data with wake-up code for WOR receivers
- **Mode 2 (M0=1, M1=0)**: WOR receive mode - Listens periodically to save power
- **Mode 3 (M0=1, M1=1)**: Sleep/configuration mode - For settings configuration via AT commands

## Troubleshooting

### Module Not Responding
- Ensure the module is properly powered (3.3V-5.5V)
- Verify the serial connections (TXD → RXD, RXD → TXD)
- Confirm M0 and M1 are both HIGH for configuration mode
- Try a different baud rate (default is 9600bps)

### Cannot Write Parameters
- Ensure you're in configuration mode (M0=HIGH, M1=HIGH)
- Check that the parameter values are within valid ranges
- Verify the serial connection is stable

### Poor Transmission Performance
- Adjust the transmission power
- Try a lower air data rate for better range
- Ensure antennas are properly connected and positioned
- Verify modules are using the same channel and air rate

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- EBYTE for the E220 module documentation
- Contributors to the project

---

*Disclaimer: This tool is not officially associated with EBYTE. Use at your own risk.*
