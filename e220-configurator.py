#!/usr/bin/env python3
"""
E220 LoRa Module Configurator
-----------------------------
A cross-platform application for configuring EBYTE E220 series LoRa modules.
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
__version__ = "1.0.0"

class ModuleMode(Enum):
    """E220 operating modes based on M0 and M1 pins"""
    NORMAL = auto()          # M0=0, M1=0: Transparent transmission mode
    WOR_SENDING = auto()     # M0=1, M1=0: WOR transmitting mode
    WOR_RECEIVING = auto()   # M0=0, M1=1: WOR receiving mode
    CONFIGURATION = auto()   # M0=1, M1=1: Configuration mode (for AT commands)

class E220Module:
    """
    Handles communication with the E220 LoRa module
    """
    def __init__(self, port=None, baudrate=9600, timeout=1, m0_pin=None, m1_pin=None, aux_pin=None, use_gpio=False):
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
        """Set M0 and M1 pins for the specified mode"""
        if not self.use_gpio or not (self.m0_pin and self.m1_pin):
            logger.warning("Cannot set mode pins: GPIO control not available or pins not specified")
            return False
            
        if mode == ModuleMode.NORMAL:
            self.GPIO.output(self.m0_pin, GPIO.LOW)
            self.GPIO.output(self.m1_pin, GPIO.LOW)
        elif mode == ModuleMode.WOR_SENDING:
            self.GPIO.output(self.m0_pin, GPIO.HIGH)
            self.GPIO.output(self.m1_pin, GPIO.LOW)
        elif mode == ModuleMode.WOR_RECEIVING:
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
            
        logger.info(f"Setting module to {mode} mode")
        result = self._set_mode_pins(mode)
        if result:
            self.current_mode = mode
            
        return result
    
    def send_command(self, command, timeout=1):
        """Send AT command to the module and receive response"""
        if not self.serial or not self.serial.is_open:
            logger.error("Not connected to module")
            return None
            
        # Clear any pending data
        self.serial.reset_input_buffer()
        
        # Send command
        cmd_bytes = (command + '\r\n').encode('ascii')
        logger.debug(f"Sending command: {command}")
        self.serial.write(cmd_bytes)
        
        # Read response
        response = ""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.serial.in_waiting:
                char = self.serial.read().decode('ascii', errors='ignore')
                response += char
                
                # Check if response is complete
                if response.endswith('\r\n'):
                    break
                    
            time.sleep(0.01)
        
        response = response.strip()
        logger.debug(f"Response received: {response}")
        return response
    
    def enter_config_mode(self):
        """Enter configuration mode for sending AT commands"""
        return self.set_mode(ModuleMode.CONFIGURATION)
    
    def exit_config_mode(self):
        """Exit configuration mode and return to normal mode"""
        return self.set_mode(ModuleMode.NORMAL)
    
    def get_parameters(self):
        """Read all parameters from the module"""
        if not self.enter_config_mode():
            return None
            
        params = {}
        
        try:
            # Read module address
            response = self.send_command("AT+ADDR=?")
            if response.startswith("AT+ADDR="):
                params["address"] = int(response[8:])
            
            # Read channel
            response = self.send_command("AT+CHANNEL=?")
            if response.startswith("AT+CHANNEL="):
                params["channel"] = int(response[11:])
            
            # Read UART parameters
            response = self.send_command("AT+UART=?")
            if response.startswith("AT+UART="):
                uart_parts = response[8:].split(',')
                if len(uart_parts) == 2:
                    params["baudRate"] = int(uart_parts[0])
                    params["parity"] = int(uart_parts[1])
            
            # Read air rate
            response = self.send_command("AT+RATE=?")
            if response.startswith("AT+RATE="):
                params["airRate"] = int(response[8:])
            
            # Read packet size
            response = self.send_command("AT+PACKET=?")
            if response.startswith("AT+PACKET="):
                params["packetSize"] = int(response[10:])
            
            # Read transmit power
            response = self.send_command("AT+POWER=?")
            if response.startswith("AT+POWER="):
                params["transmitPower"] = int(response[9:])
            
            # Read WOR period
            response = self.send_command("AT+WTIME=?")
            if response.startswith("AT+WTIME="):
                params["worPeriod"] = int(response[9:])
                
            # Read WOR role
            response = self.send_command("AT+WOR=?")
            if response.startswith("AT+WOR="):
                params["worRole"] = int(response[7:])
                
            # Read transmission mode
            response = self.send_command("AT+TRANS=?")
            if response.startswith("AT+TRANS="):
                params["transMode"] = int(response[9:])
                
            # Read LBT enable
            response = self.send_command("AT+LBT=?")
            if response.startswith("AT+LBT="):
                params["lbtEnable"] = int(response[7:])
                
            # Read ambient RSSI enable
            response = self.send_command("AT+ERSSI=?")
            if response.startswith("AT+ERSSI="):
                params["rssiEnable"] = int(response[9:])
                
            # Read data RSSI enable
            response = self.send_command("AT+DRSSI=?")
            if response.startswith("AT+DRSSI="):
                params["dataRssiEnable"] = int(response[9:])
                
            # Read Network ID
            # Note: Not directly readable, using default value
            params["netID"] = 0
            
            # Key is not readable for security reasons
            params["key"] = 0
            
            # Read WOR delay
            response = self.send_command("AT+DELAY=?")
            if response.startswith("AT+DELAY="):
                params["worDelay"] = int(response[9:])
                
            # Read software switching mode
            response = self.send_command("AT+SWITCH=?")
            if response.startswith("AT+SWITCH="):
                params["switchMode"] = int(response[10:])
                
        except Exception as e:
            logger.error(f"Error reading parameters: {e}")
            params = None
            
        finally:
            self.exit_config_mode()
            
        return params
    
    def set_parameters(self, params):
        """Write parameters to the module"""
        if not self.enter_config_mode():
            return False
            
        success = True
        
        try:
            # Set address
            if "address" in params:
                response = self.send_command(f"AT+ADDR={params['address']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set address: {response}")
                    success = False
            
            # Set channel
            if "channel" in params:
                response = self.send_command(f"AT+CHANNEL={params['channel']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set channel: {response}")
                    success = False
            
            # Set UART parameters
            if "baudRate" in params and "parity" in params:
                response = self.send_command(f"AT+UART={params['baudRate']},{params['parity']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set UART parameters: {response}")
                    success = False
            
            # Set air rate
            if "airRate" in params:
                response = self.send_command(f"AT+RATE={params['airRate']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set air rate: {response}")
                    success = False
            
            # Set packet size
            if "packetSize" in params:
                response = self.send_command(f"AT+PACKET={params['packetSize']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set packet size: {response}")
                    success = False
            
            # Set transmit power
            if "transmitPower" in params:
                response = self.send_command(f"AT+POWER={params['transmitPower']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set transmit power: {response}")
                    success = False
            
            # Set WOR period
            if "worPeriod" in params:
                response = self.send_command(f"AT+WTIME={params['worPeriod']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set WOR period: {response}")
                    success = False
                    
            # Set transmission mode
            if "transMode" in params:
                response = self.send_command(f"AT+TRANS={params['transMode']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set transmission mode: {response}")
                    success = False
                    
            # Set LBT enable
            if "lbtEnable" in params:
                response = self.send_command(f"AT+LBT={params['lbtEnable']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set LBT enable: {response}")
                    success = False
                    
            # Set ambient RSSI enable
            if "rssiEnable" in params:
                response = self.send_command(f"AT+ERSSI={params['rssiEnable']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set ambient RSSI enable: {response}")
                    success = False
                    
            # Set data RSSI enable
            if "dataRssiEnable" in params:
                response = self.send_command(f"AT+DRSSI={params['dataRssiEnable']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set data RSSI enable: {response}")
                    success = False
                    
            # Set key (if non-zero)
            if "key" in params and params["key"] > 0:
                response = self.send_command(f"AT+KEY={params['key']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set key: {response}")
                    success = False
                    
            # Set WOR delay
            if "worDelay" in params:
                response = self.send_command(f"AT+DELAY={params['worDelay']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set WOR delay: {response}")
                    success = False
                    
            # Set software switching mode
            if "switchMode" in params:
                response = self.send_command(f"AT+SWITCH={params['switchMode']}")
                if not response.endswith("=OK"):
                    logger.error(f"Failed to set software switching mode: {response}")
                    success = False
                    
        except Exception as e:
            logger.error(f"Error setting parameters: {e}")
            success = False
            
        finally:
            self.exit_config_mode()
            
        return success
    
    def reset_module(self):
        """Reset the module"""
        if not self.enter_config_mode():
            return False
            
        try:
            response = self.send_command("AT+RESET")
            if response.endswith("=OK"):
                logger.info("Module reset successful")
                return True
            else:
                logger.error(f"Module reset failed: {response}")
                return False
        finally:
            self.exit_config_mode()
    
    def factory_reset(self):
        """Reset the module to factory defaults"""
        if not self.enter_config_mode():
            return False
            
        try:
            response = self.send_command("AT+DEFAULT")
            if response.endswith("=OK"):
                logger.info("Factory reset successful")
                return True
            else:
                logger.error(f"Factory reset failed: {response}")
                return False
        finally:
            self.exit_config_mode()
            
    def send_custom_command(self, command):
        """Send a custom AT command to the module"""
        if not self.enter_config_mode():
            return None
            
        try:
            response = self.send_command(command)
            return response
        finally:
            self.exit_config_mode()

class E220ConfigGUI:
    """
    GUI interface for configuring the E220 module
    """
    def __init__(self, master):
        self.master = master
        self.master.title("E220 LoRa Module Configurator")
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
        self.command_tab = ttk.Frame(self.notebook)
        
        self.notebook.add(self.connection_tab, text="Connection")
        self.notebook.add(self.basic_tab, text="Basic Settings")
        self.notebook.add(self.advanced_tab, text="Advanced Settings")
        self.notebook.add(self.command_tab, text="Command Console")
        
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
        self._setup_command_tab()
        
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
        self.baudrate_idx_var = tk.IntVar(value=3)  # Default: 9600 bps
        self.parity_var = tk.IntVar(value=0)        # Default: 8N1
        self.airrate_var = tk.IntVar(value=2)       # Default: 2.4 kbps
        self.power_var = tk.IntVar(value=0)         # Default: Max power
        
        # Advanced settings
        self.packet_size_var = tk.IntVar(value=0)   # Default: 200 bytes
        self.trans_mode_var = tk.IntVar(value=0)    # Default: Transparent
        self.wor_period_var = tk.IntVar(value=0)    # Default: 500ms
        self.wor_role_var = tk.IntVar(value=0)      # Default: Receiver
        self.net_id_var = tk.IntVar(value=0)        # Default: 0
        self.key_var = tk.IntVar(value=0)           # Default: 0 (no encryption)
        self.lbt_var = tk.IntVar(value=0)           # Default: Disabled
        self.rssi_env_var = tk.IntVar(value=0)      # Default: Disabled
        self.rssi_data_var = tk.IntVar(value=0)     # Default: Disabled
        self.wor_delay_var = tk.IntVar(value=0)     # Default: 0ms
        self.switch_mode_var = tk.IntVar(value=0)   # Default: Disabled
    
    def _setup_connection_tab(self):
        """Setup the connection tab"""
        # Create a frame for the connection settings
        conn_frame = ttk.LabelFrame(self.connection_tab, text="Connection Settings")
        conn_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Serial port selection
        ttk.Label(conn_frame, text="Serial Port:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.port_combo = ttk.Combobox(conn_frame, textvariable=self.port_var)
        self.port_combo.grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Button(conn_frame, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=5, pady=5)
        
        # Baud rate selection
        ttk.Label(conn_frame, text="Baud Rate:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        baud_rates = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
        self.baud_combo = ttk.Combobox(conn_frame, textvariable=self.baudrate_var, values=baud_rates)
        self.baud_combo.grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        
        # Connect/Disconnect button
        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self._toggle_connection)
        self.connect_button.grid(row=2, column=0, columnspan=3, padx=5, pady=20)
        
        # Version and info
        ttk.Label(conn_frame, text=f"E220 LoRa Module Configurator v{__version__}").grid(
            row=3, column=0, columnspan=3, padx=5, pady=5
        )
        
        # Description
        desc_text = """This application allows you to configure EBYTE E220 series LoRa modules.
