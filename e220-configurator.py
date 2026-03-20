#!/usr/bin/env python3
"""
E220-915MHz LoRa Module Configurator
-----------------------------------
A cross-platform application for configuring EBYTE E220 series LoRa modules.
Specifically optimized for the 915MHz version.
Provides both GUI and CLI interfaces for complete module configuration.

Usage:
    - Run without arguments to open the GUI
    - Run with --cli argument to use the command-line interface
    - Run with --help to see all available CLI options
"""

import argparse
import sys
import time
import threading
import json
import os
import serial
import serial.tools.list_ports
from enum import Enum, auto
import logging

# GUI imports - wrapped in try/except to allow CLI-only usage if GUI dependencies are missing
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, scrolledtext
    import tkinter.font as tkFont
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("E220-Configurator")

# Version information
__version__ = "1.1.0"

# ============================================================================
# E220 Binary Register Protocol Constants
# ============================================================================

# Register addresses (single-byte address space)
REG_ADDH        = 0x00  # Address high byte (0-255)
REG_ADDL        = 0x01  # Address low byte (0-255)
REG_UART        = 0x02  # Serial port: baud rate, parity
REG_AIR_RATE    = 0x03  # Air data rate, subpacket length
REG_POWER       = 0x04  # Transmit power
REG_CHANNEL     = 0x05  # Channel (0-80 for 915MHz)
REG_OPTIONS     = 0x06  # RSSI, transmission mode, WOR, LBT
REG_WOR         = 0x07  # WOR wake-up period

# UART command bytes
CMD_READ        = 0xC1  # Read registers: [CMD_READ, start_reg, count]
CMD_WRITE       = 0xC0  # Write registers: [CMD_WRITE, start_reg, count, data...]
CMD_SAVE        = 0xC4  # Save parameters to flash (if supported by module)
CMD_RESET       = 0xC2  # Software reset

# Register block size
REG_BLOCK_SIZE  = 8     # Registers 0x00-0x07

# Frequency calculation (MHz) for 915MHz modules (E220-900T30S/T22S)
FREQ_BASE       = 900.125
FREQ_STEP       = 1.0   # 1 MHz per channel

# UART baud rate index → actual baud
UART_BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

# Air data rate index → actual rate
AIR_DATA_RATES  = [2400, 4800, 9600, 19200, 38400, 62500]

# Air data rate labels
AIR_RATE_LABELS = ["2.4 kbps", "4.8 kbps", "9.6 kbps", "19.2 kbps", "38.4 kbps", "62.5 kbps"]

# Transmit power index → dBm
TX_POWER_DBM    = [30, 27, 24, 21]
TX_POWER_LABELS = ["30 dBm (max)", "27 dBm", "24 dBm", "21 dBm"]

# Parity index → label
PARITY_LABELS   = ["8N1", "8O1", "8E1"]

# Wake-up time index → milliseconds
WAKE_TIME_MS    = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000]
WAKE_TIME_LABELS = ["500ms", "1000ms", "1500ms", "2000ms", "2500ms", "3000ms", "3500ms", "4000ms"]

# Packet length index → bytes
PACKET_LENGTHS  = [240, 128, 64, 32]
PACKET_LABELS   = ["240 bytes", "128 bytes", "64 bytes", "32 bytes"]


class ModuleMode(Enum):
    """E220 operating modes based on M0 and M1 pins

    E220 pin assignments:
      Mode 0 - Normal:        M0=0, M1=0  (transparent transmission)
      Mode 1 - WOR Transmit:  M0=1, M1=0  (sends with wake-up code)
      Mode 2 - WOR Receive:   M0=0, M1=1  (periodic listen for wake-up)
      Mode 3 - Configuration: M0=1, M1=1  (sleep / AT config mode)
    """
    NORMAL = auto()          # M0=0, M1=0
    WOR_TRANSMIT = auto()    # M0=1, M1=0
    WOR_RECEIVE = auto()     # M0=0, M1=1
    CONFIGURATION = auto()   # M0=1, M1=1


# ============================================================================
# Register Parsing Helpers
# ============================================================================

def _parse_registers(regs):
    """Parse 8-byte E220 register block into a parameters dict.

    Args:
        regs: list/array of 8 bytes (registers 0x00-0x07)

    Returns:
        dict of parsed parameter names to values
    """
    if len(regs) < REG_BLOCK_SIZE:
        raise ValueError(f"Expected {REG_BLOCK_SIZE} register bytes, got {len(regs)}")

    p = {}

    # Address (16-bit)
    p["address"] = (regs[REG_ADDH] << 8) | regs[REG_ADDL]

    # UART config (register 0x02)
    #   Bits 7-5: baud rate (0-7)
    #   Bits 4-3: parity (0=8N1, 1=8O1, 2=8E1)
    #   Bits 2-0: reserved / stop bits (usually 0)
    uart_reg = regs[REG_UART]
    p["uart_baud"] = (uart_reg >> 5) & 0x07
    p["parity"]    = (uart_reg >> 3) & 0x03

    # Air rate config (register 0x03)
    #   Bits 7-5: air data rate
    #   Bits 4-3: subpacket length (0=240, 1=128, 2=64, 3=32)
    #   Bit  2:   RSSI ambient noise enable
    air_reg = regs[REG_AIR_RATE]
    p["air_data_rate"]   = (air_reg >> 5) & 0x07
    p["packet"]          = (air_reg >> 3) & 0x03
    p["rssi_noise_en"]   = (air_reg >> 2) & 0x01  # ERSSI

    # Transmit power (register 0x04)
    #   Bits 7-6: transmit power (0=30dBm, 1=27, 2=24, 3=21)
    #   Bits 5-0: reserved
    power_reg = regs[REG_POWER]
    p["transmission_power"] = (power_reg >> 6) & 0x03

    # Channel (register 0x05)
    p["chan"] = regs[REG_CHANNEL]
    p["frequency"] = FREQ_BASE + p["chan"] * FREQ_STEP

    # Options (register 0x06)
    #   Bit 7:    RSSI byte enable (DRSSI) - append RSSI to received data
    #   Bit 6:    Transmission mode (0=transparent, 1=fixed-point)
    #   Bits 5-3: WOR wake-up time (0-7)
    #   Bit 2:    LBT enable (listen before talk)
    #   Bits 1-0: reserved
    opt_reg = regs[REG_OPTIONS]
    p["drssi"]             = (opt_reg >> 7) & 0x01
    p["fixed_transmission"]= (opt_reg >> 6) & 0x01
    p["wake_up_time"]      = (opt_reg >> 3) & 0x07
    p["lbt"]               = (opt_reg >> 2) & 0x01

    # WOR period (register 0x07)
    #   Bits 7-0: WOR cycle period (low 8 bits, meaning depends on module)
    p["wor_period"] = regs[REG_WOR]

    # Software mode switching (if supported) — typically a separate register
    # or a flag within options. Default to 0 if not found.
    p["sw_switch"] = 0

    return p


def _build_registers(params, existing_regs=None):
    """Build an 8-byte register block from a parameters dict.

    Args:
        params: dict of parameter names to set (only provided keys are changed)
        existing_regs: optional existing register values to merge with

    Returns:
        list of 8 bytes ready to write
    """
    # Start with existing or zeros
    if existing_regs and len(existing_regs) >= REG_BLOCK_SIZE:
        regs = list(existing_regs[:REG_BLOCK_SIZE])
    else:
        regs = [0x00] * REG_BLOCK_SIZE

    # Address
    if "address" in params:
        addr = int(params["address"])
        regs[REG_ADDH] = (addr >> 8) & 0xFF
        regs[REG_ADDL] = addr & 0xFF

    # UART config
    if "uart_baud" in params or "parity" in params:
        baud = int(params.get("uart_baud", (regs[REG_UART] >> 5) & 0x07))
        parity = int(params.get("parity", (regs[REG_UART] >> 3) & 0x03))
        regs[REG_UART] = ((baud & 0x07) << 5) | ((parity & 0x03) << 3)

    # Air rate config
    if "air_data_rate" in params or "packet" in params or "rssi_noise_en" in params:
        rate = int(params.get("air_data_rate", (regs[REG_AIR_RATE] >> 5) & 0x07))
        pkt = int(params.get("packet", (regs[REG_AIR_RATE] >> 3) & 0x03))
        noise = int(params.get("rssi_noise_en", (regs[REG_AIR_RATE] >> 2) & 0x01))
        regs[REG_AIR_RATE] = ((rate & 0x07) << 5) | ((pkt & 0x03) << 3) | ((noise & 0x01) << 2)

    # Transmit power
    if "transmission_power" in params:
        pwr = int(params["transmission_power"])
        regs[REG_POWER] = ((pwr & 0x03) << 6) | (regs[REG_POWER] & 0x3F)

    # Channel
    if "chan" in params:
        regs[REG_CHANNEL] = int(params["chan"]) & 0xFF

    # Options register
    if any(k in params for k in ("drssi", "fixed_transmission", "wake_up_time", "lbt")):
        # Merge with existing values
        opt = regs[REG_OPTIONS]
        if "drssi" in params:
            opt = (opt & 0x7F) | ((int(params["drssi"]) & 0x01) << 7)
        if "fixed_transmission" in params:
            opt = (opt & 0xBF) | ((int(params["fixed_transmission"]) & 0x01) << 6)
        if "wake_up_time" in params:
            opt = (opt & 0xC7) | ((int(params["wake_up_time"]) & 0x07) << 3)
        if "lbt" in params:
            opt = (opt & 0xFB) | ((int(params["lbt"]) & 0x01) << 2)
        regs[REG_OPTIONS] = opt

    # WOR period
    if "wor_period" in params:
        regs[REG_WOR] = int(params["wor_period"]) & 0xFF

    return regs


