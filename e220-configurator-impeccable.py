#!/usr/bin/env python3
"""
E220-915MHz LoRa Module Configurator - Impeccable GUI Edition
============================================================

A beautifully designed, production-grade GUI for configuring EBYTE E220 LoRa modules.
This version implements Impeccable design principles:
- Industrial/utilitarian aesthetic with technical refinement
- Clear visual hierarchy and progressive disclosure
- Real-time frequency display and register visualization
- Professional dark theme optimized for workbench environments
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import tkinter.font as tkFont
import serial
import serial.tools.list_ports
import sys
import os
import logging

# Import the core E220Module from the main configurator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib.util import spec_from_file_location, module_from_spec

spec = spec_from_file_location("e220_main", "e220-configurator.py")
e220_main = module_from_spec(spec)
spec.loader.exec_module(e220_main)

# Copy necessary classes and constants
E220Module = e220_main.E220Module
ModuleMode = e220_main.ModuleMode
FREQ_BASE = e220_main.FREQ_BASE
FREQ_STEP = e220_main.FREQ_STEP
UART_BAUD_RATES = e220_main.UART_BAUD_RATES
AIR_DATA_RATES = e220_main.AIR_DATA_RATES
AIR_RATE_LABELS = e220_main.AIR_RATE_LABELS
TX_POWER_DBM = e220_main.TX_POWER_DBM
TX_POWER_LABELS = e220_main.TX_POWER_LABELS
PARITY_LABELS = e220_main.PARITY_LABELS
WAKE_TIME_MS = e220_main.WAKE_TIME_MS
WAKE_TIME_LABELS = e220_main.WAKE_TIME_LABELS
PACKET_LENGTHS = e220_main.PACKET_LENGTHS
PACKET_LABELS = e220_main.PACKET_LABELS

logger = logging.getLogger("E220-GUI-Impeccable")

# ============================================================================
# Color Palette (900 MHz inspired - warm amber/gold on dark background)
# ============================================================================
COLORS = {
    "bg_primary": "#0f0f0f",      # Pure black background
    "bg_secondary": "#1a1a1a",    # Slightly lighter for cards/sections
    "bg_tertiary": "#252525",     # Lighter for interactive elements
    "accent_primary": "#d97706",   # Warm amber (900 MHz band color)
    "accent_secondary": "#06b6d4", # Teal (frequency complementary)
    "text_primary": "#f5f5f5",     # Off-white text
    "text_secondary": "#a3a3a3",   # Dimmed text for labels
    "text_tertiary": "#737373",    # Even dimmer for hints
    "success": "#10b981",          # Green for success states
    "warning": "#f59e0b",          # Amber for warnings
    "error": "#ef4444",            # Red for errors
    "border": "#404040",           # Subtle borders
}

# ============================================================================
# E220 Impeccable GUI Class
# ============================================================================

class E220ImpeccableGUI:
    """
    Impeccable design implementation of E220 Configurator GUI.
    
    Design principles:
    - Industrial/utilitarian aesthetic with technical refinement
    - Progressive disclosure (basic → advanced)
    - Real-time feedback (frequency, register values)
    - Dark theme optimized for workbench environments
    - High contrast, keyboard-navigable, clear focus states
    """
    
    def __init__(self, root):
        self.root = root
        self.root.title("E220 LoRa Module Configurator")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 600)
        
        # Configure window colors
        self.root.configure(bg=COLORS["bg_primary"])
        
        # Configure fonts
        self._setup_fonts()
        
        # Module instance
        self.module = None
        self.connected = False
        
        # Initialize parameter variables
        self._init_vars()
        
        # Build UI
        self._build_ui()
        
        # Set up window close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _setup_fonts(self):
        """Configure typography system"""
        # Display font (headings)
        self.font_display = tkFont.Font(family="TkDefaultFont", size=16, weight="bold")
        self.font_heading = tkFont.Font(family="TkDefaultFont", size=12, weight="bold")
        self.font_label = tkFont.Font(family="TkDefaultFont", size=10)
        self.font_value = tkFont.Font(family="Courier", size=10, weight="bold")
        self.font_hint = tkFont.Font(family="TkDefaultFont", size=8)
    
    def _init_vars(self):
        """Initialize all parameter variables"""
        # Connection
        self.port_var = tk.StringVar()
        self.baudrate_var = tk.IntVar(value=9600)
        
        # Basic parameters
        self.address_var = tk.StringVar(value="0000")
        self.channel_var = tk.IntVar(value=0)
        self.uart_baud_var = tk.IntVar(value=3)
        self.parity_var = tk.IntVar(value=0)
        self.air_rate_var = tk.IntVar(value=0)
        self.power_var = tk.IntVar(value=0)
        
        # Advanced parameters
        self.fixed_trans_var = tk.BooleanVar(value=False)
        self.wake_time_var = tk.IntVar(value=0)
        self.packet_var = tk.IntVar(value=0)
        self.lbt_var = tk.BooleanVar(value=False)
        self.erssi_var = tk.BooleanVar(value=False)
        self.drssi_var = tk.BooleanVar(value=False)
        self.sw_switch_var = tk.BooleanVar(value=False)
        
        # Status
        self.status_var = tk.StringVar(value="●  Disconnected")
        self.frequency_var = tk.StringVar(value="900.125 MHz")
        
        # Add trace callbacks for display label updates
        self.uart_baud_var.trace_add("write", self._update_baud_display)
        self.air_rate_var.trace_add("write", self._update_air_rate_display)
        self.power_var.trace_add("write", self._update_power_display)
    
    def _build_ui(self):
        """Build the complete UI with impeccable design"""
        # Main container with dark background
        main_container = tk.Frame(self.root, bg=COLORS["bg_primary"])
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Top header with connection status
        self._build_header(main_container)
        
        # Horizontal layout: Left sidebar + Main content area
        content_container = tk.Frame(main_container, bg=COLORS["bg_primary"])
        content_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        
        # Left sidebar: Navigation + Connection
        self._build_left_sidebar(content_container)
        
        # Main content area: Tabs
        self._build_main_content(content_container)
        
        # Right info panel: Real-time status
        self._build_right_panel(content_container)
        
        # Bottom status bar
        self._build_footer(main_container)
    
    def _build_header(self, parent):
        """Build top header with connection status and title"""
        header = tk.Frame(parent, bg=COLORS["bg_secondary"], height=60)
        header.pack(fill=tk.X, padx=0, pady=0)
        header.pack_propagate(False)
        
        # Title
        title = tk.Label(
            header,
            text="E220 LoRa Module Configurator",
            font=self.font_display,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_primary"]
        )
        title.pack(side=tk.LEFT, padx=16, pady=12)
        
        # Connection status indicator
        status_frame = tk.Frame(header, bg=COLORS["bg_secondary"])
        status_frame.pack(side=tk.RIGHT, padx=16, pady=12)
        
        self.status_indicator = tk.Label(
            status_frame,
            textvariable=self.status_var,
            font=self.font_label,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_tertiary"]
        )
        self.status_indicator.pack(side=tk.LEFT)
    
    def _build_left_sidebar(self, parent):
        """Build left sidebar with connection controls"""
        sidebar = tk.Frame(parent, bg=COLORS["bg_secondary"], width=280)
        sidebar.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 12))
        sidebar.pack_propagate(False)
        
        # Connection section header
        conn_header = tk.Label(
            sidebar,
            text="Connection",
            font=self.font_heading,
            bg=COLORS["bg_secondary"],
            fg=COLORS["accent_primary"]
        )
        conn_header.pack(padx=12, pady=(12, 8), anchor=tk.W)
        
        # Serial port selector
        tk.Label(
            sidebar,
            text="Serial Port",
            font=self.font_label,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_secondary"]
        ).pack(padx=12, pady=(8, 2), anchor=tk.W)
        
        port_frame = tk.Frame(sidebar, bg=COLORS["bg_secondary"])
        port_frame.pack(padx=12, pady=(0, 12), fill=tk.X)
        
        self.port_combo = ttk.Combobox(
            port_frame,
            textvariable=self.port_var,
            width=30,
            state="readonly"
        )
        self.port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        refresh_btn = tk.Button(
            port_frame,
            text="↻",
            command=self._refresh_ports,
            font=self.font_label,
            width=2,
            bg=COLORS["bg_tertiary"],
            fg=COLORS["accent_secondary"],
            activebackground=COLORS["accent_secondary"],
            activeforeground=COLORS["bg_primary"],
            relief=tk.FLAT,
            bd=0
        )
        refresh_btn.pack(side=tk.RIGHT, padx=(4, 0))
        
        # Baud rate selector
        tk.Label(
            sidebar,
            text="Baud Rate",
            font=self.font_label,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_secondary"]
        ).pack(padx=12, pady=(12, 2), anchor=tk.W)
        
        baud_combo = ttk.Combobox(
            sidebar,
            textvariable=self.baudrate_var,
            values=UART_BAUD_RATES,
            state="readonly",
            width=30
        )
        baud_combo.pack(padx=12, pady=(0, 12), fill=tk.X)
        
        # Connect/Disconnect button
        self.connect_btn = tk.Button(
            sidebar,
            text="▶ Connect",
            command=self._toggle_connection,
            font=self.font_heading,
            bg=COLORS["accent_primary"],
            fg=COLORS["bg_primary"],
            activebackground=COLORS["warning"],
            activeforeground=COLORS["bg_primary"],
            relief=tk.FLAT,
            bd=0,
            pady=8,
            padx=12
        )
        self.connect_btn.pack(padx=12, pady=8, fill=tk.X)
        
        # Separator
        separator = tk.Frame(sidebar, bg=COLORS["border"], height=1)
        separator.pack(padx=12, pady=16, fill=tk.X)
        
        # Quick actions
        actions_header = tk.Label(
            sidebar,
            text="Quick Actions",
            font=self.font_heading,
            bg=COLORS["bg_secondary"],
            fg=COLORS["accent_primary"]
        )
        actions_header.pack(padx=12, pady=(8, 8), anchor=tk.W)
        
        action_buttons = [
            ("📖 Read Config", self._read_config),
            ("✏️  Write to Module", self._write_to_module),
            ("💾 Save Config", self._save_config),
            ("📂 Load Config", self._load_config),
            ("🔄 Reset Module", self._reset_module),
        ]
        
        for label, command in action_buttons:
            btn = tk.Button(
                sidebar,
                text=label,
                command=command,
                font=self.font_label,
                bg=COLORS["bg_tertiary"],
                fg=COLORS["text_primary"],
                activebackground=COLORS["accent_secondary"],
                activeforeground=COLORS["bg_primary"],
                relief=tk.FLAT,
                bd=0,
                padx=8,
                pady=6
            )
            btn.pack(padx=12, pady=4, fill=tk.X)
    
    def _build_main_content(self, parent):
        """Build main content area with tabs"""
        content = tk.Frame(parent, bg=COLORS["bg_secondary"])
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Tab buttons (custom implementation for better styling)
        tab_frame = tk.Frame(content, bg=COLORS["bg_tertiary"])
        tab_frame.pack(fill=tk.X, padx=0, pady=0)
        
        self.tabs = {}
        self.tab_buttons = {}
        
        for i, (tab_name, tab_label) in enumerate([
            ("basic", "Basic Settings"),
            ("advanced", "Advanced Settings"),
            ("monitor", "Monitor"),
        ]):
            btn = tk.Button(
                tab_frame,
                text=tab_label,
                font=self.font_label,
                bg=COLORS["bg_tertiary"],
                fg=COLORS["text_secondary"],
                activebackground=COLORS["accent_primary"],
                activeforeground=COLORS["bg_primary"],
                relief=tk.FLAT,
                bd=0,
                padx=12,
                pady=8,
                command=lambda t=tab_name: self._switch_tab(t)
            )
            btn.pack(side=tk.LEFT, padx=4, pady=4)
            self.tab_buttons[tab_name] = btn
        
        # Tab content area
        self.tab_content = tk.Frame(content, bg=COLORS["bg_secondary"])
        self.tab_content.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        
        # Build individual tabs
        self._build_basic_tab()
        self._build_advanced_tab()
        self._build_monitor_tab()
        
        # Show basic tab by default
        self._switch_tab("basic")
    
    def _build_basic_tab(self):
        """Build basic settings tab"""
        self.tabs["basic"] = tk.Frame(self.tab_content, bg=COLORS["bg_secondary"])
        
        # Address section
        self._add_parameter_field(
            self.tabs["basic"], "Address (0-65535)", self.address_var,
            "Device address for fixed-point transmission", 0
        )
        
        # Frequency section (with live display)
        freq_frame = self._add_parameter_row(self.tabs["basic"], "Frequency", 1)
        
        channel_frame = tk.Frame(freq_frame, bg=COLORS["bg_secondary"])
        channel_frame.pack(fill=tk.X, pady=4)
        
        tk.Label(
            channel_frame,
            text="Channel (0-80)",
            font=self.font_label,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_secondary"]
        ).pack(side=tk.LEFT, padx=4)
        
        scale = tk.Scale(
            channel_frame,
            from_=0, to=80,
            variable=self.channel_var,
            orient=tk.HORIZONTAL,
            bg=COLORS["bg_tertiary"],
            fg=COLORS["accent_primary"],
            troughcolor=COLORS["bg_secondary"],
            command=lambda v: self._update_frequency_display()
        )
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        
        # Frequency display
        freq_display = tk.Frame(freq_frame, bg=COLORS["bg_tertiary"], relief=tk.SUNKEN, bd=1)
        freq_display.pack(fill=tk.X, pady=4)
        
        tk.Label(
            freq_display,
            textvariable=self.frequency_var,
            font=self.font_value,
            bg=COLORS["bg_tertiary"],
            fg=COLORS["accent_primary"]
        ).pack(padx=8, pady=6)
        
        # UART settings - use indices, not labels
        self._add_combobox_field(
            self.tabs["basic"], "UART Baud Rate",
            self.uart_baud_var, list(range(len(UART_BAUD_RATES))),
            "Serial port communication speed", 2
        )
        
        self._add_combobox_field(
            self.tabs["basic"], "UART Parity",
            self.parity_var, list(range(len(PARITY_LABELS))),
            "Serial port parity setting", 3
        )
        
        # Radio settings - use indices, not labels
        self._add_combobox_field(
            self.tabs["basic"], "Air Data Rate",
            self.air_rate_var, list(range(len(AIR_RATE_LABELS))),
            "Wireless transmission speed (kbps)", 4
        )
        
        self._add_combobox_field(
            self.tabs["basic"], "Transmit Power",
            self.power_var, list(range(len(TX_POWER_LABELS))),
            "RF transmitter output power", 5
        )
    
    def _build_advanced_tab(self):
        """Build advanced settings tab"""
        self.tabs["advanced"] = tk.Frame(self.tab_content, bg=COLORS["bg_secondary"])
        
        # WOR and transmission mode
        self._add_checkbox_field(
            self.tabs["advanced"], "Fixed Transmission Mode",
            self.fixed_trans_var,
            "Enable fixed-point transmission (with address headers)", 0
        )
        
        self._add_combobox_field(
            self.tabs["advanced"], "WOR Wake Time",
            self.wake_time_var, WAKE_TIME_LABELS,
            "Time interval for WOR (Wake on Radio) mode", 1
        )
        
        self._add_combobox_field(
            self.tabs["advanced"], "Packet Length",
            self.packet_var, PACKET_LABELS,
            "Maximum bytes per wireless packet", 2
        )
        
        # E220-specific features
        section_header = tk.Label(
            self.tabs["advanced"],
            text="E220-Specific Features",
            font=self.font_heading,
            bg=COLORS["bg_secondary"],
            fg=COLORS["accent_secondary"]
        )
        section_header.pack(padx=12, pady=(16, 8), anchor=tk.W)
        
        self._add_checkbox_field(
            self.tabs["advanced"], "Listen Before Talk (LBT)",
            self.lbt_var,
            "Check channel before transmitting to avoid collisions", 3
        )
        
        self._add_checkbox_field(
            self.tabs["advanced"], "Ambient Noise RSSI",
            self.erssi_var,
            "Enable monitoring of environmental RF noise levels", 4
        )
        
        self._add_checkbox_field(
            self.tabs["advanced"], "Data RSSI",
            self.drssi_var,
            "Append RSSI value to received data packets", 5
        )
        
        self._add_checkbox_field(
            self.tabs["advanced"], "Software Mode Switching",
            self.sw_switch_var,
            "Allow mode changes via serial commands", 6
        )
    
    def _build_monitor_tab(self):
        """Build monitoring/debugging tab"""
        self.tabs["monitor"] = tk.Frame(self.tab_content, bg=COLORS["bg_secondary"])
        
        # Register display
        header = tk.Label(
            self.tabs["monitor"],
            text="Register Values (Hex)",
            font=self.font_heading,
            bg=COLORS["bg_secondary"],
            fg=COLORS["accent_primary"]
        )
        header.pack(padx=12, pady=12, anchor=tk.W)
        
        reg_frame = tk.Frame(self.tabs["monitor"], bg=COLORS["bg_tertiary"], relief=tk.SUNKEN, bd=1)
        reg_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)
        
        self.register_text = tk.Label(
            reg_frame,
            text="No data",
            font=self.font_value,
            bg=COLORS["bg_tertiary"],
            fg=COLORS["accent_secondary"],
            justify=tk.LEFT
        )
        self.register_text.pack(padx=8, pady=8)
        
        # Refresh button
        refresh_btn = tk.Button(
            self.tabs["monitor"],
            text="🔄 Refresh Registers",
            command=self._refresh_registers,
            font=self.font_label,
            bg=COLORS["bg_tertiary"],
            fg=COLORS["text_primary"],
            activebackground=COLORS["accent_secondary"],
            activeforeground=COLORS["bg_primary"],
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=6
        )
        refresh_btn.pack(padx=12, pady=8)
    
    def _build_right_panel(self, parent):
        """Build right info panel with real-time status"""
        panel = tk.Frame(parent, bg=COLORS["bg_secondary"], width=260)
        panel.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(12, 0))
        panel.pack_propagate(False)
        
        header = tk.Label(
            panel,
            text="Quick Info",
            font=self.font_heading,
            bg=COLORS["bg_secondary"],
            fg=COLORS["accent_secondary"]
        )
        header.pack(padx=12, pady=(12, 8), anchor=tk.W)
        
        # Info items
        self.info_labels = {}
        info_items = [
            ("Frequency", "frequency_var"),
            ("Baud Rate", "uart_baud_var"),
            ("Air Rate", "air_rate_var"),
            ("Power", "power_var"),
            ("Channel", "channel_var"),
            ("Address", "address_var"),
        ]
        
        for label, var_name in info_items:
            info_frame = tk.Frame(panel, bg=COLORS["bg_secondary"])
            info_frame.pack(fill=tk.X, padx=12, pady=6)
            
            tk.Label(
                info_frame,
                text=f"{label}:",
                font=self.font_label,
                bg=COLORS["bg_secondary"],
                fg=COLORS["text_secondary"]
            ).pack(anchor=tk.W)
            
            value_label = tk.Label(
                info_frame,
                text="—",
                font=self.font_value,
                bg=COLORS["bg_secondary"],
                fg=COLORS["accent_primary"]
            )
            value_label.pack(anchor=tk.W, padx=(8, 0))
            
            self.info_labels[label.lower()] = value_label
    
    def _build_footer(self, parent):
        """Build bottom footer with status bar"""
        footer = tk.Frame(parent, bg=COLORS["bg_secondary"], height=40)
        footer.pack(fill=tk.X, side=tk.BOTTOM, padx=0, pady=0)
        footer.pack_propagate(False)
        
        status = tk.Label(
            footer,
            text="● Ready",
            font=self.font_label,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_tertiary"]
        )
        status.pack(side=tk.LEFT, padx=16, pady=8)
    
    # UI Helper Methods
    
    def _add_parameter_field(self, parent, label, variable, hint, row):
        """Add a text input field for a parameter"""
        row_frame = self._add_parameter_row(parent, label, row, hint)
        
        entry = tk.Entry(
            row_frame,
            textvariable=variable,
            font=self.font_label,
            bg=COLORS["bg_tertiary"],
            fg=COLORS["text_primary"],
            insertbackground=COLORS["accent_primary"],
            relief=tk.FLAT,
            bd=0,
            width=20
        )
        entry.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
    
    def _add_combobox_field(self, parent, label, variable, values, hint, row):
        """Add a dropdown field for a parameter"""
        row_frame = self._add_parameter_row(parent, label, row, hint)
        
        combo = ttk.Combobox(
            row_frame,
            textvariable=variable,
            values=values,
            state="readonly",
            width=20
        )
        combo.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
    
    def _add_checkbox_field(self, parent, label, variable, hint, row):
        """Add a checkbox field for a parameter"""
        row_frame = tk.Frame(parent, bg=COLORS["bg_secondary"])
        row_frame.pack(fill=tk.X, padx=12, pady=8)
        
        checkbox = tk.Checkbutton(
            row_frame,
            text=label,
            variable=variable,
            font=self.font_label,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_primary"],
            activebackground=COLORS["bg_secondary"],
            activeforeground=COLORS["accent_primary"],
            selectcolor=COLORS["accent_primary"],
            relief=tk.FLAT,
            bd=0
        )
        checkbox.pack(anchor=tk.W)
        
        hint_label = tk.Label(
            row_frame,
            text=hint,
            font=self.font_hint,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_tertiary"]
        )
        hint_label.pack(anchor=tk.W, padx=(20, 0), pady=(2, 0))
    
    def _add_parameter_row(self, parent, label, row, hint=""):
        """Add a parameter row with label"""
        row_frame = tk.Frame(parent, bg=COLORS["bg_secondary"])
        row_frame.pack(fill=tk.X, padx=12, pady=8)
        
        label_widget = tk.Label(
            row_frame,
            text=label,
            font=self.font_label,
            bg=COLORS["bg_secondary"],
            fg=COLORS["text_secondary"]
        )
        label_widget.pack(anchor=tk.W, pady=(0, 4))
        
        if hint:
            hint_widget = tk.Label(
                row_frame,
                text=hint,
                font=self.font_hint,
                bg=COLORS["bg_secondary"],
                fg=COLORS["text_tertiary"]
            )
            hint_widget.pack(anchor=tk.W, pady=(0, 4))
        
        return row_frame
    
    def _switch_tab(self, tab_name):
        """Switch to a different tab"""
        # Hide all tabs
        for tab in self.tabs.values():
            tab.pack_forget()
        
        # Reset button colors
        for btn in self.tab_buttons.values():
            btn.config(bg=COLORS["bg_tertiary"], fg=COLORS["text_secondary"])
        
        # Show selected tab
        self.tabs[tab_name].pack(fill=tk.BOTH, expand=True)
        self.tab_buttons[tab_name].config(bg=COLORS["accent_primary"], fg=COLORS["bg_primary"])
    
    def _update_frequency_display(self):
        """Update the frequency display based on channel"""
        channel = self.channel_var.get()
        freq = FREQ_BASE + channel * FREQ_STEP
        self.frequency_var.set(f"{freq:.3f} MHz")
        self.info_labels["frequency"].config(text=f"{freq:.3f} MHz")
    
    def _toggle_connection(self):
        """Connect or disconnect from the module"""
        if not self.connected:
            port = self.port_var.get()
            baud = self.baudrate_var.get()
            
            if not port:
                messagebox.showerror("Error", "Please select a serial port")
                return
            
            try:
                self.module = E220Module(port=port, baudrate=baud)
                if self.module.connect():
                    self.connected = True
                    self.status_var.set(f"● Connected ({port})")
                    self.status_indicator.config(fg=COLORS["success"])
                    self.connect_btn.config(text="▶ Disconnect", bg=COLORS["error"])
                    self._read_config()
                else:
                    messagebox.showerror("Error", "Failed to connect to module")
            except Exception as e:
                messagebox.showerror("Error", f"Connection failed: {e}")
        else:
            if self.module:
                self.module.disconnect()
            self.connected = False
            self.status_var.set("● Disconnected")
            self.status_indicator.config(fg=COLORS["text_tertiary"])
            self.connect_btn.config(text="▶ Connect", bg=COLORS["accent_primary"])
    
    def _refresh_ports(self):
        """Refresh list of available serial ports"""
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports:
            self.port_var.set(ports[0])
    
    def _read_config(self):
        """Read current module configuration"""
        if not self.module or not self.connected:
            messagebox.showwarning("Warning", "Module not connected")
            return
        
        try:
            params = self.module.get_parameters()
            if params:
                # Update UI with parameter values
                self.address_var.set(str(params.get("address", 0)))
                self.channel_var.set(params.get("chan", 0))
                self.uart_baud_var.set(params.get("uart_baud", 3))
                self.parity_var.set(params.get("parity", 0))
                self.air_rate_var.set(params.get("air_data_rate", 0))
                self.power_var.set(params.get("transmission_power", 0))
                
                self._update_frequency_display()
                self._refresh_registers()
                messagebox.showinfo("Success", "Configuration read successfully")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read configuration: {e}")
    
    def _save_config(self):
        """Save configuration to file"""
        if not self.module or not self.connected:
            messagebox.showwarning("Warning", "Module not connected")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                params = self.module.get_parameters()
                import json
                with open(file_path, 'w') as f:
                    json.dump(params, f, indent=2)
                messagebox.showinfo("Success", f"Configuration saved to {file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save configuration: {e}")
    
    def _write_to_module(self):
        """Write current GUI values to the hardware module"""
        if not self.module or not self.connected:
            messagebox.showwarning("Warning", "Module not connected")
            return
        
        if messagebox.askyesno("Confirm", "Write these settings to the module?"):
            try:
                # Collect all values from GUI
                params = {
                    "address": int(self.address_var.get()),
                    "chan": int(self.channel_var.get()),
                    "uart_baud": int(self.uart_baud_var.get()),
                    "parity": int(self.parity_var.get()),
                    "air_data_rate": int(self.air_rate_var.get()),
                    "transmission_power": int(self.power_var.get()),
                }
                
                # Send to module
                if self.module.set_parameters(params):
                    self._refresh_registers()
                    messagebox.showinfo("Success", "Configuration written to module successfully")
                else:
                    messagebox.showerror("Error", "Failed to write configuration to module")
            except ValueError as e:
                messagebox.showerror("Error", f"Invalid value entered: {e}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to write to module: {e}")
    
    def _load_config(self):
        """Load configuration from file"""
        if not self.module or not self.connected:
            messagebox.showwarning("Warning", "Module not connected")
            return
        
        file_path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                import json
                with open(file_path, 'r') as f:
                    params = json.load(f)
                
                # Apply parameters
                if self.module.set_parameters(params):
                    self._read_config()
                    messagebox.showinfo("Success", "Configuration applied successfully")
                else:
                    messagebox.showerror("Error", "Failed to apply configuration")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load configuration: {e}")
    
    def _reset_module(self):
        """Reset the module"""
        if not self.module or not self.connected:
            messagebox.showwarning("Warning", "Module not connected")
            return
        
        if messagebox.askyesno("Confirm", "Reset the module? This will restart the device."):
            try:
                if self.module.reset_module():
                    messagebox.showinfo("Success", "Module reset successfully")
                    self._read_config()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to reset module: {e}")
    
    def _refresh_registers(self):
        """Refresh and display register values"""
        if not self.module or not self.connected:
            self.register_text.config(text="No data")
            return
        
        try:
            regs = self.module._read_registers()
            if regs:
                hex_str = " ".join(f"{b:02X}" for b in regs)
                self.register_text.config(text=hex_str)
        except:
            self.register_text.config(text="Error reading registers")
    
    # Display label helper methods
    def _update_baud_display(self, *args):
        """Update baud rate display label"""
        try:
            idx = int(self.uart_baud_var.get())
            if 0 <= idx < len(UART_BAUD_RATES):
                self.info_labels["baud rate"].config(text=f"{UART_BAUD_RATES[idx]} bps")
        except:
            pass
    
    def _update_parity_display(self, *args):
        """Update parity display label"""
        try:
            idx = int(self.parity_var.get())
            if 0 <= idx < len(PARITY_LABELS):
                # Parity is not in info_labels, skip
                pass
        except:
            pass
    
    def _update_air_rate_display(self, *args):
        """Update air rate display label"""
        try:
            idx = int(self.air_rate_var.get())
            if 0 <= idx < len(AIR_RATE_LABELS):
                self.info_labels["air rate"].config(text=AIR_RATE_LABELS[idx])
        except:
            pass
    
    def _update_power_display(self, *args):
        """Update power display label"""
        try:
            idx = int(self.power_var.get())
            if 0 <= idx < len(TX_POWER_LABELS):
                self.info_labels["power"].config(text=TX_POWER_LABELS[idx])
        except:
            pass
    
    def _on_close(self):
        """Handle window close"""
        if self.connected and self.module:
            self.module.disconnect()
        self.root.destroy()


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point"""
    root = tk.Tk()
    app = E220ImpeccableGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