Connect the module to your computer using a USB-to-serial adapter with the following wiring:

- Connect module's M0 and M1 pins to your adapter if you need automatic mode switching
- Make sure the module is powered with 3.3-5V DC
- Default baud rate is 9600 bps
        """
        desc_label = ttk.Label(conn_frame, text=desc_text, justify=tk.LEFT, wraplength=500)
        desc_label.grid(row=4, column=0, columnspan=3, padx=5, pady=10, sticky=tk.W)
        
        # Additional options frame
        options_frame = ttk.LabelFrame(conn_frame, text="Additional Options")
        options_frame.grid(row=5, column=0, columnspan=3, padx=5, pady=10, sticky=tk.W+tk.E)
        
        # GPIO control options (for Raspberry Pi or similar)
        self.use_gpio_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_frame, 
            text="Use GPIO pins for mode control (Raspberry Pi)",
            variable=self.use_gpio_var
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=5)
        
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
        # Create a frame for the basic settings
        basic_frame = ttk.LabelFrame(self.basic_tab, text="Basic Configuration")
        basic_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Module address
        ttk.Label(basic_frame, text="Module Address (0-65535):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(basic_frame, textvariable=self.address_var).grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text="Unique identifier for the module").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Channel
        ttk.Label(basic_frame, text="Channel (0-83):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(basic_frame, textvariable=self.channel_var).grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text="Frequency = Base + Channel*1MHz").grid(row=1, column=2, sticky=tk.W, padx=5, pady=5)
        
        # UART Baud Rate
        ttk.Label(basic_frame, text="UART Baud Rate:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        baud_options = ["1200 bps", "2400 bps", "4800 bps", "9600 bps", "19200 bps", "38400 bps", "57600 bps", "115200 bps"]
        ttk.Combobox(basic_frame, textvariable=self.baudrate_idx_var, values=list(range(len(baud_options))), 
                     state="readonly").grid(row=2, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text=f"Serial port speed").grid(row=2, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed baud rate
        def update_baud_display(*args):
            idx = self.baudrate_idx_var.get()
            if 0 <= idx < len(baud_options):
                baud_label.config(text=f"Selected: {baud_options[idx]}")
        
        # Add a label to display the selected baud rate
        baud_label = ttk.Label(basic_frame, text=f"Selected: {baud_options[self.baudrate_idx_var.get()]}")
        baud_label.grid(row=2, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.baudrate_idx_var.trace_add("write", update_baud_display)
        
        # Parity
        ttk.Label(basic_frame, text="Serial Parity:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        parity_options = ["8N1", "8O1", "8E1", "8N1 (same as 0)"]
        ttk.Combobox(basic_frame, textvariable=self.parity_var, values=list(range(len(parity_options))), 
                    state="readonly").grid(row=3, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text="Serial data format").grid(row=3, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed parity
        def update_parity_display(*args):
            idx = self.parity_var.get()
            if 0 <= idx < len(parity_options):
                parity_label.config(text=f"Selected: {parity_options[idx]}")
        
        # Add a label to display the selected parity
        parity_label = ttk.Label(basic_frame, text=f"Selected: {parity_options[self.parity_var.get()]}")
        parity_label.grid(row=3, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.parity_var.trace_add("write", update_parity_display)
        
        # Air Rate
        ttk.Label(basic_frame, text="Air Rate:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        airrate_options = ["2.4 kbps", "2.4 kbps", "2.4 kbps", "4.8 kbps", "9.6 kbps", "19.2 kbps", "38.4 kbps", "62.5 kbps"]
        ttk.Combobox(basic_frame, textvariable=self.airrate_var, values=list(range(len(airrate_options))), 
                     state="readonly").grid(row=4, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text="Wireless transmission rate").grid(row=4, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed air rate
        def update_airrate_display(*args):
            idx = self.airrate_var.get()
            if 0 <= idx < len(airrate_options):
                airrate_label.config(text=f"Selected: {airrate_options[idx]}")
        
        # Add a label to display the selected air rate
        airrate_label = ttk.Label(basic_frame, text=f"Selected: {airrate_options[self.airrate_var.get()]}")
        airrate_label.grid(row=4, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.airrate_var.trace_add("write", update_airrate_display)
        
        # Transmit Power
        ttk.Label(basic_frame, text="Transmit Power:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        power_options = ["22/30 dBm (max)", "17/27 dBm", "13/24 dBm", "10/21 dBm"]
        ttk.Combobox(basic_frame, textvariable=self.power_var, values=list(range(len(power_options))), 
                     state="readonly").grid(row=5, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(basic_frame, text="RF transmission power").grid(row=5, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed power
        def update_power_display(*args):
            idx = self.power_var.get()
            if 0 <= idx < len(power_options):
                power_label.config(text=f"Selected: {power_options[idx]}")
        
        # Add a label to display the selected power
        power_label = ttk.Label(basic_frame, text=f"Selected: {power_options[self.power_var.get()]}")
        power_label.grid(row=5, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.power_var.trace_add("write", update_power_display)
        
        # Buttons frame
        button_frame = ttk.Frame(basic_frame)
        button_frame.grid(row=6, column=0, columnspan=4, pady=20)
        
        # Read/Write buttons
        ttk.Button(button_frame, text="Read from Module", command=self._read_params).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Write to Module", command=self._write_params).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Reset Module", command=self._reset_module).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Factory Reset", command=self._factory_reset).pack(side=tk.LEFT, padx=10)
    
    def _setup_advanced_tab(self):
        """Setup the advanced settings tab"""
        # Create a frame for the advanced settings
        adv_frame = ttk.LabelFrame(self.advanced_tab, text="Advanced Configuration")
        adv_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Packet Size
        ttk.Label(adv_frame, text="Packet Size:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        packet_options = ["200 bytes", "128 bytes", "64 bytes", "32 bytes"]
        ttk.Combobox(adv_frame, textvariable=self.packet_size_var, values=list(range(len(packet_options))), 
                     state="readonly").grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Maximum data packet size").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed packet size
        def update_packet_display(*args):
            idx = self.packet_size_var.get()
            if 0 <= idx < len(packet_options):
                packet_label.config(text=f"Selected: {packet_options[idx]}")
        
        # Add a label to display the selected packet size
        packet_label = ttk.Label(adv_frame, text=f"Selected: {packet_options[self.packet_size_var.get()]}")
        packet_label.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.packet_size_var.trace_add("write", update_packet_display)
        
        # Transmission Mode
        ttk.Label(adv_frame, text="Transmission Mode:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        trans_options = ["Transparent Transmission", "Fixed Point Transmission"]
        ttk.Combobox(adv_frame, textvariable=self.trans_mode_var, values=list(range(len(trans_options))), 
                     state="readonly").grid(row=1, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Data transmission method").grid(row=1, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed transmission mode
        def update_trans_display(*args):
            idx = self.trans_mode_var.get()
            if 0 <= idx < len(trans_options):
                trans_label.config(text=f"Selected: {trans_options[idx]}")
        
        # Add a label to display the selected transmission mode
        trans_label = ttk.Label(adv_frame, text=f"Selected: {trans_options[self.trans_mode_var.get()]}")
        trans_label.grid(row=1, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.trans_mode_var.trace_add("write", update_trans_display)
        
        # WOR Period
        ttk.Label(adv_frame, text="WOR Period:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        wor_options = ["500 ms", "1000 ms", "1500 ms", "2000 ms", "2500 ms", "3000 ms", "3500 ms", "4000 ms"]
        ttk.Combobox(adv_frame, textvariable=self.wor_period_var, values=list(range(len(wor_options))), 
                     state="readonly").grid(row=2, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Wake-on-radio interval").grid(row=2, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed WOR period
        def update_wor_display(*args):
            idx = self.wor_period_var.get()
            if 0 <= idx < len(wor_options):
                wor_label.config(text=f"Selected: {wor_options[idx]}")
        
        # Add a label to display the selected WOR period
        wor_label = ttk.Label(adv_frame, text=f"Selected: {wor_options[self.wor_period_var.get()]}")
        wor_label.grid(row=2, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.wor_period_var.trace_add("write", update_wor_display)
        
        # WOR Role
        ttk.Label(adv_frame, text="WOR Role:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        wor_role_options = ["WOR Receiver", "WOR Transmitter"]
        ttk.Combobox(adv_frame, textvariable=self.wor_role_var, values=list(range(len(wor_role_options))), 
                     state="readonly").grid(row=3, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Wake-on-radio role").grid(row=3, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed WOR role
        def update_wor_role_display(*args):
            idx = self.wor_role_var.get()
            if 0 <= idx < len(wor_role_options):
                wor_role_label.config(text=f"Selected: {wor_role_options[idx]}")
        
        # Add a label to display the selected WOR role
        wor_role_label = ttk.Label(adv_frame, text=f"Selected: {wor_role_options[self.wor_role_var.get()]}")
        wor_role_label.grid(row=3, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.wor_role_var.trace_add("write", update_wor_role_display)
        
        # Network ID
        ttk.Label(adv_frame, text="Network ID (0-255):").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(adv_frame, textvariable=self.net_id_var).grid(row=4, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Network identifier").grid(row=4, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Encryption Key
        ttk.Label(adv_frame, text="Encryption Key (0-65535):").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(adv_frame, textvariable=self.key_var).grid(row=5, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Data encryption key (0 = disabled)").grid(row=5, column=2, sticky=tk.W, padx=5, pady=5)
        
        # LBT Enable
        ttk.Label(adv_frame, text="Listen Before Talk:").grid(row=6, column=0, sticky=tk.W, padx=5, pady=5)
        lbt_options = ["Disabled", "Enabled"]
        ttk.Combobox(adv_frame, textvariable=self.lbt_var, values=list(range(len(lbt_options))), 
                     state="readonly").grid(row=6, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Check channel before transmission").grid(row=6, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed LBT setting
        def update_lbt_display(*args):
            idx = self.lbt_var.get()
            if 0 <= idx < len(lbt_options):
                lbt_label.config(text=f"Selected: {lbt_options[idx]}")
        
        # Add a label to display the selected LBT setting
        lbt_label = ttk.Label(adv_frame, text=f"Selected: {lbt_options[self.lbt_var.get()]}")
        lbt_label.grid(row=6, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.lbt_var.trace_add("write", update_lbt_display)
        
        # RSSI Ambient Noise Enable
        ttk.Label(adv_frame, text="RSSI Ambient Noise:").grid(row=7, column=0, sticky=tk.W, padx=5, pady=5)
        rssi_env_options = ["Disabled", "Enabled"]
        ttk.Combobox(adv_frame, textvariable=self.rssi_env_var, values=list(range(len(rssi_env_options))), 
                     state="readonly").grid(row=7, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Enable ambient noise RSSI detection").grid(row=7, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed RSSI env setting
        def update_rssi_env_display(*args):
            idx = self.rssi_env_var.get()
            if 0 <= idx < len(rssi_env_options):
                rssi_env_label.config(text=f"Selected: {rssi_env_options[idx]}")
        
        # Add a label to display the selected RSSI env setting
        rssi_env_label = ttk.Label(adv_frame, text=f"Selected: {rssi_env_options[self.rssi_env_var.get()]}")
        rssi_env_label.grid(row=7, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.rssi_env_var.trace_add("write", update_rssi_env_display)
        
        # RSSI Data Enable
        ttk.Label(adv_frame, text="RSSI Data Output:").grid(row=8, column=0, sticky=tk.W, padx=5, pady=5)
        rssi_data_options = ["Disabled", "Enabled"]
        ttk.Combobox(adv_frame, textvariable=self.rssi_data_var, values=list(range(len(rssi_data_options))), 
                     state="readonly").grid(row=8, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Append RSSI to received data").grid(row=8, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed RSSI data setting
        def update_rssi_data_display(*args):
            idx = self.rssi_data_var.get()
            if 0 <= idx < len(rssi_data_options):
                rssi_data_label.config(text=f"Selected: {rssi_data_options[idx]}")
        
        # Add a label to display the selected RSSI data setting
        rssi_data_label = ttk.Label(adv_frame, text=f"Selected: {rssi_data_options[self.rssi_data_var.get()]}")
        rssi_data_label.grid(row=8, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.rssi_data_var.trace_add("write", update_rssi_data_display)
        
        # WOR Delay
        ttk.Label(adv_frame, text="WOR Delay Sleep Time (ms):").grid(row=9, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(adv_frame, textvariable=self.wor_delay_var).grid(row=9, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="WOR delay before sleep (0-65535ms)").grid(row=9, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Software Mode Switching
        ttk.Label(adv_frame, text="Software Mode Switching:").grid(row=10, column=0, sticky=tk.W, padx=5, pady=5)
        switch_options = ["Disabled", "Enabled"]
        ttk.Combobox(adv_frame, textvariable=self.switch_mode_var, values=list(range(len(switch_options))), 
                     state="readonly").grid(row=10, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Label(adv_frame, text="Enable software mode switching").grid(row=10, column=2, sticky=tk.W, padx=5, pady=5)
        
        # Create a function to update the displayed switch mode setting
        def update_switch_display(*args):
            idx = self.switch_mode_var.get()
            if 0 <= idx < len(switch_options):
                switch_label.config(text=f"Selected: {switch_options[idx]}")
        
        # Add a label to display the selected switch mode setting
        switch_label = ttk.Label(adv_frame, text=f"Selected: {switch_options[self.switch_mode_var.get()]}")
        switch_label.grid(row=10, column=3, sticky=tk.W, padx=5, pady=5)
        
        # Bind the variable to the update function
        self.switch_mode_var.trace_add("write", update_switch_display)
        
        # Buttons frame
        button_frame = ttk.Frame(adv_frame)
        button_frame.grid(row=11, column=0, columnspan=4, pady=20)
        
        # Read/Write buttons (same functionality as basic tab)
        ttk.Button(button_frame, text="Read from Module", command=self._read_params).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="Write to Module", command=self._write_params).pack(side=tk.LEFT, padx=10)
    
    def _setup_command_tab(self):
        """Setup the command console tab"""
        # Create a frame for the command console
        cmd_frame = ttk.LabelFrame(self.command_tab, text="AT Command Console")
        cmd_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Command entry
        ttk.Label(cmd_frame, text="Enter AT Command:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.cmd_entry = ttk.Entry(cmd_frame, width=40)
        self.cmd_entry.grid(row=0, column=1, sticky=tk.W+tk.E, padx=5, pady=5)
        ttk.Button(cmd_frame, text="Send", command=self._send_command).grid(row=0, column=2, padx=5, pady=5)
        
        # Response display
        ttk.Label(cmd_frame, text="Response:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.response_text = scrolledtext.ScrolledText(cmd_frame, height=10, width=50)
        self.response_text.grid(row=2, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, padx=5, pady=5)
        
        # Common commands frame
        common_frame = ttk.LabelFrame(cmd_frame, text="Common Commands")
        common_frame.grid(row=3, column=0, columnspan=3, sticky=tk.W+tk.E, padx=5, pady=10)
        
        # Common commands
        common_commands = {
            "Get Version": "AT+HELP=?",
            "Get Address": "AT+ADDR=?",
            "Get Channel": "AT+CHANNEL=?",
            "Get UART": "AT+UART=?",
            "Get Air Rate": "AT+RATE=?",
            "Reset Module": "AT+RESET",
            "Factory Reset": "AT+DEFAULT"
        }
        
        # Create buttons for common commands
        row, col = 0, 0
        for label, cmd in common_commands.items():
            ttk.Button(
                common_frame, 
                text=label, 
                command=lambda c=cmd: self._send_predefined_command(c)
            ).grid(row=row, column=col, padx=5, pady=5, sticky=tk.W)
            col += 1
            if col > 2:
                col = 0
                row += 1
        
        # Command history
        history_frame = ttk.LabelFrame(cmd_frame, text="Command History")
        history_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W+tk.E+tk.N+tk.S, padx=5, pady=10)
        
        self.history_text = scrolledtext.ScrolledText(history_frame, height=6, width=50)
        self.history_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Help text
        help_frame = ttk.LabelFrame(cmd_frame, text="AT Command Help")
        help_frame.grid(row=5, column=0, columnspan=3, sticky=tk.W+tk.E, padx=5, pady=10)
        
        help_text = """