def _compute_checksum(data):
    """Compute 8-bit checksum (sum of all bytes, masked to 8 bits)."""
    return sum(data) & 0xFF


# ============================================================================
# E220 Module Class
# ============================================================================

class E220Module:
    """
    Handles communication with the E220 LoRa module using binary register protocol.
    """
    def __init__(self, port=None, baudrate=9600, timeout=1, m0_pin=None, m1_pin=None, aux_pin=None, use_gpio=False, manual_config=False):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None
        self.current_mode = None

        # GPIO pins for module control (optional, for Raspberry Pi or similar)
        self.m0_pin = m0_pin
        self.m1_pin = m1_pin
        self.aux_pin = aux_pin
        self.use_gpio = use_gpio

        # Flag to indicate if the user has manually set configuration mode
        self.manual_config = manual_config

        # Initialize GPIO if available and requested
        if self.use_gpio:
            try:
                import RPi.GPIO as GPIO
                self.GPIO = GPIO
                self.GPIO.setmode(GPIO.BCM)
                if self.m0_pin:
                    self.GPIO.setup(self.m0_pin, GPIO.OUT)
                if self.m1_pin:
                    self.GPIO.setup(self.m1_pin, GPIO.OUT)
                if self.aux_pin:
                    self.GPIO.setup(self.aux_pin, GPIO.IN)
                logger.info("GPIO initialized for module control")
            except ImportError:
                logger.warning("GPIO library not available. Cannot control module pins directly.")
                self.use_gpio = False

    def connect(self):
        """Connect to the LoRa module"""
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            logger.info(f"Connected to port {self.port} at {self.baudrate} baud")
            return True
        except serial.SerialException as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def disconnect(self):
        """Disconnect from the LoRa module"""
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info("Disconnected from module")

    def _set_mode_pins(self, mode):
        """Set M0 and M1 pins for the specified mode.

        E220 mode/pin mapping:
          Normal:        M0=LOW,  M1=LOW
          WOR Transmit:  M0=HIGH, M1=LOW
          WOR Receive:   M0=LOW,  M1=HIGH
          Configuration: M0=HIGH, M1=HIGH
        """
        if not self.use_gpio or not (self.m0_pin and self.m1_pin):
            logger.warning("Cannot set mode pins: GPIO control not available or pins not specified")
            logger.info("Please ensure M0 and M1 pins are set correctly manually")
            # Return True to allow operation to continue if user has manually set the pins
            return True

        if mode == ModuleMode.NORMAL:
            self.GPIO.output(self.m0_pin, GPIO.LOW)
            self.GPIO.output(self.m1_pin, GPIO.LOW)
        elif mode == ModuleMode.WOR_TRANSMIT:
            self.GPIO.output(self.m0_pin, GPIO.HIGH)
            self.GPIO.output(self.m1_pin, GPIO.LOW)
        elif mode == ModuleMode.WOR_RECEIVE:
            self.GPIO.output(self.m0_pin, GPIO.LOW)
            self.GPIO.output(self.m1_pin, GPIO.HIGH)
        elif mode == ModuleMode.CONFIGURATION:
            self.GPIO.output(self.m0_pin, GPIO.HIGH)
            self.GPIO.output(self.m1_pin, GPIO.HIGH)
        else:
            logger.error(f"Invalid mode: {mode}")
            return False

        # Wait for AUX pin to go HIGH if available
        if self.aux_pin:
            timeout = 100  # 1 second (10ms * 100)
            while timeout > 0 and not self.GPIO.input(self.aux_pin):
                time.sleep(0.01)
                timeout -= 1

            if timeout <= 0:
                logger.warning("Timeout waiting for AUX pin to go HIGH")

        # Additional delay to ensure mode switch is complete
        time.sleep(0.1)
        return True

    def set_mode(self, mode):
        """Set the module's operating mode"""
        if self.current_mode == mode:
            logger.debug(f"Module already in {mode} mode")
            return True

        # For configuration mode, check if it's already in that mode
        if mode == ModuleMode.CONFIGURATION and self._check_config_mode():
            logger.info("Module already in configuration mode")
            self.current_mode = ModuleMode.CONFIGURATION
            return True

        logger.info(f"Setting module to {mode} mode")
        result = self._set_mode_pins(mode)
        if result:
            self.current_mode = mode

        return result

    def _read_raw(self, num_bytes, timeout=1.0):
        """Read raw bytes from serial port with timeout."""
        if not self.serial or not self.serial.is_open:
            return None

        data = bytearray()
        start = time.time()
        while len(data) < num_bytes and (time.time() - start) < timeout:
            chunk = self.serial.read(num_bytes - len(data))
            if chunk:
                data.extend(chunk)
            else:
                time.sleep(0.01)
        return bytes(data)

    def _send_command(self, cmd_bytes, expected_response_len=None, timeout=1.0):
        """Send a binary command and read the response.

        Args:
            cmd_bytes: bytes to send
            expected_response_len: expected number of response bytes (None to read what's available)
            timeout: read timeout in seconds

        Returns:
            response bytes, or None on failure
        """
        if not self.serial or not self.serial.is_open:
            logger.error("Not connected to module")
            return None

        # Clear any pending data
        self.serial.reset_input_buffer()

        # Send command
        logger.debug(f"Sending: {' '.join(f'0x{b:02X}' for b in cmd_bytes)}")
        self.serial.write(bytes(cmd_bytes))

        # Read response
        if expected_response_len:
            response = self._read_raw(expected_response_len, timeout)
        else:
            # Read whatever comes back
            time.sleep(0.05)
            avail = self.serial.in_waiting
            response = self.serial.read(avail) if avail else b""

        if response:
            logger.debug(f"Response: {' '.join(f'0x{b:02X}' for b in response)}")
        else:
            logger.warning("No response received")

        return bytes(response) if response else None

    def _read_registers(self, start_reg=0x00, count=REG_BLOCK_SIZE):
        """Read registers from the module using 0xC1 command.

        Returns:
            list of register byte values, or None on failure
        """
        cmd = [CMD_READ, start_reg, count]
        # Response: [0xC1, start_reg, count, reg0, reg1, ...]
        expected_len = 3 + count
        response = self._send_command(cmd, expected_len, timeout=1.5)

        if not response or len(response) < expected_len:
            logger.error(f"Invalid read response: got {len(response) if response else 0} bytes, expected {expected_len}")
            return None

        # Verify response header
        if response[0] != CMD_READ:
            logger.error(f"Bad response header: 0x{response[0]:02X}, expected 0xC1")
            return None

        if response[1] != start_reg or response[2] != count:
            logger.error(f"Response address/count mismatch")
            return None

        # Extract register values
        regs = list(response[3:3 + count])
        logger.debug(f"Read registers: {' '.join(f'0x{r:02X}' for r in regs)}")
        return regs

    def _write_registers(self, regs, start_reg=0x00):
        """Write registers to the module using 0xC0 command.

        Args:
            regs: list of byte values to write
            start_reg: starting register address

        Returns:
            True on success, False on failure
        """
        count = len(regs)
        cmd = [CMD_WRITE, start_reg, count] + list(regs)
        # Expect echo: [0xC0, start_reg, count, reg0, reg1, ...]
        expected_len = 3 + count
        response = self._send_command(cmd, expected_len, timeout=1.5)

        if not response or len(response) < expected_len:
            logger.error(f"Invalid write response: got {len(response) if response else 0} bytes, expected {expected_len}")
            return False

        # Verify echo matches what we wrote
        if response[0] != CMD_WRITE:
            logger.error(f"Bad write response header: 0x{response[0]:02X}")
            return False

        echo_regs = list(response[3:3 + count])
        if echo_regs != list(regs):
            logger.error(f"Write echo mismatch: sent {regs}, got {echo_regs}")
            return False

        logger.info("Write confirmed")
        return True

    def enter_config_mode(self):
        """Enter configuration mode for sending commands"""
        # First check if the module is already in configuration mode
        if self._check_config_mode():
            logger.info("Module already in configuration mode")
            self.current_mode = ModuleMode.CONFIGURATION
            return True
        # If not, try to set the mode using pins
        return self.set_mode(ModuleMode.CONFIGURATION)

    def _check_config_mode(self):
        """Check if the module is already in configuration mode
        Returns True if the module responds to a register read, False otherwise"""
        if not self.serial or not self.serial.is_open:
            return False

        try:
            self.serial.reset_input_buffer()
            # Try reading address register — if we get a valid 0xC1 response, we're in config mode
            cmd = [CMD_READ, REG_ADDH, 1]
            self.serial.write(bytes(cmd))
            time.sleep(0.1)

            if self.serial.in_waiting >= 4:
                resp = self.serial.read(self.serial.in_waiting)
                if resp and resp[0] == CMD_READ and resp[1] == REG_ADDH:
                    logger.info("Configuration mode verified via register read")
                    return True

            logger.debug("No valid configuration mode response")
        except Exception as e:
            logger.debug(f"Exception when checking config mode: {e}")

        return False

    def exit_config_mode(self):
        """Exit configuration mode and return to normal mode"""
        # If using manual configuration, don't exit config mode
        if hasattr(self, 'manual_config') and self.manual_config:
            logger.info("Not exiting configuration mode - manual configuration is enabled")
            return True

        return self.set_mode(ModuleMode.NORMAL)

    def get_parameters(self):
        """Read all parameters from the module using binary register protocol"""
        if not self.enter_config_mode():
            return None

        try:
            regs = self._read_registers(0x00, REG_BLOCK_SIZE)
            if regs is None:
                return None

            params = _parse_registers(regs)
            logger.info(f"Parameters read: addr={params['address']}, ch={params['chan']}, "
                       f"freq={params['frequency']:.3f}MHz")
            return params

        except Exception as e:
            logger.error(f"Error reading parameters: {e}")
            return None

        finally:
            # Don't exit config mode if manual config is enabled
            if hasattr(self, 'manual_config') and self.manual_config:
                logger.info("Keeping module in configuration mode (manual configuration selected)")
                return params if 'params' in dir() else None

            self.exit_config_mode()

    def set_parameters(self, params):
        """Write parameters to the module using binary register protocol.

        Args:
            params: dict of parameter names and values to set.
                    Only the provided keys are changed; existing values are preserved.

        Returns:
            True on success, False on failure
        """
        if not self.enter_config_mode():
            return False

        success = True

        try:
            # Read current register values first (to merge with new values)
            existing_regs = self._read_registers(0x00, REG_BLOCK_SIZE)
            if existing_regs is None:
                logger.warning("Could not read existing registers, writing all values from scratch")
                existing_regs = [0x00] * REG_BLOCK_SIZE

            # Build new register block from params + existing
            new_regs = _build_registers(params, existing_regs)

            logger.info(f"Writing registers: {' '.join(f'0x{r:02X}' for r in new_regs)}")

            # Write all 8 registers
            if not self._write_registers(new_regs, 0x00):
                logger.error("Failed to write register block")
                success = False
            else:
                logger.info("Parameters written successfully")

            # Attempt to save to flash (0xC4 command)
            # Note: Not all E220 firmware versions support this.
            # If the module doesn't respond, parameters will reset on power cycle.
            if success:
                try:
                    save_cmd = [CMD_SAVE, 0x00, 0x00]
                    resp = self._send_command(save_cmd, expected_response_len=3, timeout=0.5)
                    if resp and resp[0] == CMD_SAVE:
                        logger.info("Parameters saved to flash")
                    else:
                        logger.info("Flash save not confirmed (module may auto-save or require different command)")
                except Exception:
                    logger.debug("Flash save command not supported or failed — parameters may not persist across power cycles")

        except Exception as e:
            logger.error(f"Error setting parameters: {e}")
            success = False

        # Don't exit config mode if manual configuration is enabled
        if not (hasattr(self, 'manual_config') and self.manual_config):
            self.exit_config_mode()

        return success

    def reset_module(self):
        """Reset the module via software command"""
        if not self.enter_config_mode():
            return False

        try:
            # Send reset command
            cmd = [CMD_RESET, 0x00, 0x00]
            response = self._send_command(cmd, expected_response_len=3, timeout=1.0)

            if response and response[0] == CMD_RESET:
                time.sleep(1)
                logger.info("Module reset command sent")
                return True
            else:
                logger.error(f"Invalid response when resetting module")
                return False
        except Exception as e:
            logger.error(f"Error resetting module: {e}")
            return False
        finally:
            # Reset will automatically put the module back in normal mode
            self.current_mode = None

    def factory_reset(self):
        """Reset the module to factory defaults.

        The E220 factory reset typically requires writing default register values.
        EBYTE default factory values:
          Address: 0x0000
          UART: 9600 8N1 (reg=0x60 → baud_idx=3, parity_idx=0)
          Air rate: 2.4kbps, 240-byte packets (reg=0x00)
          Power: 30dBm max (reg=0x00)
          Channel: 0 (reg=0x00)
          Options: transparent mode, LBT off, RSSI off (reg=0x00)
          WOR period: 0 (reg=0x00)
        """
        if not self.enter_config_mode():
            return False

        try:
            # EBYTE factory default register values
            # These match the E220-900T30S defaults from the datasheet
            default_regs = [
                0x00,  # ADDH = 0
                0x00,  # ADDL = 0
                0x60,  # UART: 9600 bps (3<<5), 8N1 (0<<3)
                0x00,  # Air rate: 2.4kbps (0), 240-byte packets (0)
                0x00,  # Power: 30dBm (0)
                0x00,  # Channel: 0
                0x00,  # Options: transparent, no LBT, no RSSI
                0x00,  # WOR period: 0
            ]

            if self._write_registers(default_regs, 0x00):
                logger.info("Factory defaults written")

                # Attempt flash save
                try:
                    save_cmd = [CMD_SAVE, 0x00, 0x00]
                    self._send_command(save_cmd, expected_response_len=3, timeout=0.5)
                except Exception:
                    pass

                time.sleep(0.5)
                return True
            else:
                logger.error("Failed to write factory defaults")
                return False

        except Exception as e:
            logger.error(f"Error factory resetting module: {e}")
            return False
        finally:
            self.current_mode = None

    def version(self):
        """Get module version info.

        The E220 may support reading additional registers for version info,
        but this varies by firmware. We read the standard register block
        and return what we can determine.
        """
        if not self.enter_config_mode():
            return None

        try:
            regs = self._read_registers(0x00, REG_BLOCK_SIZE)
            if regs is None:
                return None

            # Build a version info dict from what we can read
            params = _parse_registers(regs)
            version_info = {
                "model": "E220 (detected via register read)",
                "version": f"regs={' '.join(f'{r:02X}' for r in regs)}",
                "address": params["address"],
                "frequency": f"{params['frequency']:.3f} MHz",
            }
            return version_info

        except Exception as e:
            logger.error(f"Error getting version: {e}")
            return None
        finally:
            self.exit_config_mode()


# ============================================================================
# GUI Class
# ============================================================================

class E220ConfigGUI:
    """
    GUI interface for configuring the E220 module
    """
    def __init__(self, master):
        self.master = master
        self.master.title("E220-915MHz LoRa Module Configurator")
        self.master.geometry("800x600")
        self.master.minsize(800, 600)

        # Module instance
        self.module = None

        # Serial port variables
        self.port_var = tk.StringVar()
        self.baudrate_var = tk.IntVar(value=9600)

        # Parameter variables
        self._init_parameter_vars()

        # Create the main notebook/tabs
        self.notebook = ttk.Notebook(self.master)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create tabs
        self.connection_tab = ttk.Frame(self.notebook)
        self.basic_tab = ttk.Frame(self.notebook)
        self.advanced_tab = ttk.Frame(self.notebook)
        self.monitor_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.connection_tab, text="Connection")
        self.notebook.add(self.basic_tab, text="Basic Settings")
        self.notebook.add(self.advanced_tab, text="Advanced Settings")
        self.notebook.add(self.monitor_tab, text="Monitor")

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = tk.Label(
            self.master,
            textvariable=self.status_var,
            bd=1,
            relief=tk.SUNKEN,
            anchor=tk.W
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Setup tabs
        self._setup_connection_tab()
        self._setup_basic_tab()
        self._setup_advanced_tab()
        self._setup_monitor_tab()

        # Disable tabs until connected
        self.notebook.tab(1, state="disabled")
        self.notebook.tab(2, state="disabled")
        self.notebook.tab(3, state="disabled")

        # Add a window close handler
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_parameter_vars(self):
        """Initialize variables for module parameters"""
        # Basic settings
        self.address_var = tk.IntVar(value=0)
        self.channel_var = tk.IntVar(value=0)
        self.uart_baud_var = tk.IntVar(value=3)  # Default: 9600 bps (index 3)
        self.parity_var = tk.IntVar(value=0)     # Default: 8N1
        self.air_rate_var = tk.IntVar(value=0)   # Default: 2.4 kbps (index 0)
        self.power_var = tk.IntVar(value=0)      # Default: 30 dBm (max)

        # Advanced settings
        self.fixed_trans_var = tk.IntVar(value=0)  # Default: Transparent
        self.wake_time_var = tk.IntVar(value=0)    # Default: 500ms
        self.packet_var = tk.IntVar(value=0)       # Default: 240 bytes

        # E220-specific settings
        self.lbt_var = tk.IntVar(value=0)          # Default: Off
        self.erssi_var = tk.IntVar(value=0)        # Default: Off
        self.drssi_var = tk.IntVar(value=0)        # Default: Off
        self.sw_switch_var = tk.IntVar(value=0)    # Default: Off

    def _setup_connection_tab(self):
        """Setup the connection tab"""
        conn_frame = ttk.LabelFrame(self.connection_tab, text="Connection Settings")
        conn_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Serial port selection
        ttk.Label(conn_frame, text="Serial Port:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.port_combo = ttk.Combobox(conn_frame, textvariable=self.port_var)
        self.port_combo.grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Button(conn_frame, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=5, pady=5)

        # Baud rate selection
        ttk.Label(conn_frame, text="Baud Rate:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.baud_combo = ttk.Combobox(conn_frame, textvariable=self.baudrate_var, values=UART_BAUD_RATES)
        self.baud_combo.grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        # Connect/Disconnect button
        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self._toggle_connection)
        self.connect_button.grid(row=2, column=0, columnspan=3, padx=5, pady=20)

        # Version and info
        ttk.Label(conn_frame, text=f"E220-915MHz LoRa Module Configurator v{__version__}").grid(
            row=3, column=0, columnspan=3, padx=5, pady=5
        )

        # Description
        desc_text = """This application allows you to configure EBYTE E220-915MHz series LoRa modules.
Connect the module to your computer using a USB-to-serial adapter with the following wiring:

- Connect module's M0 and M1 pins to your adapter if you need automatic mode switching
- Make sure the module is powered with 3.3-5V DC
- Default baud rate is 9600 bps

For configuration mode, both M0 and M1 must be set HIGH.
If you've already set M0=HIGH and M1=HIGH manually, check the option below.
        """
        desc_label = ttk.Label(conn_frame, text=desc_text, justify=tk.LEFT, wraplength=500)
        desc_label.grid(row=4, column=0, columnspan=3, padx=5, pady=10, sticky=tk.W)

        # Additional options frame
        options_frame = ttk.LabelFrame(conn_frame, text="Additional Options")
        options_frame.grid(row=5, column=0, columnspan=3, padx=5, pady=10, sticky=tk.W+tk.E)

        # Manual configuration mode option
        self.manual_config_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame,
            text="I have manually set M0=HIGH, M1=HIGH for configuration mode",
            variable=self.manual_config_var
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)

        # GPIO control options (for Raspberry Pi or similar)
        self.use_gpio_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_frame,
            text="Use GPIO pins for mode control (Raspberry Pi)",
            variable=self.use_gpio_var
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)

        # GPIO pin settings
        ttk.Label(options_frame, text="M0 GPIO Pin:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.m0_pin_var = tk.IntVar(value=16)
        ttk.Entry(options_frame, textvariable=self.m0_pin_var, width=5).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(options_frame, text="M1 GPIO Pin:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.m1_pin_var = tk.IntVar(value=17)
        ttk.Entry(options_frame, textvariable=self.m1_pin_var, width=5).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(options_frame, text="AUX GPIO Pin:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.aux_pin_var = tk.IntVar(value=22)
        ttk.Entry(options_frame, textvariable=self.aux_pin_var, width=5).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)

        # Load/Save configuration buttons
        button_frame = ttk.Frame(conn_frame)
        button_frame.grid(row=6, column=0, columnspan=3, padx=5, pady=10)

        ttk.Button(button_frame, text="Load Config", command=self._load_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save Config", command=self._save_config).pack(side=tk.LEFT, padx=5)

        # Initial refresh of ports
        self._refresh_ports()

    def _setup_basic_tab(self):
        """Setup the basic settings tab"""
        basic_frame = ttk.LabelFrame(self.basic_tab, text="Basic Configuration")
        basic_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Module address
        ttk.Label(basic_frame, text="Module Address (0-65535):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(basic_frame, textvariable=self.address_var).grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text="Unique identifier for the module").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)

        # Channel
        ttk.Label(basic_frame, text="Channel (0-80):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(basic_frame, textvariable=self.channel_var).grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text="Frequency = 900.125MHz + Channel*1MHz").grid(row=1, column=2, sticky=tk.W, padx=5, pady=5)

        # UART Baud Rate
        ttk.Label(basic_frame, text="UART Baud Rate:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        baud_display = [f"{b} bps" for b in UART_BAUD_RATES]
        ttk.Combobox(basic_frame, textvariable=self.uart_baud_var, values=list(range(len(UART_BAUD_RATES))),
                     state="readonly").grid(row=2, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_baud_display(*args):
            idx = self.uart_baud_var.get()
            if 0 <= idx < len(baud_display):
                baud_label.config(text=f"Selected: {baud_display[idx]}")

        baud_label = ttk.Label(basic_frame, text=f"Selected: {baud_display[self.uart_baud_var.get()]}")
        baud_label.grid(row=2, column=3, sticky=tk.W, padx=5, pady=5)
        self.uart_baud_var.trace_add("write", update_baud_display)

        # Parity
        ttk.Label(basic_frame, text="Serial Parity:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Combobox(basic_frame, textvariable=self.parity_var, values=list(range(len(PARITY_LABELS))),
                    state="readonly").grid(row=3, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_parity_display(*args):
            idx = self.parity_var.get()
            if 0 <= idx < len(PARITY_LABELS):
                parity_label.config(text=f"Selected: {PARITY_LABELS[idx]}")

        parity_label = ttk.Label(basic_frame, text=f"Selected: {PARITY_LABELS[self.parity_var.get()]}")
        parity_label.grid(row=3, column=3, sticky=tk.W, padx=5, pady=5)
        self.parity_var.trace_add("write", update_parity_display)

        # Air Rate
        ttk.Label(basic_frame, text="Air Rate:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Combobox(basic_frame, textvariable=self.air_rate_var, values=list(range(len(AIR_RATE_LABELS))),
                     state="readonly").grid(row=4, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_airrate_display(*args):
            idx = self.air_rate_var.get()
            if 0 <= idx < len(AIR_RATE_LABELS):
                airrate_label.config(text=f"Selected: {AIR_RATE_LABELS[idx]}")

        airrate_label = ttk.Label(basic_frame, text=f"Selected: {AIR_RATE_LABELS[self.air_rate_var.get()]}")
        airrate_label.grid(row=4, column=3, sticky=tk.W, padx=5, pady=5)
        self.air_rate_var.trace_add("write", update_airrate_display)

        # Transmit Power
        ttk.Label(basic_frame, text="Transmit Power:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Combobox(basic_frame, textvariable=self.power_var, values=list(range(len(TX_POWER_LABELS))),
                     state="readonly").grid(row=5, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_power_display(*args):
            idx = self.power_var.get()
            if 0 <= idx < len(TX_POWER_LABELS):
                power_label.config(text=f"Selected: {TX_POWER_LABELS[idx]}")

        power_label = ttk.Label(basic_frame, text=f"Selected: {TX_POWER_LABELS[self.power_var.get()]}")
        power_label.grid(row=5, column=3, sticky=tk.W, padx=5, pady=5)
        self.power_var.trace_add("write", update_power_display)

        # Frequency display
        ttk.Label(basic_frame, text="Frequency:").grid(row=6, column=0, sticky=tk.W, padx=5, pady=5)

        def update_frequency_display(*args):
            channel = self.channel_var.get()
            try:
                frequency = FREQ_BASE + channel * FREQ_STEP
                freq_label.config(text=f"{frequency:.3f} MHz")
            except:
                freq_label.config(text="Invalid channel")

        freq_label = ttk.Label(basic_frame, text=f"{FREQ_BASE:.3f} MHz")
        freq_label.grid(row=6, column=1, sticky=tk.W, padx=5, pady=5)
        self.channel_var.trace_add("write", update_frequency_display)

        # Buttons frame
        button_frame = ttk.Frame(basic_frame)
        button_frame.grid(row=7, column=0, columnspan=4, pady=20)

        ttk.Button(button_frame, text="Read from Module", command=self._read_params).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Write to Module", command=self._write_params).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Reset Module", command=self._reset_module).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Factory Reset", command=self._factory_reset).pack(side=tk.LEFT, padx=10)

    def _setup_advanced_tab(self):
        """Setup the advanced settings tab"""
        adv_frame = ttk.LabelFrame(self.advanced_tab, text="Advanced Configuration")
        adv_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Fixed Transmission Mode
        ttk.Label(adv_frame, text="Transmission Mode:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        trans_options = ["Transparent Transmission", "Fixed Point Transmission"]
        ttk.Combobox(adv_frame, textvariable=self.fixed_trans_var, values=list(range(len(trans_options))),
                     state="readonly").grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_trans_display(*args):
            idx = self.fixed_trans_var.get()
            if 0 <= idx < len(trans_options):
                trans_label.config(text=f"Selected: {trans_options[idx]}")

        trans_label = ttk.Label(adv_frame, text=f"Selected: {trans_options[self.fixed_trans_var.get()]}")
        trans_label.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)
        self.fixed_trans_var.trace_add("write", update_trans_display)

        # Wake-up Time
        ttk.Label(adv_frame, text="Wake-up Time:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Combobox(adv_frame, textvariable=self.wake_time_var, values=list(range(len(WAKE_TIME_LABELS))),
                     state="readonly").grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_wake_display(*args):
            idx = self.wake_time_var.get()
            if 0 <= idx < len(WAKE_TIME_LABELS):
                wake_label.config(text=f"Selected: {WAKE_TIME_LABELS[idx]}")

        wake_label = ttk.Label(adv_frame, text=f"Selected: {WAKE_TIME_LABELS[self.wake_time_var.get()]}")
        wake_label.grid(row=1, column=3, sticky=tk.W, padx=5, pady=5)
        self.wake_time_var.trace_add("write", update_wake_display)

        # Packet length
        ttk.Label(adv_frame, text="Packet Length:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Combobox(adv_frame, textvariable=self.packet_var, values=list(range(len(PACKET_LABELS))),
                     state="readonly").grid(row=2, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_packet_display(*args):
            idx = self.packet_var.get()
            if 0 <= idx < len(PACKET_LABELS):
                packet_label.config(text=f"Selected: {PACKET_LABELS[idx]}")

        packet_label = ttk.Label(adv_frame, text=f"Selected: {PACKET_LABELS[self.packet_var.get()]}")
        packet_label.grid(row=2, column=3, sticky=tk.W, padx=5, pady=5)
        self.packet_var.trace_add("write", update_packet_display)

        # LBT (Listen Before Talk)
        ttk.Label(adv_frame, text="Listen Before Talk:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        lbt_options = ["Off", "On"]
        ttk.Combobox(adv_frame, textvariable=self.lbt_var, values=list(range(len(lbt_options))),
                     state="readonly").grid(row=3, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_lbt_display(*args):
            idx = self.lbt_var.get()
            if 0 <= idx < len(lbt_options):
                lbt_label.config(text=f"Selected: {lbt_options[idx]}")

        lbt_label = ttk.Label(adv_frame, text=f"Selected: {lbt_options[self.lbt_var.get()]}")
        lbt_label.grid(row=3, column=3, sticky=tk.W, padx=5, pady=5)
        self.lbt_var.trace_add("write", update_lbt_display)

        # RSSI Ambient Noise Enable
        ttk.Label(adv_frame, text="Ambient Noise RSSI:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        erssi_options = ["Off", "On"]
        ttk.Combobox(adv_frame, textvariable=self.erssi_var, values=list(range(len(erssi_options))),
                     state="readonly").grid(row=4, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_erssi_display(*args):
            idx = self.erssi_var.get()
            if 0 <= idx < len(erssi_options):
                erssi_label.config(text=f"Selected: {erssi_options[idx]}")

        erssi_label = ttk.Label(adv_frame, text=f"Selected: {erssi_options[self.erssi_var.get()]}")
        erssi_label.grid(row=4, column=3, sticky=tk.W, padx=5, pady=5)
        self.erssi_var.trace_add("write", update_erssi_display)

        # Data RSSI
        ttk.Label(adv_frame, text="Data RSSI:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        drssi_options = ["Off", "On"]
        ttk.Combobox(adv_frame, textvariable=self.drssi_var, values=list(range(len(drssi_options))),
                     state="readonly").grid(row=5, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_drssi_display(*args):
            idx = self.drssi_var.get()
            if 0 <= idx < len(drssi_options):
                drssi_label.config(text=f"Selected: {drssi_options[idx]}")

        drssi_label = ttk.Label(adv_frame, text=f"Selected: {drssi_options[self.drssi_var.get()]}")
        drssi_label.grid(row=5, column=3, sticky=tk.W, padx=5, pady=5)
        self.drssi_var.trace_add("write", update_drssi_display)

        # Software Mode Switching
        ttk.Label(adv_frame, text="Software Mode Switch:").grid(row=6, column=0, sticky=tk.W, padx=5, pady=5)
        sw_switch_options = ["Off", "On"]
        ttk.Combobox(adv_frame, textvariable=self.sw_switch_var, values=list(range(len(sw_switch_options))),
                     state="readonly").grid(row=6, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        def update_sw_switch_display(*args):
            idx = self.sw_switch_var.get()
            if 0 <= idx < len(sw_switch_options):
                sw_switch_label.config(text=f"Selected: {sw_switch_options[idx]}")

        sw_switch_label = ttk.Label(adv_frame, text=f"Selected: {sw_switch_options[self.sw_switch_var.get()]}")
        sw_switch_label.grid(row=6, column=3, sticky=tk.W, padx=5, pady=5)
        self.sw_switch_var.trace_add("write", update_sw_switch_display)

        # Operating mode explanation
        mode_frame = ttk.LabelFrame(adv_frame, text="Operating Modes")
        mode_frame.grid(row=7, column=0, columnspan=4, sticky=tk.W+tk.E, padx=5, pady=10)

        mode_text = """
The E220 module has 4 operating modes controlled by M0 and M1 pins:

Mode 0 (M0=0, M1=0): Normal mode - UART and wireless channels are open for transparent transmission
Mode 1 (M0=1, M1=0): WOR transmit mode - Sends data with wake-up code for WOR receivers
Mode 2 (M0=0, M1=1): WOR receive mode - Listens periodically to save power
Mode 3 (M0=1, M1=1): Sleep/configuration mode - For settings configuration via register commands

Note: These modes cannot be changed from this software unless you use GPIO control or enable software mode switching.
        """

        mode_label = ttk.Label(mode_frame, text=mode_text, justify=tk.LEFT, wraplength=700)
        mode_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Buttons frame
        button_frame = ttk.Frame(adv_frame)
        button_frame.grid(row=8, column=0, columnspan=4, pady=20)

        ttk.Button(button_frame, text="Read from Module", command=self._read_params).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Write to Module", command=self._write_params).pack(side=tk.LEFT, padx=10)

    def _setup_monitor_tab(self):
        """Setup the monitor tab for seeing module status and testing"""
        monitor_frame = ttk.LabelFrame(self.monitor_tab, text="Module Monitor")
        monitor_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Version info
        ttk.Label(monitor_frame, text="Module Information:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.version_var = tk.StringVar(value="Not available")
        ttk.Label(monitor_frame, textvariable=self.version_var).grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        ttk.Button(monitor_frame, text="Get Version", command=self._get_version).grid(row=0, column=2, padx=5, pady=5)

        # Current parameters display
        param_frame = ttk.LabelFrame(monitor_frame, text="Current Parameters")
        param_frame.grid(row=1, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, padx=5, pady=10)

        self.param_text = scrolledtext.ScrolledText(param_frame, height=10, width=60)
        self.param_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        ttk.Button(param_frame, text="Refresh Parameters", command=self._refresh_params_display).pack(pady=5)

        # Test transmission frame
        test_frame = ttk.LabelFrame(monitor_frame, text="Test Transmission")
        test_frame.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, padx=5, pady=10)

        ttk.Label(test_frame, text="Data to send:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.test_data_var = tk.StringVar(value="Hello LoRa!")
        ttk.Entry(test_frame, textvariable=self.test_data_var, width=40).grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)

        ttk.Button(test_frame, text="Send Data", command=self._send_test_data).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(test_frame, text="Received Data:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.received_text = scrolledtext.ScrolledText(test_frame, height=5, width=60)
        self.received_text.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.E, padx=5, pady=5)

        ttk.Button(test_frame, text="Clear Received", command=lambda: self.received_text.delete(1.0, tk.END)).grid(row=3, column=0, columnspan=3, pady=5)

        self.receiving_var = tk.BooleanVar(value=False)
        self.receive_button = ttk.Button(test_frame, text="Start Receiving", command=self._toggle_receiving)
        self.receive_button.grid(row=4, column=0, columnspan=3, pady=5)

    def _refresh_ports(self):
        """Refresh the list of available serial ports"""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo['values'] = ports

        if ports:
            if self.port_var.get() not in ports:
                self.port_var.set(ports[0])
        else:
            self.port_var.set("")

    def _toggle_connection(self):
        """Connect to or disconnect from the module"""
        if self.module and self.module.serial and self.module.serial.is_open:
            # Disconnect
            self.module.disconnect()
            self.module = None
            self.connect_button.config(text="Connect")
            self.status_var.set("Disconnected from module")

            # Disable tabs
            self.notebook.tab(1, state="disabled")
            self.notebook.tab(2, state="disabled")
            self.notebook.tab(3, state="disabled")
        else:
            # Connect
            port = self.port_var.get()
            baudrate = self.baudrate_var.get()

            if not port:
                messagebox.showerror("Error", "No serial port selected")
                return

            # Initialize module
            use_gpio = self.use_gpio_var.get()
            manual_config = self.manual_config_var.get()
            m0_pin = self.m0_pin_var.get() if use_gpio else None
            m1_pin = self.m1_pin_var.get() if use_gpio else None
            aux_pin = self.aux_pin_var.get() if use_gpio else None

            # Display a reminder for manual configuration mode if needed
            if not use_gpio and manual_config:
                self.status_var.set("Using manual configuration mode (M0=HIGH, M1=HIGH)")
            elif not use_gpio and not manual_config:
                result = messagebox.askquestion("Configuration Mode Reminder",
                    "You have not selected GPIO control or manual configuration mode.\n\n" +
                    "Have you set M0=HIGH and M1=HIGH manually for configuration mode?",
                    icon='warning')
                if result != 'yes':
                    messagebox.showinfo("Configuration Required",
                        "Please set M0=HIGH and M1=HIGH manually before connecting.")
                    return
                # User confirmed they set pins manually, so set the flag
                manual_config = True

            self.module = E220Module(
                port=port,
                baudrate=baudrate,
                timeout=1,
                m0_pin=m0_pin,
                m1_pin=m1_pin,
                aux_pin=aux_pin,
                use_gpio=use_gpio,
                manual_config=manual_config
            )

            if self.module.connect():
                self.connect_button.config(text="Disconnect")
                self.status_var.set(f"Connected to module on {port} at {baudrate} baud")

                # Enable tabs
                self.notebook.tab(1, state="normal")
                self.notebook.tab(2, state="normal")
                self.notebook.tab(3, state="normal")

                # Try to read parameters
                self._read_params()
            else:
                messagebox.showerror("Error", f"Failed to connect to module on {port}")
                self.module = None

    def _read_params(self):
        """Read parameters from the module"""
        if not self.module:
            messagebox.showerror("Error", "Not connected to module")
            return

        self.status_var.set("Reading parameters from module...")
        self.master.update()

        params = self.module.get_parameters()

        if params:
            # Update UI with retrieved parameters
            self.address_var.set(params.get("address", 0))
            self.channel_var.set(params.get("chan", 0))
            self.uart_baud_var.set(params.get("uart_baud", 3))
            self.parity_var.set(params.get("parity", 0))
            self.air_rate_var.set(params.get("air_data_rate", 0))
            self.power_var.set(params.get("transmission_power", 0))
            self.fixed_trans_var.set(params.get("fixed_transmission", 0))
            self.wake_time_var.set(params.get("wake_up_time", 0))
            self.packet_var.set(params.get("packet", 0))

            # E220-specific parameters
            self.lbt_var.set(params.get("lbt", 0))
            self.erssi_var.set(params.get("rssi_noise_en", 0))
            self.drssi_var.set(params.get("drssi", 0))
            self.sw_switch_var.set(params.get("sw_switch", 0))

            self.status_var.set("Parameters read successfully")
            self._refresh_params_display()
        else:
            self.status_var.set("Failed to read parameters")
            messagebox.showerror("Error", "Failed to read parameters from module")

    def _write_params(self):
        """Write parameters to the module"""
        if not self.module:
            messagebox.showerror("Error", "Not connected to module")
            return

        # Validate parameters
        try:
            address = int(self.address_var.get())
            if not 0 <= address <= 65535:
                raise ValueError("Address must be between 0 and 65535")

            channel = int(self.channel_var.get())
            if not 0 <= channel <= 80:
                raise ValueError("Channel must be between 0 and 80")

        except ValueError as e:
            messagebox.showerror("Parameter Error", str(e))
            return

        # Collect parameters
        params = {
            "address": address,
            "chan": self.channel_var.get(),
            "uart_baud": self.uart_baud_var.get(),
            "parity": self.parity_var.get(),
            "air_data_rate": self.air_rate_var.get(),
            "transmission_power": self.power_var.get(),
            "fixed_transmission": self.fixed_trans_var.get(),
            "wake_up_time": self.wake_time_var.get(),
            "packet": self.packet_var.get(),
            # E220-specific parameters
            "lbt": self.lbt_var.get(),
            "rssi_noise_en": self.erssi_var.get(),
            "drssi": self.drssi_var.get(),
            "sw_switch": self.sw_switch_var.get()
        }

        # Ask for confirmation if baudrate is changing from the default 9600
        if params["uart_baud"] != 3:  # Default baud rate index (9600 bps)
            if not messagebox.askyesno(
                "Confirm Baud Rate Change",
                f"You are changing the module's baud rate to {UART_BAUD_RATES[params['uart_baud']]} bps.\n\n"
                "If you continue, you may need to disconnect and reconnect at the new baud rate.\n\n"
                "Are you sure you want to continue?"
            ):
                return

        self.status_var.set("Writing parameters to module...")
        self.master.update()

        if self.module.set_parameters(params):
            self.status_var.set("Parameters written successfully")

            # If baudrate changed, notify the user to reconnect
            if params["uart_baud"] != 3:  # Default baud rate index (9600 bps)
                messagebox.showinfo(
                    "Baud Rate Changed",
                    f"The module's baud rate has been changed to {UART_BAUD_RATES[params['uart_baud']]} bps.\n\n"
                    "Please disconnect and reconnect at the new baud rate."
                )

            # Update the parameter display
            self._refresh_params_display()
        else:
            self.status_var.set("Failed to write parameters")
            messagebox.showerror("Error", "Failed to write parameters to module")

    def _reset_module(self):
        """Reset the module"""
        if not self.module:
            messagebox.showerror("Error", "Not connected to module")
            return

        if messagebox.askyesno("Confirm Reset", "Are you sure you want to reset the module?"):
            self.status_var.set("Resetting module...")
            self.master.update()

            if self.module.reset_module():
                self.status_var.set("Module reset successfully")
                self._read_params()
            else:
                self.status_var.set("Failed to reset module")
                messagebox.showerror("Error", "Failed to reset module")

    def _factory_reset(self):
        """Reset the module to factory defaults"""
        if not self.module:
            messagebox.showerror("Error", "Not connected to module")
            return

        if messagebox.askyesno(
            "Confirm Factory Reset",
            "Are you sure you want to reset the module to factory defaults?\n\n"
            "This will erase all custom settings."
        ):
            self.status_var.set("Performing factory reset...")
            self.master.update()

            if self.module.factory_reset():
                self.status_var.set("Factory reset successful")
                self._read_params()
            else:
                self.status_var.set("Failed to perform factory reset")
                messagebox.showerror("Error", "Failed to perform factory reset")

    def _get_version(self):
        """Get module version information"""
        if not self.module:
            messagebox.showerror("Error", "Not connected to module")
            return

        self.status_var.set("Getting module version...")
        self.master.update()

        version_info = self.module.version()

        if version_info:
            version_str = f"Model: {version_info['model']}"
            self.version_var.set(version_str)
            self.status_var.set("Version read successfully")
        else:
            self.status_var.set("Failed to read version")
            messagebox.showerror("Error", "Failed to read module version")

    def _refresh_params_display(self):
        """Refresh the parameters display in the monitor tab"""
        if not self.module:
            self.param_text.delete(1.0, tk.END)
            self.param_text.insert(tk.END, "Not connected to module")
            return

        params = self.module.get_parameters()

        if not params:
            self.param_text.delete(1.0, tk.END)
            self.param_text.insert(tk.END, "Failed to read parameters")
            return

        # Format display text
        self.param_text.delete(1.0, tk.END)

        # Format and display parameters
        self.param_text.insert(tk.END, f"Address: {params['address']} (0x{params['address']:04X})\n")
        self.param_text.insert(tk.END, f"Channel: {params['chan']} (Frequency: {params['frequency']:.3f} MHz)\n")

        uart_baud = params['uart_baud']
        if 0 <= uart_baud < len(UART_BAUD_RATES):
            self.param_text.insert(tk.END, f"UART Baud Rate: {UART_BAUD_RATES[uart_baud]} bps\n")

        parity = params['parity']
        if 0 <= parity < len(PARITY_LABELS):
            self.param_text.insert(tk.END, f"UART Parity: {PARITY_LABELS[parity]}\n")

        air_rate = params['air_data_rate']
        if 0 <= air_rate < len(AIR_RATE_LABELS):
            self.param_text.insert(tk.END, f"Air Data Rate: {AIR_RATE_LABELS[air_rate]}\n")

        power = params['transmission_power']
        if 0 <= power < len(TX_POWER_LABELS):
            self.param_text.insert(tk.END, f"Transmission Power: {TX_POWER_LABELS[power]}\n")

        self.param_text.insert(tk.END, f"Fixed Transmission: {'Enabled' if params['fixed_transmission'] else 'Disabled'}\n")

        wake_time = params['wake_up_time']
        if 0 <= wake_time < len(WAKE_TIME_LABELS):
            self.param_text.insert(tk.END, f"Wake-up Time: {WAKE_TIME_LABELS[wake_time]}\n")

        packet = params.get('packet', 0)
        if 0 <= packet < len(PACKET_LABELS):
            self.param_text.insert(tk.END, f"Packet Length: {PACKET_LABELS[packet]}\n")

        # E220-specific parameters
        self.param_text.insert(tk.END, f"Listen Before Talk (LBT): {'Enabled' if params.get('lbt', 0) else 'Disabled'}\n")
        self.param_text.insert(tk.END, f"Ambient Noise RSSI: {'Enabled' if params.get('rssi_noise_en', 0) else 'Disabled'}\n")
        self.param_text.insert(tk.END, f"Data RSSI: {'Enabled' if params.get('drssi', 0) else 'Disabled'}\n")
        self.param_text.insert(tk.END, f"Software Mode Switching: {'Enabled' if params.get('sw_switch', 0) else 'Disabled'}\n")

    def _send_test_data(self):
        """Send test data through the module"""
        if not self.module or not self.module.serial or not self.module.serial.is_open:
            messagebox.showerror("Error", "Not connected to module")
            return

        data = self.test_data_var.get()
        if not data:
            return

        try:
            # Switch to normal mode for transmission
            if self.module.set_mode(ModuleMode.NORMAL):
                self.module.serial.write(data.encode('utf-8'))
                self.status_var.set(f"Data sent: {data}")
            else:
                self.status_var.set("Failed to set module to normal mode")
                messagebox.showerror("Error", "Failed to set module to normal mode for transmission")
        except Exception as e:
            self.status_var.set(f"Error sending data: {str(e)}")
            messagebox.showerror("Error", f"Failed to send data: {str(e)}")

    def _toggle_receiving(self):
        """Toggle receiving mode"""
        if not self.module or not self.module.serial or not self.module.serial.is_open:
            messagebox.showerror("Error", "Not connected to module")
            return

        if self.receiving_var.get():
            # Stop receiving
            self.receiving_var.set(False)
            self.receive_button.config(text="Start Receiving")
            self.status_var.set("Stopped receiving")
        else:
            # Start receiving
            self.receiving_var.set(True)
            self.receive_button.config(text="Stop Receiving")
            self.status_var.set("Started receiving")

            threading.Thread(target=self._receive_data, daemon=True).start()

    def _receive_data(self):
        """Receive data in a separate thread"""
        if not self.module.set_mode(ModuleMode.NORMAL):
            self.status_var.set("Failed to set module to normal mode")
            self.receiving_var.set(False)
            self.receive_button.config(text="Start Receiving")
            return

        self.module.serial.reset_input_buffer()

        while self.receiving_var.get():
            try:
                if self.module.serial.in_waiting:
                    data = self.module.serial.read(self.module.serial.in_waiting)
                    if data:
                        try:
                            decoded = data.decode('utf-8')
                        except UnicodeDecodeError:
                            decoded = f"HEX: {data.hex()}"

                        timestamp = time.strftime("%H:%M:%S")
                        self.master.after(0, self._update_received_text, f"[{timestamp}] {decoded}\n")
            except Exception as e:
                self.master.after(0, self._update_status, f"Error receiving data: {str(e)}")
                break

            time.sleep(0.1)

    def _update_received_text(self, text):
        """Update received text in a thread-safe way"""
        self.received_text.insert(tk.END, text)
        self.received_text.see(tk.END)

    def _update_status(self, text):
        """Update status bar in a thread-safe way"""
        self.status_var.set(text)

    def _load_config(self):
        """Load configuration from file"""
        filename = filedialog.askopenfilename(
            title="Load Configuration File",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not filename:
            return

        try:
            with open(filename, 'r') as f:
                config = json.load(f)

            # Update UI with loaded parameters
            if "address" in config:
                self.address_var.set(config["address"])

            if "chan" in config:
                self.channel_var.set(config["chan"])

            if "uart_baud" in config:
                self.uart_baud_var.set(config["uart_baud"])

            if "parity" in config:
                self.parity_var.set(config["parity"])

            if "air_data_rate" in config:
                self.air_rate_var.set(config["air_data_rate"])

            if "transmission_power" in config:
                self.power_var.set(config["transmission_power"])

            if "fixed_transmission" in config:
                self.fixed_trans_var.set(config["fixed_transmission"])

            if "wake_up_time" in config:
                self.wake_time_var.set(config["wake_up_time"])

            if "packet" in config:
                self.packet_var.set(config["packet"])

            # E220-specific parameters
            if "lbt" in config:
                self.lbt_var.set(config["lbt"])

            if "rssi_noise_en" in config:
                self.erssi_var.set(config["rssi_noise_en"])

            if "erssi" in config:
                self.erssi_var.set(config["erssi"])

            if "drssi" in config:
                self.drssi_var.set(config["drssi"])

            if "sw_switch" in config:
                self.sw_switch_var.set(config["sw_switch"])

            self.status_var.set(f"Configuration loaded from {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load configuration: {e}")

    def _save_config(self):
        """Save configuration to file"""
        filename = filedialog.asksaveasfilename(
            title="Save Configuration File",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )

        if not filename:
            return

        try:
            config = {
                "address": self.address_var.get(),
                "chan": self.channel_var.get(),
                "uart_baud": self.uart_baud_var.get(),
                "parity": self.parity_var.get(),
                "air_data_rate": self.air_rate_var.get(),
                "transmission_power": self.power_var.get(),
                "fixed_transmission": self.fixed_trans_var.get(),
                "wake_up_time": self.wake_time_var.get(),
                "packet": self.packet_var.get(),
                # E220-specific parameters
                "lbt": self.lbt_var.get(),
                "rssi_noise_en": self.erssi_var.get(),
                "drssi": self.drssi_var.get(),
                "sw_switch": self.sw_switch_var.get()
            }

            with open(filename, 'w') as f:
                json.dump(config, f, indent=4)

            self.status_var.set(f"Configuration saved to {os.path.basename(filename)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {e}")

    def _on_close(self):
        """Clean up when window is closed"""
        if self.module:
            self.module.disconnect()
        self.master.destroy()


# ============================================================================
# CLI Class
# ============================================================================

class E220CLI:
    """
    Command-line interface for configuring the E220 module
    """
    def __init__(self, args):
        self.args = args
        self.module = None

    def run(self):
        """Run the CLI based on arguments"""
        self.module = E220Module(
            port=self.args.port,
            baudrate=self.args.baudrate,
            timeout=1,
            m0_pin=self.args.m0_pin,
            m1_pin=self.args.m1_pin,
            aux_pin=self.args.aux_pin,
            use_gpio=self.args.use_gpio
        )

        if not self.module.connect():
            logger.error(f"Failed to connect to module on {self.args.port}")
            return 1

        logger.info(f"Connected to module on {self.args.port} at {self.args.baudrate} baud")

        try:
            if self.args.command == 'read':
                return self._read_params()
            elif self.args.command == 'write':
                return self._write_params()
            elif self.args.command == 'reset':
                return self._reset_module()
            elif self.args.command == 'factory-reset':
                return self._factory_reset()
            elif self.args.command == 'version':
                return self._get_version()
            elif self.args.command == 'save-config':
                return self._save_config()
            elif self.args.command == 'load-config':
                return self._load_config()
            elif self.args.command == 'scan-ports':
                return self._scan_ports()
            elif self.args.command == 'send-data':
                return self._send_data()
            else:
                logger.error(f"Unknown command: {self.args.command}")
                return 1
        finally:
            self.module.disconnect()

    def _read_params(self):
        """Read and display module parameters"""
        logger.info("Reading parameters from module...")

        params = self.module.get_parameters()

        if params:
            logger.info("Module parameters:")

            print(f"Address:               {params['address']} (0x{params['address']:04X})")
            print(f"Channel:               {params['chan']} ({params['frequency']:.3f}MHz)")

            if 'uart_baud' in params and 0 <= params['uart_baud'] < len(UART_BAUD_RATES):
                print(f"UART Baud Rate:        {UART_BAUD_RATES[params['uart_baud']]} bps")

            if 'parity' in params and 0 <= params['parity'] < len(PARITY_LABELS):
                print(f"UART Parity:           {PARITY_LABELS[params['parity']]}")

            if 'air_data_rate' in params and 0 <= params['air_data_rate'] < len(AIR_RATE_LABELS):
                print(f"Air Data Rate:         {AIR_RATE_LABELS[params['air_data_rate']]}")

            if 'transmission_power' in params and 0 <= params['transmission_power'] < len(TX_POWER_LABELS):
                print(f"Transmission Power:    {TX_POWER_LABELS[params['transmission_power']]}")

            print(f"Fixed Transmission:    {'Enabled' if params.get('fixed_transmission', 0) else 'Disabled'}")

            if 'wake_up_time' in params and 0 <= params['wake_up_time'] < len(WAKE_TIME_LABELS):
                print(f"Wake-up Time:          {WAKE_TIME_LABELS[params['wake_up_time']]}")

            if 'packet' in params and 0 <= params['packet'] < len(PACKET_LABELS):
                print(f"Packet Length:         {PACKET_LABELS[params['packet']]}")

            # E220-specific parameters
            print(f"Listen Before Talk:    {'Enabled' if params.get('lbt', 0) else 'Disabled'}")
            print(f"Ambient Noise RSSI:    {'Enabled' if params.get('rssi_noise_en', 0) else 'Disabled'}")
            print(f"Data RSSI:             {'Enabled' if params.get('drssi', 0) else 'Disabled'}")
            print(f"Software Mode Switch:  {'Enabled' if params.get('sw_switch', 0) else 'Disabled'}")

            if self.args.output:
                try:
                    with open(self.args.output, 'w') as f:
                        json.dump(params, f, indent=4)
                    logger.info(f"Parameters saved to {self.args.output}")
                except Exception as e:
                    logger.error(f"Failed to save parameters to file: {e}")
        else:
            logger.error("Failed to read parameters from module")
            return 1

        return 0

    def _write_params(self):
        """Write parameters to module"""
        if self.args.input:
            try:
                with open(self.args.input, 'r') as f:
                    params = json.load(f)
                logger.info(f"Parameters loaded from {self.args.input}")
            except Exception as e:
                logger.error(f"Failed to load parameters from file: {e}")
                return 1
        else:
            params = {}

            if self.args.address is not None:
                params["address"] = self.args.address

            if self.args.channel is not None:
                params["chan"] = self.args.channel

            if self.args.uart_baud is not None:
                params["uart_baud"] = self.args.uart_baud

            if self.args.parity is not None:
                params["parity"] = self.args.parity

            if self.args.air_rate is not None:
                params["air_data_rate"] = self.args.air_rate

            if self.args.power is not None:
                params["transmission_power"] = self.args.power

            if self.args.fixed_trans:
                params["fixed_transmission"] = 1

            if self.args.wake_time is not None:
                params["wake_up_time"] = self.args.wake_time

            if self.args.packet is not None:
                params["packet"] = self.args.packet

            # E220-specific parameters
            if self.args.lbt:
                params["lbt"] = 1

            if self.args.erssi:
                params["rssi_noise_en"] = 1

            if self.args.drssi:
                params["drssi"] = 1

            if self.args.sw_switch:
                params["sw_switch"] = 1

        if not params:
            logger.error("No parameters specified to write")
            return 1

        logger.info("Writing parameters to module...")

        if self.module.set_parameters(params):
            logger.info("Parameters written successfully")
            return 0
        else:
            logger.error("Failed to write parameters to module")
            return 1

    def _reset_module(self):
        """Reset the module"""
        logger.info("Resetting module...")

        if self.module.reset_module():
            logger.info("Module reset successfully")
            return 0
        else:
            logger.error("Failed to reset module")
            return 1

    def _factory_reset(self):
        """Reset the module to factory defaults"""
        logger.info("Performing factory reset...")

        if self.module.factory_reset():
            logger.info("Factory reset successful")
            return 0
        else:
            logger.error("Failed to perform factory reset")
            return 1

    def _get_version(self):
        """Get module version information"""
        logger.info("Getting module version...")

        version_info = self.module.version()

        if version_info:
            print(f"Model: {version_info['model']}")
            print(f"Version: {version_info['version']}")
            return 0
        else:
            logger.error("Failed to get module version")
            return 1

    def _save_config(self):
        """Save current module configuration to file"""
        if not self.args.output:
            logger.error("No output file specified")
            return 1

        logger.info("Reading parameters from module...")
        params = self.module.get_parameters()

        if not params:
            logger.error("Failed to read parameters from module")
            return 1

        try:
            with open(self.args.output, 'w') as f:
                json.dump(params, f, indent=4)
            logger.info(f"Configuration saved to {self.args.output}")
            return 0
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return 1

    def _load_config(self):
        """Load and apply configuration from file"""
        if not self.args.input:
            logger.error("No input file specified")
            return 1

        try:
            with open(self.args.input, 'r') as f:
                params = json.load(f)

            logger.info(f"Configuration loaded from {self.args.input}")

            if self.module.set_parameters(params):
                logger.info("Parameters applied successfully")
                return 0
            else:
                logger.error("Failed to apply parameters to module")
                return 1
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return 1

    def _scan_ports(self):
        """Scan and display available serial ports"""
        ports = serial.tools.list_ports.comports()

        if not ports:
            logger.info("No serial ports found")
        else:
            logger.info("Available serial ports:")
            for port in ports:
                print(f"- {port.device}: {port.description}")

        return 0

    def _send_data(self):
        """Send data through the module"""
        if not self.args.data:
            logger.error("No data specified to send")
            return 1

        logger.info(f"Sending data: {self.args.data}")

        if not self.module.set_mode(ModuleMode.NORMAL):
            logger.error("Failed to set module to normal mode")
            return 1

        try:
            self.module.serial.write(self.args.data.encode('utf-8'))
            logger.info("Data sent successfully")
            return 0
        except Exception as e:
            logger.error(f"Failed to send data: {e}")
            return 1


# ============================================================================
# Main Entry Point
# ============================================================================

def setup_arg_parser():
    """Set up the argument parser for CLI mode"""
    parser = argparse.ArgumentParser(description='E220-915MHz LoRa Module Configurator')

    # Global options
    parser.add_argument('--cli', action='store_true', help='Run in command-line mode')
    parser.add_argument('--port', help='Serial port to use (e.g., COM3, /dev/ttyUSB0)')
    parser.add_argument('--baudrate', type=int, default=9600, help='Serial baudrate (default: 9600)')
    parser.add_argument('--use-gpio', action='store_true', help='Use GPIO pins for mode control (Raspberry Pi)')
    parser.add_argument('--m0-pin', type=int, help='GPIO pin number for M0 pin')
    parser.add_argument('--m1-pin', type=int, help='GPIO pin number for M1 pin')
    parser.add_argument('--aux-pin', type=int, help='GPIO pin number for AUX pin')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # read command
    read_parser = subparsers.add_parser('read', help='Read module parameters')
    read_parser.add_argument('--output', '-o', help='Save parameters to file')

    # write command
    write_parser = subparsers.add_parser('write', help='Write module parameters')
    write_parser.add_argument('--input', '-i', help='Load parameters from file')
    write_parser.add_argument('--address', type=int, help='Module address (0-65535)')
    write_parser.add_argument('--channel', type=int, help='Channel (0-80)')
    write_parser.add_argument('--uart-baud', type=int, help='UART baudrate index (0-7)')
    write_parser.add_argument('--parity', type=int, help='UART parity (0=8N1, 1=8O1, 2=8E1)')
    write_parser.add_argument('--air-rate', type=int, help='Air rate index (0-5)')
    write_parser.add_argument('--power', type=int, help='Transmit power index (0=30dBm, 1=27, 2=24, 3=21)')
    write_parser.add_argument('--fixed-trans', action='store_true', help='Enable fixed transmission mode')
    write_parser.add_argument('--wake-time', type=int, help='Wake-up time index (0-7)')
    write_parser.add_argument('--packet', type=int, help='Packet length index (0=240B, 1=128B, 2=64B, 3=32B)')
    # E220-specific parameters
    write_parser.add_argument('--lbt', action='store_true', help='Enable Listen Before Talk')
    write_parser.add_argument('--erssi', action='store_true', help='Enable Ambient Noise RSSI')
    write_parser.add_argument('--drssi', action='store_true', help='Enable Data RSSI')
    write_parser.add_argument('--sw-switch', action='store_true', help='Enable Software Mode Switching')

    # reset command
    subparsers.add_parser('reset', help='Reset the module')

    # factory-reset command
    subparsers.add_parser('factory-reset', help='Reset the module to factory defaults')

    # version command
    subparsers.add_parser('version', help='Get module version information')

    # save-config command
    save_parser = subparsers.add_parser('save-config', help='Save current module configuration to file')
    save_parser.add_argument('--output', '-o', required=True, help='Output file')

    # load-config command
    load_parser = subparsers.add_parser('load-config', help='Load and apply configuration from file')
    load_parser.add_argument('--input', '-i', required=True, help='Input file')

    # scan-ports command
    subparsers.add_parser('scan-ports', help='Scan and display available serial ports')

    # send-data command
    send_parser = subparsers.add_parser('send-data', help='Send data through the module')
    send_parser.add_argument('--data', required=True, help='Data to send')

    return parser

def main():
    """Main entry point"""
    parser = setup_arg_parser()
    args = parser.parse_args()

    # Set up logging level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Run in CLI mode if requested
    if args.cli:
        if not args.command:
            parser.print_help()
            return 1

        if args.command != 'scan-ports' and not args.port:
            logger.error("Serial port must be specified (--port)")
            return 1

        cli = E220CLI(args)
        return cli.run()
    else:
        # Run in GUI mode
        if not HAS_GUI:
            logger.error("GUI dependencies not available. Please install tkinter.")
            return 1

        root = tk.Tk()
        app = E220ConfigGUI(root)
        root.mainloop()
        return 0

if __name__ == "__main__":
    sys.exit(main())