Common AT Commands for E220 Modules:

- AT+HELP=?                    - Show all commands
- AT+ADDR=?                    - Query module address
- AT+ADDR=<value>              - Set module address (0-65535)
- AT+CHANNEL=?                 - Query channel
- AT+CHANNEL=<value>           - Set channel (0-83)
- AT+UART=?                    - Query UART parameters
- AT+UART=<baudrate>,<parity>  - Set UART parameters
- AT+RATE=?                    - Query air rate
- AT+RATE=<value>              - Set air rate (0-7)
- AT+POWER=?                   - Query transmit power
- AT+POWER=<value>             - Set transmit power (0-3)
- AT+RESET                     - Reset the module
- AT+DEFAULT                   - Restore factory settings
        """
        
        help_label = ttk.Label(help_frame, text=help_text, justify=tk.LEFT)
        help_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
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
            m0_pin = self.m0_pin_var.get() if use_gpio else None
            m1_pin = self.m1_pin_var.get() if use_gpio else None
            aux_pin = self.aux_pin_var.get() if use_gpio else None
            
            self.module = E220Module(
                port=port,
                baudrate=baudrate,
                timeout=1,
                m0_pin=m0_pin,
                m1_pin=m1_pin,
                aux_pin=aux_pin,
                use_gpio=use_gpio
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
            self.channel_var.set(params.get("channel", 0))
            self.baudrate_idx_var.set(params.get("baudRate", 3))
            self.parity_var.set(params.get("parity", 0))
            self.airrate_var.set(params.get("airRate", 2))
            self.power_var.set(params.get("transmitPower", 0))
            self.packet_size_var.set(params.get("packetSize", 0))
            self.trans_mode_var.set(params.get("transMode", 0))
            self.wor_period_var.set(params.get("worPeriod", 0))
            self.wor_role_var.set(params.get("worRole", 0))
            self.net_id_var.set(params.get("netID", 0))
            self.key_var.set(params.get("key", 0))
            self.lbt_var.set(params.get("lbtEnable", 0))
            self.rssi_env_var.set(params.get("rssiEnable", 0))
            self.rssi_data_var.set(params.get("dataRssiEnable", 0))
            self.wor_delay_var.set(params.get("worDelay", 0))
            self.switch_mode_var.set(params.get("switchMode", 0))
            
            self.status_var.set("Parameters read successfully")
            self._add_to_history("Read parameters from module")
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
            if not 0 <= channel <= 83:
                raise ValueError("Channel must be between 0 and 83")
                
            net_id = int(self.net_id_var.get())
            if not 0 <= net_id <= 255:
                raise ValueError("Network ID must be between 0 and 255")
                
            key = int(self.key_var.get())
            if not 0 <= key <= 65535:
                raise ValueError("Encryption key must be between 0 and 65535")
                
            wor_delay = int(self.wor_delay_var.get())
            if not 0 <= wor_delay <= 65535:
                raise ValueError("WOR delay must be between 0 and 65535")
                
        except ValueError as e:
            messagebox.showerror("Parameter Error", str(e))
            return
            
        # Collect parameters
        params = {
            "address": self.address_var.get(),
            "channel": self.channel_var.get(),
            "baudRate": self.baudrate_idx_var.get(),
            "parity": self.parity_var.get(),
            "airRate": self.airrate_var.get(),
            "transmitPower": self.power_var.get(),
            "packetSize": self.packet_size_var.get(),
            "transMode": self.trans_mode_var.get(),
            "worPeriod": self.wor_period_var.get(),
            "worRole": self.wor_role_var.get(),
            "netID": self.net_id_var.get(),
            "key": self.key_var.get(),
            "lbtEnable": self.lbt_var.get(),
            "rssiEnable": self.rssi_env_var.get(),
            "dataRssiEnable": self.rssi_data_var.get(),
            "worDelay": self.wor_delay_var.get(),
            "switchMode": self.switch_mode_var.get()
        }
        
        # Ask for confirmation if baudrate is changing
        if params["baudRate"] != 3:  # Default baud rate index (9600 bps)
            baud_options = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
            if not messagebox.askyesno(
                "Confirm Baud Rate Change", 
                f"You are changing the module's baud rate to {baud_options[params['baudRate']]} bps.\n\n"
                "If you continue, you may need to disconnect and reconnect at the new baud rate.\n\n"
                "Are you sure you want to continue?"
            ):
                return
                
        self.status_var.set("Writing parameters to module...")
        self.master.update()
        
        if self.module.set_parameters(params):
            self.status_var.set("Parameters written successfully")
            
            # If baudrate changed, notify the user to reconnect
            if params["baudRate"] != 3:  # Default baud rate index (9600 bps)
                messagebox.showinfo(
                    "Baud Rate Changed",
                    f"The module's baud rate has been changed to {baud_options[params['baudRate']]} bps.\n\n"
                    "Please disconnect and reconnect at the new baud rate."
                )
                
            self._add_to_history("Wrote parameters to module")
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
                self._add_to_history("Reset module")
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
                self._add_to_history("Factory reset module")
                
                # Re-read parameters after factory reset
                self._read_params()
            else:
                self.status_var.set("Failed to perform factory reset")
                messagebox.showerror("Error", "Failed to perform factory reset")
    
    def _send_command(self):
        """Send a custom AT command"""
        if not self.module:
            messagebox.showerror("Error", "Not connected to module")
            return
            
        command = self.cmd_entry.get().strip()
        if not command:
            return
            
        self.status_var.set(f"Sending command: {command}")
        self.master.update()
        
        response = self.module.send_custom_command(command)
        
        if response is not None:
            self.response_text.delete(1.0, tk.END)
            self.response_text.insert(tk.END, response)
            self.status_var.set(f"Command sent: {command}")
            self._add_to_history(f"Sent: {command} -> Received: {response}")
        else:
            self.response_text.delete(1.0, tk.END)
            self.response_text.insert(tk.END, "Error: No response or communication error")
            self.status_var.set("Command failed")
    
    def _send_predefined_command(self, command):
        """Send a predefined AT command"""
        if command:
            self.cmd_entry.delete(0, tk.END)
            self.cmd_entry.insert(0, command)
            self._send_command()
    
    def _add_to_history(self, text):
        """Add entry to command history"""
        timestamp = time.strftime("%H:%M:%S")
        self.history_text.insert(tk.END, f"[{timestamp}] {text}\n")
        self.history_text.see(tk.END)
    
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
            self.address_var.set(config.get("address", 0))
            self.channel_var.set(config.get("channel", 0))
            self.baudrate_idx_var.set(config.get("baudRate", 3))
            self.parity_var.set(config.get("parity", 0))
            self.airrate_var.set(config.get("airRate", 2))
            self.power_var.set(config.get("transmitPower", 0))
            self.packet_size_var.set(config.get("packetSize", 0))
            self.trans_mode_var.set(config.get("transMode", 0))
            self.wor_period_var.set(config.get("worPeriod", 0))
            self.wor_role_var.set(config.get("worRole", 0))
            self.net_id_var.set(config.get("netID", 0))
            self.key_var.set(config.get("key", 0))
            self.lbt_var.set(config.get("lbtEnable", 0))
            self.rssi_env_var.set(config.get("rssiEnable", 0))
            self.rssi_data_var.set(config.get("dataRssiEnable", 0))
            self.wor_delay_var.set(config.get("worDelay", 0))
            self.switch_mode_var.set(config.get("switchMode", 0))
            
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
                "channel": self.channel_var.get(),
                "baudRate": self.baudrate_idx_var.get(),
                "parity": self.parity_var.get(),
                "airRate": self.airrate_var.get(),
                "transmitPower": self.power_var.get(),
                "packetSize": self.packet_size_var.get(),
                "transMode": self.trans_mode_var.get(),
                "worPeriod": self.wor_period_var.get(),
                "worRole": self.wor_role_var.get(),
                "netID": self.net_id_var.get(),
                "key": self.key_var.get(),
                "lbtEnable": self.lbt_var.get(),
                "rssiEnable": self.rssi_env_var.get(),
                "dataRssiEnable": self.rssi_data_var.get(),
                "worDelay": self.wor_delay_var.get(),
                "switchMode": self.switch_mode_var.get()
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


class E220CLI:
    """
    Command-line interface for configuring the E220 module
    """
    def __init__(self, args):
        self.args = args
        self.module = None
        
    def run(self):
        """Run the CLI based on arguments"""
        # Connect to the module
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
            # Handle command
            if self.args.command == 'read':
                self._read_params()
            elif self.args.command == 'write':
                self._write_params()
            elif self.args.command == 'reset':
                self._reset_module()
            elif self.args.command == 'factory-reset':
                self._factory_reset()
            elif self.args.command == 'send-command':
                self._send_command()
            elif self.args.command == 'save-config':
                self._save_config()
            elif self.args.command == 'load-config':
                self._load_config()
            elif self.args.command == 'scan-ports':
                self._scan_ports()
            else:
                logger.error(f"Unknown command: {self.args.command}")
                return 1
                
            return 0
        finally:
            self.module.disconnect()
            
    def _read_params(self):
        """Read and display module parameters"""
        logger.info("Reading parameters from module...")
        
        params = self.module.get_parameters()
        
        if params:
            logger.info("Module parameters:")
            
            # Format parameters for display
            baud_rates = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]
            parity_options = ["8N1", "8O1", "8E1", "8N1 (same as 0)"]
            air_rates = ["2.4k", "2.4k", "2.4k", "4.8k", "9.6k", "19.2k", "38.4k", "62.5k"]
            power_options = ["22/30 dBm", "17/27 dBm", "13/24 dBm", "10/21 dBm"]
            packet_options = ["200 bytes", "128 bytes", "64 bytes", "32 bytes"]
            trans_options = ["Transparent", "Fixed Point"]
            wor_options = ["500ms", "1000ms", "1500ms", "2000ms", "2500ms", "3000ms", "3500ms", "4000ms"]
            wor_role_options = ["Receiver", "Transmitter"]
            
            # Print formatted parameters
            print(f"Address:                {params['address']}")
            print(f"Channel:                {params['channel']} ({params['channel'] + 410}MHz for 433 band, {params['channel'] + 850}MHz for 868 band)")
            
            if 0 <= params['baudRate'] < len(baud_rates):
                print(f"UART Baud Rate:         {baud_rates[params['baudRate']]} bps")
            
            if 0 <= params['parity'] < len(parity_options):
                print(f"UART Parity:            {parity_options[params['parity']]}")
            
            if 0 <= params['airRate'] < len(air_rates):
                print(f"Air Rate:               {air_rates[params['airRate']]}")
            
            if 0 <= params['transmitPower'] < len(power_options):
                print(f"Transmit Power:         {power_options[params['transmitPower']]}")
            
            if 0 <= params['packetSize'] < len(packet_options):
                print(f"Packet Size:            {packet_options[params['packetSize']]}")
            
            if 0 <= params['transMode'] < len(trans_options):
                print(f"Transmission Mode:      {trans_options[params['transMode']]}")
            
            if 0 <= params['worPeriod'] < len(wor_options):
                print(f"WOR Period:             {wor_options[params['worPeriod']]}")
            
            if 0 <= params['worRole'] < len(wor_role_options):
                print(f"WOR Role:               {wor_role_options[params['worRole']]}")
            
            print(f"Network ID:             {params['netID']}")
            print(f"Encryption Key:         {params.get('key', 'Not readable')}")
            print(f"LBT Enable:             {'Enabled' if params['lbtEnable'] else 'Disabled'}")
            print(f"RSSI Ambient Noise:     {'Enabled' if params['rssiEnable'] else 'Disabled'}")
            print(f"RSSI Data Output:       {'Enabled' if params['dataRssiEnable'] else 'Disabled'}")
            print(f"WOR Delay:              {params['worDelay']} ms")
            print(f"Software Mode Switch:   {'Enabled' if params['switchMode'] else 'Disabled'}")
            
            if self.args.output:
                # Save to file
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
        # Load parameters from file if specified
        if self.args.input:
            try:
                with open(self.args.input, 'r') as f:
                    params = json.load(f)
                logger.info(f"Parameters loaded from {self.args.input}")
            except Exception as e:
                logger.error(f"Failed to load parameters from file: {e}")
                return 1
        else:
            # Collect parameters from command line
            params = {}
            
            if self.args.address is not None:
                params["address"] = self.args.address
                
            if self.args.channel is not None:
                params["channel"] = self.args.channel
                
            if self.args.baudrate_idx is not None:
                params["baudRate"] = self.args.baudrate_idx
                
            if self.args.parity is not None:
                params["parity"] = self.args.parity
                
            if self.args.airrate is not None:
                params["airRate"] = self.args.airrate
                
            if self.args.power is not None:
                params["transmitPower"] = self.args.power
                
            if self.args.packet_size is not None:
                params["packetSize"] = self.args.packet_size
                
            if self.args.trans_mode is not None:
                params["transMode"] = self.args.trans_mode
                
            if self.args.wor_period is not None:
                params["worPeriod"] = self.args.wor_period
                
            if self.args.wor_role is not None:
                params["worRole"] = self.args.wor_role
                
            if self.args.net_id is not None:
                params["netID"] = self.args.net_id
                
            if self.args.key is not None:
                params["key"] = self.args.key
                
            if self.args.lbt is not None:
                params["lbtEnable"] = 1 if self.args.lbt else 0
                
            if self.args.rssi_env is not None:
                params["rssiEnable"] = 1 if self.args.rssi_env else 0
                
            if self.args.rssi_data is not None:
                params["dataRssiEnable"] = 1 if self.args.rssi_data else 0
                
            if self.args.wor_delay is not None:
                params["worDelay"] = self.args.wor_delay
                
            if self.args.switch_mode is not None:
                params["switchMode"] = 1 if self.args.switch_mode else 0
        
        # Check if we have parameters to write
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
    
    def _send_command(self):
        """Send a custom AT command"""
        if not self.args.at_command:
            logger.error("No AT command specified")
            return 1
            
        command = self.args.at_command
        logger.info(f"Sending command: {command}")
        
        response = self.module.send_custom_command(command)
        
        if response is not None:
            logger.info(f"Response: {response}")
            return 0
        else:
            logger.error("Failed to send command or no response received")
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


def setup_arg_parser():
    """Set up the argument parser for CLI mode"""
    parser = argparse.ArgumentParser(description='E220 LoRa Module Configurator')
    
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
    write_parser.add_argument('--channel', type=int, help='Channel (0-83)')
    write_parser.add_argument('--baudrate-idx', type=int, help='UART baudrate index (0-7)')
    write_parser.add_argument('--parity', type=int, help='UART parity (0-3)')
    write_parser.add_argument('--airrate', type=int, help='Air rate index (0-7)')
    write_parser.add_argument('--power', type=int, help='Transmit power index (0-3)')
    write_parser.add_argument('--packet-size', type=int, help='Packet size index (0-3)')
    write_parser.add_argument('--trans-mode', type=int, help='Transmission mode (0=transparent, 1=fixed)')
    write_parser.add_argument('--wor-period', type=int, help='WOR period index (0-7)')
    write_parser.add_argument('--wor-role', type=int, help='WOR role (0=receiver, 1=transmitter)')
    write_parser.add_argument('--net-id', type=int, help='Network ID (0-255)')
    write_parser.add_argument('--key', type=int, help='Encryption key (0-65535)')
    write_parser.add_argument('--lbt', type=bool, help='Listen Before Talk enable (True/False)')
    write_parser.add_argument('--rssi-env', type=bool, help='RSSI ambient noise enable (True/False)')
    write_parser.add_argument('--rssi-data', type=bool, help='RSSI data output enable (True/False)')
    write_parser.add_argument('--wor-delay', type=int, help='WOR delay sleep time (0-65535ms)')
    write_parser.add_argument('--switch-mode', type=bool, help='Software mode switching enable (True/False)')
    
    # reset command
    subparsers.add_parser('reset', help='Reset the module')
    
    # factory-reset command
    subparsers.add_parser('factory-reset', help='Reset the module to factory defaults')
    
    # send-command
    send_parser = subparsers.add_parser('send-command', help='Send a custom AT command')
    send_parser.add_argument('at_command', help='AT command to send')
    
    # save-config command
    save_parser = subparsers.add_parser('save-config', help='Save current module configuration to file')
    save_parser.add_argument('--output', '-o', required=True, help='Output file')
    
    # load-config command
    load_parser = subparsers.add_parser('load-config', help='Load and apply configuration from file')
    load_parser.add_argument('--input', '-i', required=True, help='Input file')
    
    # scan-ports command
    subparsers.add_parser('scan-ports', help='Scan and display available serial ports')
    
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