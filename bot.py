import asyncio
import configparser
import json
import os
import threading
import queue
import sys
import multiprocessing
import winsound  # For sound notifications
from playwright.async_api import async_playwright
import customtkinter as ctk
from tkinter import messagebox

# Set up local Playwright browsers path (works for script and PyInstaller onefile)
def get_base_path():
    """Return base path for assets (handles PyInstaller onefile)."""
    if getattr(sys, '_MEIPASS', None):  # PyInstaller onefile temp dir
        return sys._MEIPASS
    if getattr(sys, 'frozen', False):   # PyInstaller one-folder
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

local_browsers_path = os.path.join(get_base_path(), "ms-playwright")
if os.path.exists(local_browsers_path):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = local_browsers_path

ACCOUNTS_FILE = os.path.join(get_base_path(), "accounts.json")

# ==============================================================================
# --- ⚙️ SETUP AND CONFIGURATION ---
# ==============================================================================

def get_playwright_browsers_path():
    """Determines the path where Playwright browsers are stored."""
    return os.path.join(get_base_path(), "ms-playwright")

class FirstTimeSetup(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("First-Time Setup"); self.geometry("400x250"); self.transient(master); self.grab_set(); self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.username = ""; self.password = ""
        ctk.CTkLabel(self, text="Welcome to Wardyati Bot!", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Please enter your login details.").pack()
        self.user_entry = ctk.CTkEntry(self, placeholder_text="Username (email)"); self.user_entry.pack(pady=10, padx=20, fill="x")
        self.pass_entry = ctk.CTkEntry(self, placeholder_text="Password", show="*"); self.pass_entry.pack(pady=5, padx=20, fill="x")
        self.save_button = ctk.CTkButton(self, text="Save and Continue", command=self.save_and_close); self.save_button.pack(pady=20)
        self.wait_window()
    def save_and_close(self):
        self.username = self.user_entry.get().strip(); self.password = self.pass_entry.get().strip()
        if not self.username or not self.password: return
        self.destroy()
    def cancel(self):
        self.username = None; self.password = None
        self.destroy()

def load_or_create_config(app_instance):
    config = configparser.ConfigParser()
    config_path = os.path.join(get_base_path(), 'config.ini')
    if not os.path.exists(config_path):
        setup_window = FirstTimeSetup(app_instance)
        username, password = setup_window.username, setup_window.password
        if username is None: return None
        config['Credentials'] = {'username': username, 'password': password}
        config['Settings'] = {'scan_interval_seconds': '0.2'}
        with open(config_path, 'w') as configfile: config.write(configfile)
    config.read(config_path)
    return config

# ==============================================================================
# --- 🤖 CORE BOT LOGIC (Playwright Automation) ---
# ==============================================================================
def get_shifts_url(room_number, shifts_to_book):
    """Generate the correct Wardyati URL based on shift dates"""
    import datetime
    import re

    current_month = datetime.datetime.now().month
    current_year = datetime.datetime.now().year

    # Check if any shifts are in a different month
    need_month_params = False
    target_year = current_year
    target_month = current_month

    for shift in shifts_to_book:
        date_str = shift["date"]
        # Try to extract date from Arabic date format (e.g., "2025-10-02 الخميس")
        date_match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
        if date_match:
            year = int(date_match.group(1))
            month = int(date_match.group(2))

            if month != current_month or year != current_year:
                need_month_params = True
                target_year = year
                target_month = month
                break

    base_url = f"https://wardyati.com/rooms/{room_number}/"

    if need_month_params:
        return f"{base_url}?view=monthly&year={target_year}&month={target_month}"
    else:
        return base_url

async def run_automation(config, shifts_to_book, room_number, cooldown, log_queue, stop_event=None, credentials=None, account_label=""):
    prefix = f"[{account_label}] " if account_label else ""
    def log(message): log_queue.put(f"{prefix}{message}")
    try:
        LOGIN_URL = "https://wardyati.com/login/"
        SHIFTS_URL = get_shifts_url(room_number, shifts_to_book)
        if credentials:
            YOUR_USERNAME = credentials.get('username', '')
            YOUR_PASSWORD = credentials.get('password', '')
        else:
            YOUR_USERNAME = config.get('Credentials', 'username')
            YOUR_PASSWORD = config.get('Credentials', 'password')
        if not YOUR_USERNAME or not YOUR_PASSWORD:
            log("ƒ?O FATAL ERROR: Missing account credentials.")
            return
        SCAN_INTERVAL_SECONDS = config.getfloat('Settings', 'scan_interval_seconds'); COOLDOWN_AFTER_BOOKING_SECONDS = cooldown + 0.5
        USERNAME_SELECTOR = "#id_username"
        PASSWORD_SELECTOR = "#id_password"
        LOGIN_BUTTON_TEXT = "تسجيل الدخول"
        TAKE_BUTTON_TEXT = "حجز"  # Updated label on new layout
        REMAINING_SPOTS_SELECTOR = "span.number-container"

        # This is now guaranteed to work because the .bat file checked for us.
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(get_playwright_browsers_path())

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, slow_mo=25)
            page = await browser.new_page()
            log("--- Step 1: Logging in ---")
            await page.goto(LOGIN_URL)
            await page.locator(USERNAME_SELECTOR).fill(YOUR_USERNAME)
            await page.locator(PASSWORD_SELECTOR).fill(YOUR_PASSWORD)
            log("🔐 Clicking login...")
            async with page.expect_navigation(url="**/rooms/**", timeout=15000):
                await page.get_by_role("button", name=LOGIN_BUTTON_TEXT).click()
            log("✅ Login successful!")
            log(f"--- Step 2: Navigating to shifts page ---")
            log(f"🔗 URL: {SHIFTS_URL}")
            await page.goto(SHIFTS_URL)
            await page.wait_for_load_state("domcontentloaded")
            log("\n--- Step 3: Starting LIVE SHIFT SCANNING ---")
            while shifts_to_book and (stop_event is None or not stop_event.is_set()):
                log(f"Scanning for {len(shifts_to_book)} target shifts...")
                booked_one_in_this_cycle = False
                for target_shift in shifts_to_book[:]:
                    try:
                        day_card = page.locator(f'div.arena-day-card:has(h5:has-text("{target_shift["date"]}"))')
                        shift_container = day_card.locator(f'div.arena_shift_instance:has(div.text-start:has-text("{target_shift["name"]}"))')
                        if await shift_container.count() == 0: continue
                        spots_container = shift_container.locator(REMAINING_SPOTS_SELECTOR)
                        if await spots_container.count() > 0:
                            if int(await spots_container.get_attribute("data-number")) == 0:
                                log(f"❌ FULL: {target_shift['date']} | {target_shift['name']}. Removing from targets."); shifts_to_book.remove(target_shift); continue
                        take_button = shift_container.locator("button.button_hold")
                        if await take_button.is_visible() and await take_button.is_enabled():
                            log(f"✅ AVAILABLE: {target_shift['date']} | {target_shift['name']}"); log("🎉 Clicking the 'Book' button NOW!")
                            await take_button.click(); shifts_to_book.remove(target_shift); booked_one_in_this_cycle = True
                            if not shifts_to_book: break
                            log(f"⏳ Shift booked! Waiting for {COOLDOWN_AFTER_BOOKING_SECONDS}s cooldown..."); await asyncio.sleep(COOLDOWN_AFTER_BOOKING_SECONDS)
                            break
                    except Exception: continue
                if not booked_one_in_this_cycle: await asyncio.sleep(SCAN_INTERVAL_SECONDS)

            # Check why the loop ended
            if stop_event and stop_event.is_set():
                log("\n🛑 Bot stopped by user.")
                log("🛑 Bot stopped")
            else:
                log("\n🎉 All target shifts processed!")
                log("--- BOT FINISHED ---")

            log("The browser will close in 10 seconds.")
            await asyncio.sleep(10)
            await browser.close()
    except Exception as e: log(f"❌ FATAL ERROR: {e}"); log("Bot stopped. Check credentials, room number, or internet.")

# ==============================================================================
# --- 🎨 MAIN GUI APPLICATION CLASS ---
# ==============================================================================
class BotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config = None
        self.target_shifts = []
        self.accounts = []
        self.log_queue = queue.Queue()
        self.bot_threads = []
        self.stop_event = threading.Event()
        self.bot_status = "idle"  # idle, running, stopping
        self.current_theme = "dark"  # Track current theme
        self.presets = self.load_presets()  # Load saved room presets
        self.accounts = self.load_accounts()  # Load saved accounts (multi-account)
        self.log_message_count = 0  # Track number of log messages
        self.active_runs = 0  # Track how many account runs are active
        self.title("Wardyati Shift Booker"); self.geometry("1100x1100"); ctk.set_appearance_mode("dark"); ctk.set_default_color_theme("green")

        # Scrollable root container so all sections remain reachable on smaller screens
        self.scroll_container = ctk.CTkScrollableFrame(self, corner_radius=0, label_text=None)
        self.scroll_container.pack(fill="both", expand=True)
        self.scroll_container.grid_columnconfigure(0, weight=1)

        # Header / status
        status_frame = ctk.CTkFrame(self.scroll_container, corner_radius=14)
        status_frame.grid(row=0, column=0, padx=14, pady=(14, 8), sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1); status_frame.grid_columnconfigure(3, weight=0)
        self.status_icon = ctk.CTkLabel(status_frame, text="⚪", font=ctk.CTkFont(size=22))
        self.status_icon.grid(row=0, column=0, padx=(12, 6), pady=10, sticky="w")
        self.status_text = ctk.CTkLabel(status_frame, text="Ready to start", font=ctk.CTkFont(size=16, weight="bold"))
        self.status_text.grid(row=0, column=1, sticky="w")
        self.presets_button = ctk.CTkButton(status_frame, text="📋 Presets", width=90, command=self.open_presets_window)
        self.presets_button.grid(row=0, column=2, padx=6, pady=10, sticky="e")
        self.theme_button = ctk.CTkButton(status_frame, text="🌙 Theme", width=90, command=self.toggle_theme)
        self.theme_button.grid(row=0, column=3, padx=(0, 12), pady=10, sticky="e")
        self.progress_bar = ctk.CTkProgressBar(status_frame, height=12, corner_radius=8)
        self.progress_bar.grid(row=1, column=0, columnspan=4, padx=12, pady=(0, 12), sticky="ew")
        self.progress_bar.set(0)
        self.progress_bar.grid_remove()

        # Quick stats row
        stats_frame = ctk.CTkFrame(self.scroll_container, corner_radius=14)
        stats_frame.grid(row=1, column=0, padx=14, pady=6, sticky="ew")
        for i in range(3): stats_frame.grid_columnconfigure(i, weight=1)
        def pill(label_text, value_text):
            frame = ctk.CTkFrame(stats_frame, corner_radius=10)
            lbl = ctk.CTkLabel(frame, text=label_text, text_color="gray80", font=ctk.CTkFont(size=12))
            val = ctk.CTkLabel(frame, text=value_text, font=ctk.CTkFont(size=16, weight="bold"))
            lbl.pack(anchor="w", padx=10, pady=(8, 0)); val.pack(anchor="w", padx=10, pady=(0, 8))
            return frame, val
        self.shifts_count_pill, self.shifts_count_label = pill("Target shifts", "0")
        self.cooldown_pill, self.cooldown_label = pill("Cooldown (s)", "—")
        self.room_pill, self.room_label = pill("Room", "—")
        self.shifts_count_pill.grid(row=0, column=0, padx=6, pady=6, sticky="ew")
        self.cooldown_pill.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        self.room_pill.grid(row=0, column=2, padx=6, pady=6, sticky="ew")

        # Accounts management
        accounts_frame = ctk.CTkFrame(self.scroll_container, corner_radius=14)
        accounts_frame.grid(row=2, column=0, padx=14, pady=6, sticky="ew")
        accounts_frame.grid_columnconfigure(1, weight=1); accounts_frame.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(accounts_frame, text="Accounts (run multiple in parallel)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=10, pady=8, sticky="w", columnspan=2)
        self.default_shared_var = ctk.BooleanVar(value=True)
        self.shared_hint = ctk.CTkCheckBox(accounts_frame, text="New accounts use main room & shift list (default)", variable=self.default_shared_var, onvalue=True, offvalue=False, fg_color="#22c55e", hover_color="#16a34a")
        self.shared_hint.grid(row=0, column=2, padx=10, pady=8, sticky="e")

        self.account_user_entry = ctk.CTkEntry(accounts_frame, placeholder_text="Username (email)")
        self.account_user_entry.grid(row=1, column=0, padx=10, pady=6, sticky="ew")
        self.account_pass_entry = ctk.CTkEntry(accounts_frame, placeholder_text="Password", show="*")
        self.account_pass_entry.grid(row=1, column=1, padx=10, pady=6, sticky="ew")
        add_account_btn = ctk.CTkButton(accounts_frame, text="Add Account", command=self.add_account)
        add_account_btn.grid(row=1, column=2, padx=10, pady=6, sticky="ew")

        self.accounts_scroll = ctk.CTkScrollableFrame(accounts_frame, height=140)
        self.accounts_scroll.grid(row=2, column=0, columnspan=3, padx=10, pady=(4, 10), sticky="nsew")
        self.refresh_accounts_display()

        # Session + add shift
        session_frame = ctk.CTkFrame(self.scroll_container, corner_radius=14)
        session_frame.grid(row=3, column=0, padx=14, pady=6, sticky="ew")
        session_frame.grid_columnconfigure(1, weight=1); session_frame.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(session_frame, text="Room Number", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.room_entry = ctk.CTkEntry(session_frame, placeholder_text="e.g., 2761"); self.room_entry.grid(row=0, column=1, padx=10, pady=8, sticky="ew")
        self.room_entry.bind("<KeyRelease>", lambda e: self.refresh_stats())
        ctk.CTkLabel(session_frame, text="Cooldown (sec)", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, padx=10, pady=8, sticky="w")
        self.cooldown_entry = ctk.CTkEntry(session_frame, placeholder_text="e.g., 15"); self.cooldown_entry.grid(row=0, column=3, padx=10, pady=8, sticky="ew")
        self.cooldown_entry.bind("<KeyRelease>", lambda e: self.refresh_stats())
        ctk.CTkLabel(session_frame, text="Date", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, padx=10, pady=8, sticky="w")
        self.date_entry = ctk.CTkEntry(session_frame, placeholder_text="Copy exact date from Wardyati (e.g., 2025-12-01)")
        self.date_entry.grid(row=1, column=1, padx=10, pady=8, sticky="ew")
        self.date_entry.bind("<KeyRelease>", self.validate_inputs); self.date_entry.bind("<Return>", lambda e: self.name_entry.focus())
        ctk.CTkLabel(session_frame, text="Shift Name", font=ctk.CTkFont(weight="bold")).grid(row=1, column=2, padx=10, pady=8, sticky="w")
        self.name_entry = ctk.CTkEntry(session_frame, placeholder_text='e.g., "Morning Post"')
        self.name_entry.grid(row=1, column=3, padx=10, pady=8, sticky="ew")
        self.name_entry.bind("<KeyRelease>", self.validate_inputs); self.name_entry.bind("<Return>", lambda e: self.add_shift() if self.add_button.cget("state") == "normal" else None)
        self.validation_label = ctk.CTkLabel(session_frame, text="", font=ctk.CTkFont(size=12))
        self.validation_label.grid(row=2, column=0, columnspan=4, padx=10, pady=(0, 4), sticky="w")
        actions_frame = ctk.CTkFrame(session_frame, fg_color="transparent"); actions_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=(2, 8), sticky="ew")
        actions_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.add_button = ctk.CTkButton(actions_frame, text="Add Shift ➕", command=self.add_shift)
        self.add_button.grid(row=0, column=0, padx=6, pady=4, sticky="ew")
        self.start_button = ctk.CTkButton(actions_frame, text="Start Bot", command=self.start_bot_thread, height=38, font=ctk.CTkFont(size=15, weight="bold"))
        self.start_button.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        self.stop_button = ctk.CTkButton(actions_frame, text="🛑 Stop Bot", command=self.stop_bot, height=38, font=ctk.CTkFont(size=15, weight="bold"), fg_color="red", hover_color="darkred", state="disabled")
        self.stop_button.grid(row=0, column=2, padx=6, pady=4, sticky="ew")

        # Shifts list
        display_frame = ctk.CTkFrame(self.scroll_container, corner_radius=14)
        display_frame.grid(row=4, column=0, padx=14, pady=6, sticky="nsew")
        display_frame.grid_columnconfigure(0, weight=1); display_frame.grid_rowconfigure(1, weight=1)
        header_frame = ctk.CTkFrame(display_frame, fg_color="transparent"); header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        ctk.CTkLabel(header_frame, text="🎯 Target Shifts", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        self.clear_all_button = ctk.CTkButton(header_frame, text="Clear All", width=100, height=30, command=self.clear_all_shifts); self.clear_all_button.pack(side="right")
        self.shifts_scroll_frame = ctk.CTkScrollableFrame(display_frame, height=140)
        self.shifts_scroll_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        # Log panel
        log_frame = ctk.CTkFrame(self.scroll_container, corner_radius=14)
        log_frame.grid(row=5, column=0, padx=14, pady=10, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1); log_frame.grid_rowconfigure(1, weight=1)
        log_header_frame = ctk.CTkFrame(log_frame, fg_color="transparent"); log_header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        log_title_frame = ctk.CTkFrame(log_header_frame, fg_color="transparent"); log_title_frame.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(log_title_frame, text="📡 Live Log", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        self.log_stats_label = ctk.CTkLabel(log_title_frame, text="Messages: 0", font=ctk.CTkFont(size=12), text_color="gray80")
        self.log_stats_label.pack(side="left", padx=(12, 0))
        log_controls_frame = ctk.CTkFrame(log_header_frame, fg_color="transparent"); log_controls_frame.pack(side="right")
        self.clear_log_button = ctk.CTkButton(log_controls_frame, text="Clear Log", width=90, height=28, command=self.clear_log)
        self.clear_log_button.pack(side="left", padx=6)
        ctk.CTkLabel(log_controls_frame, text="Shortcuts: F5=Start | Esc=Stop | Ctrl+Enter=Add", font=ctk.CTkFont(size=10), text_color="gray70").pack(side="left")
        self.log_textbox = ctk.CTkTextbox(log_frame, state="disabled", font=ctk.CTkFont(size=13), height=500)
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.update_log_from_queue(); self.after(100, self.initial_setup)
        # Initialize validation
        self.validate_inputs()

        # Global keyboard shortcuts
        self.bind("<F5>", self.shortcut_start_bot)
        self.bind("<Control-Return>", self.shortcut_add_shift)
        self.bind("<Escape>", self.shortcut_stop_bot)
        self.focus_set()  # Enable keyboard shortcuts
    def initial_setup(self):
        self.update_status("initializing", "Initializing...")
        self.start_button.configure(state="disabled", text="Initializing...")
        threading.Thread(target=self.run_setup_tasks, daemon=True).start()
    def run_setup_tasks(self):
        self.config = load_or_create_config(self)
        if self.config is None: self.after(100, self.destroy); return
        if not self.accounts and self.config is not None and self.config.has_section('Credentials'):
            username = self.config.get('Credentials', 'username', fallback="").strip()
            password = self.config.get('Credentials', 'password', fallback="").strip()
            if username and password:
                self.accounts.append({"username": username, "password": password, "use_shared": True, "room": "", "cooldown": "", "shifts": []})
                self.save_accounts()
                self.after(0, self.refresh_accounts_display)
        self.log_queue.put("Setup complete. Ready to book shifts.")
        self.start_button.configure(state="normal", text="Start Bot")
        self.update_status("idle", "Ready to start")
        self.after(0, self.refresh_stats)
    def add_shift(self):
        date = self.date_entry.get().strip(); name = self.name_entry.get().strip()
        if date and name:
            self.target_shifts.append({"date": date, "name": name})
            self.update_shifts_display()
            self.refresh_stats()
            self.date_entry.delete(0, 'end'); self.name_entry.delete(0, 'end'); self.date_entry.focus()
            self.validate_inputs()  # Reset validation after clearing fields
            self.log_queue.put(f"✅ Added shift: {date} | {name}")
        else: self.log_queue.put("⚠️ Please enter both a date and a shift name.")

    def validate_inputs(self, event=None):
        date_text = self.date_entry.get().strip()
        name_text = self.name_entry.get().strip()
        self.refresh_stats()

        # Reset validation
        self.validation_label.configure(text="", text_color="white")

        if not date_text and not name_text:
            self.validation_label.configure(text="💡 Tip: Copy date and shift name exactly from Wardyati website", text_color="gray")
            self.add_button.configure(state="disabled")
            return

        if not date_text:
            self.validation_label.configure(text="⚠️ Please enter a date", text_color="orange")
            self.add_button.configure(state="disabled")
            return

        if not name_text:
            self.validation_label.configure(text="⚠️ Please enter a shift name", text_color="orange")
            self.add_button.configure(state="disabled")
            return

        # Check for common patterns
        if len(date_text) < 10:
            self.validation_label.configure(text="⚠️ Date seems too short. Copy full date from Wardyati", text_color="orange")
            self.add_button.configure(state="disabled")
            self.refresh_stats(); return

        # All validations passed
        self.validation_label.configure(text="✅ Ready to add shift", text_color="green")
        self.add_button.configure(state="normal")
        self.refresh_stats()

    def remove_shift(self, index):
        if 0 <= index < len(self.target_shifts):
            removed_shift = self.target_shifts.pop(index)
            self.update_shifts_display()
            self.refresh_stats()
            self.log_queue.put(f"🗑️ Removed shift: {removed_shift['date']} | {removed_shift['name']}")

    def move_shift_up(self, index):
        """Move shift up in the list (higher priority)"""
        if 0 < index < len(self.target_shifts):
            # Swap with the previous item
            self.target_shifts[index], self.target_shifts[index-1] = self.target_shifts[index-1], self.target_shifts[index]
            self.update_shifts_display()
            shift = self.target_shifts[index-1]
            self.log_queue.put(f"↑ Moved up: {shift['date']} | {shift['name']}")
            self.refresh_stats()

    def move_shift_down(self, index):
        """Move shift down in the list (lower priority)"""
        if 0 <= index < len(self.target_shifts) - 1:
            # Swap with the next item
            self.target_shifts[index], self.target_shifts[index+1] = self.target_shifts[index+1], self.target_shifts[index]
            self.update_shifts_display()
            shift = self.target_shifts[index+1]
            self.log_queue.put(f"↓ Moved down: {shift['date']} | {shift['name']}")
            self.refresh_stats()

    def clear_all_shifts(self):
        if self.target_shifts:
            from tkinter import messagebox
            if messagebox.askyesno("Clear All Shifts", f"Are you sure you want to remove all {len(self.target_shifts)} shifts?"):
                self.target_shifts.clear()
                self.update_shifts_display()
                self.refresh_stats()
                self.log_queue.put("🗑️ All shifts cleared.")
        else:
            self.log_queue.put("ℹ️ No shifts to clear.")

    def update_shifts_display(self):
        # Clear existing shift widgets
        for widget in self.shifts_scroll_frame.winfo_children():
            widget.destroy()

        # Add each shift as an interactive row
        for i, shift in enumerate(self.target_shifts):
            shift_frame = ctk.CTkFrame(self.shifts_scroll_frame)
            shift_frame.pack(fill="x", padx=5, pady=2)

            # Shift info label
            info_text = f"{i+1}. {shift['date']} | {shift['name']}"
            shift_label = ctk.CTkLabel(shift_frame, text=info_text, anchor="w")
            shift_label.pack(side="left", fill="x", expand=True, padx=10, pady=5)

            # Buttons frame (for reorder and remove)
            buttons_frame = ctk.CTkFrame(shift_frame)
            buttons_frame.pack(side="right", padx=5, pady=2)

            # Up button (only if not first)
            if i > 0:
                up_btn = ctk.CTkButton(
                    buttons_frame,
                    text="↑",
                    width=25,
                    height=25,
                    command=lambda idx=i: self.move_shift_up(idx)
                )
                up_btn.pack(side="left", padx=1)

            # Down button (only if not last)
            if i < len(self.target_shifts) - 1:
                down_btn = ctk.CTkButton(
                    buttons_frame,
                    text="↓",
                    width=25,
                    height=25,
                    command=lambda idx=i: self.move_shift_down(idx)
                )
                down_btn.pack(side="left", padx=1)

            # Remove button
            remove_btn = ctk.CTkButton(
                buttons_frame,
                text="❌",
                width=25,
                height=25,
                command=lambda idx=i: self.remove_shift(idx)
            )
            remove_btn.pack(side="left", padx=1)

        # Update clear button state
        self.clear_all_button.configure(state="normal" if self.target_shifts else "disabled")
        self.refresh_stats()

    def refresh_stats(self):
        """Update the quick stat pills (counts/room/cooldown)."""
        self.shifts_count_label.configure(text=str(len(self.target_shifts)))
        room_val = self.room_entry.get().strip() or "—"
        self.room_label.configure(text=room_val)
        cooldown_val = self.cooldown_entry.get().strip() or "—"
        self.cooldown_label.configure(text=cooldown_val)

    def update_status(self, status, text):
        """Update the visual status indicator"""
        self.bot_status = status
        status_icons = {
            "idle": "⚪",
            "initializing": "🔄",
            "running": "🟢",
            "stopping": "🟡",
            "error": "🔴"
        }
        self.status_icon.configure(text=status_icons.get(status, "⚪"))
        self.status_text.configure(text=text)

        # Control progress bar visibility and animation
        if status == "running":
            self.progress_bar.grid()
            self.animate_progress_bar()
        elif status in ["idle", "error", "stopping"]:
            self.progress_bar.grid_remove()  # Hide progress bar
        elif status == "initializing":
            self.progress_bar.grid()
            self.progress_bar.set(0.5)  # Static 50% for initialization

    def animate_progress_bar(self):
        """Animate progress bar with scanning pattern"""
        if self.bot_status != "running":
            return

        # Get current progress
        current = self.progress_bar.get()

        # Create scanning pattern (0 → 1 → 0)
        if not hasattr(self, '_progress_direction'):
            self._progress_direction = 1

        # Update progress
        next_progress = current + (0.02 * self._progress_direction)

        # Reverse direction at endpoints
        if next_progress >= 1.0:
            next_progress = 1.0
            self._progress_direction = -1
        elif next_progress <= 0.0:
            next_progress = 0.0
            self._progress_direction = 1

        self.progress_bar.set(next_progress)

        # Continue animation if still running
        if self.bot_status == "running":
            self.after(50, self.animate_progress_bar)  # Update every 50ms

    def play_notification_sound(self, sound_type="success"):
        """Play notification sound for important events"""
        try:
            if sound_type == "success":
                # Success sound: High-pitched beep sequence
                winsound.Beep(800, 200)  # 800Hz for 200ms
                winsound.Beep(1000, 200)  # 1000Hz for 200ms
                winsound.Beep(1200, 400)  # 1200Hz for 400ms
            elif sound_type == "error":
                # Error sound: Low-pitched beep
                winsound.Beep(300, 500)  # 300Hz for 500ms
            elif sound_type == "complete":
                # Completion sound: Musical sequence
                winsound.Beep(600, 150)
                winsound.Beep(800, 150)
                winsound.Beep(1000, 150)
                winsound.Beep(1200, 300)
        except Exception:
            # If sound fails, silently ignore
            pass

    def toggle_theme(self):
        """Toggle between light and dark theme"""
        if self.current_theme == "dark":
            ctk.set_appearance_mode("light")
            self.current_theme = "light"
            self.theme_button.configure(text="☀️")  # Sun icon for light mode
        else:
            ctk.set_appearance_mode("dark")
            self.current_theme = "dark"
            self.theme_button.configure(text="🌙")  # Moon icon for dark mode

    def clear_log(self):
        """Clear the log textbox and reset message count"""
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")
        self.log_message_count = 0
        self.update_log_stats()
        self.add_log_message("🗑️ Log cleared.")

    def update_log_stats(self):
        """Update the log statistics display"""
        self.log_stats_label.configure(text=f"Messages: {self.log_message_count}")

    def add_log_message(self, message):
        """Add a formatted message to the log with timestamp and styling"""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

        # Format message with timestamp and better spacing
        formatted_message = f"[{timestamp}] {message}"

        self.log_textbox.configure(state="normal")

        # Add message with appropriate formatting
        if "✅" in message or "🎉" in message or "BOOKED:" in message:
            # Success messages in green
            self.log_textbox.insert("end", formatted_message + "\n", "success")
        elif "❌" in message or "ERROR" in message or "FATAL" in message:
            # Error messages in red
            self.log_textbox.insert("end", formatted_message + "\n", "error")
        elif "⚠️" in message or "WARNING" in message:
            # Warning messages in orange
            self.log_textbox.insert("end", formatted_message + "\n", "warning")
        elif "💡" in message or "TIP:" in message:
            # Tips in blue
            self.log_textbox.insert("end", formatted_message + "\n", "tip")
        else:
            # Regular messages
            self.log_textbox.insert("end", formatted_message + "\n")

        # Configure text tags for colors (if not already done)
        try:
            self.log_textbox.tag_config("success", foreground="#4ade80")  # Green
            self.log_textbox.tag_config("error", foreground="#f87171")    # Red
            self.log_textbox.tag_config("warning", foreground="#fb923c")  # Orange
            self.log_textbox.tag_config("tip", foreground="#60a5fa")      # Blue
        except:
            pass

        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

        self.log_message_count += 1
        self.update_log_stats()

    def account_display_name(self, account, index=None):
        """Return a short label for an account without exposing full email."""
        username = account.get("username", "") or "Account"
        base = username.split("@")[0] if "@" in username else username
        if len(base) > 3:
            base = f"{base[:3]}***"
        label = base or "Account"
        if index is not None:
            return f"{index+1}:{label}"
        return label

    def load_accounts(self):
        """Load saved accounts; fall back to single-account config if present."""
        try:
            if os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
        except Exception:
            # Continue to fallback
            pass

        # Fallback to existing config.ini credentials (backwards compatibility)
        try:
            fallback_config = configparser.ConfigParser()
            config_path = os.path.join(get_base_path(), 'config.ini')
            if os.path.exists(config_path):
                fallback_config.read(config_path)
                if fallback_config.has_section('Credentials'):
                    username = fallback_config.get('Credentials', 'username', fallback="").strip()
                    password = fallback_config.get('Credentials', 'password', fallback="").strip()
                    if username and password:
                        return [{
                            "username": username,
                            "password": password,
                            "use_shared": True,
                            "room": "",
                            "cooldown": "",
                            "shifts": []
                        }]
        except Exception:
            pass

        return []

    def save_accounts(self):
        """Persist accounts to disk (runtime only)."""
        try:
            with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.accounts, f, indent=2, ensure_ascii=False)
        except Exception:
            self.log_queue.put("Гs Л,? WARNING: Unable to save accounts file.")

    def refresh_accounts_display(self):
        """Render account rows with shared/custom controls."""
        for widget in self.accounts_scroll.winfo_children():
            widget.destroy()

        if not self.accounts:
            ctk.CTkLabel(self.accounts_scroll, text="Add at least one account to run the bot.", text_color="gray").pack(pady=6)
            return

        for idx, account in enumerate(self.accounts):
            row = ctk.CTkFrame(self.accounts_scroll)
            row.pack(fill="x", padx=4, pady=3)

            title = ctk.CTkLabel(row, text=f"{idx+1}. {account.get('username', '')}", font=ctk.CTkFont(weight="bold"))
            title.pack(side="left", padx=6, pady=6)

            summary_text = "Using main room & shift list" if account.get("use_shared", True) else f"Custom: room {account.get('room', 'Г?\"')} | shifts {len(account.get('shifts', []))}"
            ctk.CTkLabel(row, text=summary_text, text_color="gray80").pack(side="left", padx=6)

            shared_var = ctk.BooleanVar(value=account.get("use_shared", True))
            toggle = ctk.CTkCheckBox(
                row,
                text="Use main list",
                variable=shared_var,
                onvalue=True,
                offvalue=False,
                command=lambda i=idx, var=shared_var: self.toggle_use_shared(i, var.get())
            )
            toggle.pack(side="left", padx=4)

            cfg_btn = ctk.CTkButton(
                row,
                text="Account-specific setup",
                width=110,
                command=lambda i=idx: self.open_account_config(i),
                state="normal" if not account.get("use_shared", True) else "disabled"
            )
            cfg_btn.pack(side="right", padx=4)

            remove_btn = ctk.CTkButton(
                row,
                text="Remove",
                width=70,
                fg_color="red",
                hover_color="darkred",
                command=lambda i=idx: self.remove_account(i)
            )
            remove_btn.pack(side="right", padx=4)

    def add_account(self):
        """Add a new account to the list."""
        username = self.account_user_entry.get().strip()
        password = self.account_pass_entry.get().strip()

        if not username or not password:
            self.log_queue.put("Гs Л,? Please enter both username and password for the account.")
            return

        new_account = {
            "username": username,
            "password": password,
            "use_shared": bool(self.default_shared_var.get()),
            "room": "",
            "cooldown": "",
            "shifts": []
        }
        self.accounts.append(new_account)
        self.save_accounts()
        self.refresh_accounts_display()
        self.account_user_entry.delete(0, 'end')
        self.account_pass_entry.delete(0, 'end')
        self.log_queue.put(f"Гo. Added account: {self.account_display_name(new_account)}")

    def remove_account(self, index):
        """Remove an account from the list."""
        if 0 <= index < len(self.accounts):
            removed = self.accounts.pop(index)
            self.save_accounts()
            self.refresh_accounts_display()
            self.log_queue.put(f"dY-`Л,? Removed account: {self.account_display_name(removed, index=index)}")

    def toggle_use_shared(self, index, use_shared):
        """Toggle whether an account uses the shared config or its own."""
        if 0 <= index < len(self.accounts):
            self.accounts[index]["use_shared"] = bool(use_shared)
            self.save_accounts()
            self.refresh_accounts_display()

    def open_account_config(self, index):
        """Open a small dialog to set custom room/cooldown/shifts for an account."""
        if not (0 <= index < len(self.accounts)):
            return
        account = self.accounts[index]
        config_window = ctk.CTkToplevel(self)
        config_window.title(f"Custom Config: {self.account_display_name(account, index)}")
        config_window.geometry("520x520")
        config_window.transient(self)
        config_window.grab_set()

        # Prefill local copy
        shifts_local = account.get("shifts", []).copy()

        form_frame = ctk.CTkFrame(config_window)
        form_frame.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(form_frame, text="Room Number", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        room_entry = ctk.CTkEntry(form_frame, placeholder_text="e.g., 2761")
        room_entry.insert(0, account.get("room", ""))
        room_entry.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        ctk.CTkLabel(form_frame, text="Cooldown (sec)", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, padx=6, pady=6, sticky="w")
        cooldown_entry = ctk.CTkEntry(form_frame, placeholder_text="e.g., 15")
        cooldown_entry.insert(0, str(account.get("cooldown", "")))
        cooldown_entry.grid(row=1, column=1, padx=6, pady=6, sticky="ew")
        form_frame.grid_columnconfigure(1, weight=1)

        # Shift entry
        shift_frame = ctk.CTkFrame(config_window)
        shift_frame.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(shift_frame, text="Date", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=6, pady=4, sticky="w")
        shift_date_entry = ctk.CTkEntry(shift_frame, placeholder_text="2025-12-01")
        shift_date_entry.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        ctk.CTkLabel(shift_frame, text="Shift Name", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, padx=6, pady=4, sticky="w")
        shift_name_entry = ctk.CTkEntry(shift_frame, placeholder_text="Morning Post")
        shift_name_entry.grid(row=0, column=3, padx=6, pady=4, sticky="ew")
        shift_frame.grid_columnconfigure(1, weight=1); shift_frame.grid_columnconfigure(3, weight=1)

        shifts_scroll = ctk.CTkScrollableFrame(config_window, height=220)
        shifts_scroll.pack(fill="both", expand=True, padx=12, pady=(4, 10))

        def refresh_shifts_local():
            for widget in shifts_scroll.winfo_children():
                widget.destroy()
            if not shifts_local:
                ctk.CTkLabel(shifts_scroll, text="No shifts yet.", text_color="gray").pack(pady=6)
                return
            for i, shift in enumerate(shifts_local):
                row_local = ctk.CTkFrame(shifts_scroll)
                row_local.pack(fill="x", padx=4, pady=2)
                ctk.CTkLabel(row_local, text=f"{i+1}. {shift['date']} | {shift['name']}").pack(side="left", padx=6)
                ctk.CTkButton(row_local, text="Remove", width=70, fg_color="red", hover_color="darkred",
                              command=lambda idx=i: (shifts_local.pop(idx), refresh_shifts_local())).pack(side="right", padx=4)

        def add_local_shift():
            date_text = shift_date_entry.get().strip()
            name_text = shift_name_entry.get().strip()
            if date_text and name_text:
                shifts_local.append({"date": date_text, "name": name_text})
                shift_date_entry.delete(0, 'end')
                shift_name_entry.delete(0, 'end')
                refresh_shifts_local()
            else:
                messagebox.showerror("Missing data", "Please enter both date and shift name.")

        add_shift_btn = ctk.CTkButton(shift_frame, text="Add", command=add_local_shift)
        add_shift_btn.grid(row=0, column=4, padx=6, pady=4, sticky="ew")

        button_bar = ctk.CTkFrame(config_window)
        button_bar.pack(fill="x", padx=12, pady=10)

        def save_custom_config():
            room_val = room_entry.get().strip()
            cooldown_val = cooldown_entry.get().strip()
            if not room_val or not cooldown_val:
                messagebox.showerror("Missing data", "Room and cooldown are required for a custom config.")
                return
            if not room_val.isdigit():
                messagebox.showerror("Invalid room", "Room must be numeric.")
                return
            if not cooldown_val.isdigit():
                messagebox.showerror("Invalid cooldown", "Cooldown must be a number.")
                return
            if not shifts_local:
                messagebox.showerror("No shifts", "Add at least one shift for this account.")
                return
            account["room"] = room_val
            account["cooldown"] = int(cooldown_val)
            account["shifts"] = shifts_local.copy()
            account["use_shared"] = False
            self.save_accounts()
            self.refresh_accounts_display()
            self.log_queue.put(f"Saved custom config for {self.account_display_name(account, index)}")
            config_window.destroy()

        ctk.CTkButton(button_bar, text="Save Custom Config", command=save_custom_config).pack(side="left", padx=6)
        ctk.CTkButton(button_bar, text="Cancel", fg_color="gray", hover_color="darkgray", command=config_window.destroy).pack(side="right", padx=6)

        refresh_shifts_local()

    def load_presets(self):
        """Load room presets from file"""
        try:
            presets_file = "room_presets.json"
            if os.path.exists(presets_file):
                import json
                with open(presets_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}

    def save_presets(self):
        """Save room presets to file"""
        try:
            import json
            with open("room_presets.json", 'w', encoding='utf-8') as f:
                json.dump(self.presets, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def open_presets_window(self):
        """Open presets management window"""
        presets_window = ctk.CTkToplevel(self)
        presets_window.title("Room Presets")
        presets_window.geometry("600x500")
        presets_window.transient(self)
        presets_window.grab_set()

        # Presets list frame
        list_frame = ctk.CTkFrame(presets_window)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(list_frame, text="📋 Saved Room Presets", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # Scrollable frame for presets
        presets_scroll = ctk.CTkScrollableFrame(list_frame, height=300)
        presets_scroll.pack(fill="both", expand=True, padx=10, pady=5)

        def refresh_presets_list():
            # Clear existing widgets
            for widget in presets_scroll.winfo_children():
                widget.destroy()

            if not self.presets:
                ctk.CTkLabel(presets_scroll, text="No presets saved yet", text_color="gray").pack(pady=20)
                return

            for preset_name, preset_data in self.presets.items():
                preset_frame = ctk.CTkFrame(presets_scroll)
                preset_frame.pack(fill="x", padx=5, pady=5)

                # Preset info
                info_frame = ctk.CTkFrame(preset_frame)
                info_frame.pack(fill="x", padx=10, pady=5)

                name_label = ctk.CTkLabel(info_frame, text=f"🏢 {preset_name}", font=ctk.CTkFont(weight="bold"))
                name_label.pack(anchor="w")

                room_label = ctk.CTkLabel(info_frame, text=f"Room: {preset_data['room_number']} | Cooldown: {preset_data['cooldown']}s")
                room_label.pack(anchor="w")

                shift_count = len(preset_data.get('shifts', []))
                shifts_text = f"Shifts: {shift_count} shift{'s' if shift_count != 1 else ''}" if shift_count > 0 else "Shifts: No shifts saved"
                shifts_label = ctk.CTkLabel(info_frame, text=shifts_text, text_color="gray")
                shifts_label.pack(anchor="w")

                # Buttons frame
                buttons_frame = ctk.CTkFrame(preset_frame)
                buttons_frame.pack(fill="x", padx=10, pady=5)

                load_btn = ctk.CTkButton(buttons_frame, text="Load", width=80,
                                       command=lambda name=preset_name: load_preset(name))
                load_btn.pack(side="left", padx=5)

                edit_btn = ctk.CTkButton(buttons_frame, text="Edit", width=80, fg_color="orange", hover_color="darkorange",
                                       command=lambda name=preset_name: edit_preset(name))
                edit_btn.pack(side="left", padx=5)

                delete_btn = ctk.CTkButton(buttons_frame, text="Delete", width=80, fg_color="red", hover_color="darkred",
                                         command=lambda name=preset_name: delete_preset(name))
                delete_btn.pack(side="right", padx=5)

        def load_preset(preset_name):
            preset_data = self.presets[preset_name]
            self.room_entry.delete(0, 'end')
            self.room_entry.insert(0, preset_data['room_number'])
            self.cooldown_entry.delete(0, 'end')
            self.cooldown_entry.insert(0, str(preset_data['cooldown']))
            self.target_shifts = preset_data.get('shifts', []).copy()
            self.update_shifts_display()
            self.refresh_stats()
            presets_window.destroy()
            self.log_queue.put(f"📋 Loaded preset: {preset_name}")

        def delete_preset(preset_name):
            if messagebox.askyesno("Delete Preset", f"Delete preset '{preset_name}'?"):
                del self.presets[preset_name]
                self.save_presets()
                refresh_presets_list()

        def edit_preset(preset_name):
            preset_data = self.presets[preset_name]

            # Create edit window
            edit_window = ctk.CTkToplevel(presets_window)
            edit_window.title(f"Edit Preset: {preset_name}")
            edit_window.geometry("500x300")
            edit_window.transient(presets_window)
            edit_window.grab_set()

            # Preset name
            name_frame = ctk.CTkFrame(edit_window)
            name_frame.pack(fill="x", padx=20, pady=10)
            ctk.CTkLabel(name_frame, text="Preset Name:", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            name_entry = ctk.CTkEntry(name_frame, placeholder_text="Enter preset name")
            name_entry.insert(0, preset_name)
            name_entry.pack(fill="x", pady=5)

            # Room number
            room_frame = ctk.CTkFrame(edit_window)
            room_frame.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(room_frame, text="Room Number:", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            room_entry = ctk.CTkEntry(room_frame, placeholder_text="Enter room number")
            room_entry.insert(0, preset_data['room_number'])
            room_entry.pack(fill="x", pady=5)

            # Cooldown
            cooldown_frame = ctk.CTkFrame(edit_window)
            cooldown_frame.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(cooldown_frame, text="Cooldown (seconds):", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
            cooldown_entry = ctk.CTkEntry(cooldown_frame, placeholder_text="Enter cooldown in seconds")
            cooldown_entry.insert(0, str(preset_data['cooldown']))
            cooldown_entry.pack(fill="x", pady=5)

            # Buttons
            button_frame = ctk.CTkFrame(edit_window)
            button_frame.pack(fill="x", padx=20, pady=20)

            def save_changes():
                new_name = name_entry.get().strip()
                new_room = room_entry.get().strip()
                new_cooldown = cooldown_entry.get().strip()

                if not new_name or not new_room or not new_cooldown:
                    messagebox.showerror("Error", "All fields are required")
                    return

                try:
                    cooldown_int = int(new_cooldown)
                except ValueError:
                    messagebox.showerror("Error", "Cooldown must be a valid number")
                    return

                # Remove old preset if name changed
                if new_name != preset_name:
                    del self.presets[preset_name]

                # Save updated preset
                self.presets[new_name] = {
                    'room_number': new_room,
                    'cooldown': cooldown_int,
                    'shifts': preset_data.get('shifts', [])  # Keep existing shifts
                }

                self.save_presets()
                refresh_presets_list()
                edit_window.destroy()
                self.log_queue.put(f"✏️ Updated preset: {new_name}")

            save_btn = ctk.CTkButton(button_frame, text="Save Changes", command=save_changes)
            save_btn.pack(side="left", padx=5)

            cancel_btn = ctk.CTkButton(button_frame, text="Cancel", fg_color="gray", hover_color="darkgray",
                                     command=edit_window.destroy)
            cancel_btn.pack(side="right", padx=5)

        def save_current_as_preset():
            name = preset_name_entry.get().strip()
            if not name:
                messagebox.showerror("Error", "Please enter a preset name")
                return

            room = self.room_entry.get().strip()
            cooldown = self.cooldown_entry.get().strip()

            if not room or not cooldown:
                messagebox.showerror("Error", "Please fill in room number and cooldown")
                return

            try:
                cooldown_int = int(cooldown)
            except ValueError:
                messagebox.showerror("Error", "Cooldown must be a valid number")
                return

            self.presets[name] = {
                'room_number': room,
                'cooldown': cooldown_int,
                'shifts': self.target_shifts.copy()  # Save current shifts (can be empty)
            }
            self.save_presets()
            refresh_presets_list()
            preset_name_entry.delete(0, 'end')
            self.log_queue.put(f"💾 Saved preset: {name}")

        # Save new preset section
        save_frame = ctk.CTkFrame(list_frame)
        save_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(save_frame, text="💾 Save Current Configuration", font=ctk.CTkFont(weight="bold")).pack(pady=5)

        entry_frame = ctk.CTkFrame(save_frame)
        entry_frame.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(entry_frame, text="Preset Name:").pack(side="left", padx=5)
        preset_name_entry = ctk.CTkEntry(entry_frame, placeholder_text="e.g., Morning Shifts - Room 2761")
        preset_name_entry.pack(side="left", fill="x", expand=True, padx=5)

        save_btn = ctk.CTkButton(entry_frame, text="Save", command=save_current_as_preset)
        save_btn.pack(side="right", padx=5)

        # Initialize presets list
        refresh_presets_list()

    def shortcut_start_bot(self, event=None):
        if self.start_button.cget("state") == "normal":
            self.start_bot_thread()

    def shortcut_add_shift(self, event=None):
        if self.add_button.cget("state") == "normal":
            self.add_shift()

    def shortcut_stop_bot(self, event=None):
        if self.stop_button.cget("state") == "normal":
            self.stop_bot()

    def stop_bot(self):
        running = any(t.is_alive() for t in self.bot_threads)
        if running:
            from tkinter import messagebox
            if messagebox.askyesno("Stop Bot", "Are you sure you want to stop the bot?"):
                self.update_status("stopping", "Stopping bot...")
                self.stop_event.set()
                self.log_queue.put("dY>` Stopping bot...")
                self.stop_button.configure(state="disabled")
        else:
            self.log_queue.put("No bot is currently running.")

    def start_bot_thread(self):
        if any(t.is_alive() for t in self.bot_threads):
            self.log_queue.put("Bot is already running.")
            return

        if not self.accounts:
            self.log_queue.put("ERROR: Add at least one account before starting.")
            return

        shared_room = self.room_entry.get().strip()
        shared_cooldown = self.cooldown_entry.get().strip()
        shared_shifts = self.target_shifts.copy()

        runs = []
        for idx, account in enumerate(self.accounts):
            label = self.account_display_name(account, idx)
            if account.get("use_shared", True):
                if not shared_room:
                    self.log_queue.put("ERROR: Room Number is required for accounts using the main list.")
                    return
                if not shared_room.isdigit():
                    self.log_queue.put("ERROR: Room Number must contain only numbers.")
                    return
                if not shared_cooldown:
                    self.log_queue.put("ERROR: Cooldown time is required for accounts using the main list.")
                    return
                if not shared_cooldown.isdigit():
                    self.log_queue.put("ERROR: Cooldown must be a number (seconds).")
                    return
                if not shared_shifts:
                    self.log_queue.put("ERROR: Add at least one shift to the main list (or switch the account to custom).")
                    return
                runs.append({"room": shared_room, "cooldown": int(shared_cooldown), "shifts": shared_shifts.copy(), "credentials": account, "label": label})
            else:
                room_val = str(account.get("room", "")).strip()
                cooldown_val = str(account.get("cooldown", "")).strip()
                shifts_val = account.get("shifts", [])
                if not room_val or not cooldown_val:
                    self.log_queue.put(f"ERROR: Account {label} is missing room or cooldown.")
                    return
                if not room_val.isdigit():
                    self.log_queue.put(f"ERROR: Room must be numeric for account {label}.")
                    return
                if not str(cooldown_val).isdigit():
                    self.log_queue.put(f"ERROR: Cooldown must be numeric for account {label}.")
                    return
                if not shifts_val:
                    self.log_queue.put(f"ERROR: Add shifts to account {label} or switch it to shared mode.")
                    return
                runs.append({"room": room_val, "cooldown": int(cooldown_val), "shifts": shifts_val.copy(), "credentials": account, "label": label})

        from tkinter import messagebox
        message_lines = [f"Accounts to start: {len(runs)}"]
        shared_mode_accounts = sum(1 for r in runs if r["room"] == shared_room and r["shifts"] == shared_shifts)
        message_lines.append(f"- Shared config: {shared_mode_accounts}")
        message_lines.append(f"- Custom config: {len(runs) - shared_mode_accounts}")
        message_lines.append(f"Shared room: {shared_room or 'n/a'} | cooldown: {shared_cooldown or 'n/a'}")
        if not messagebox.askyesno("Confirm Start Bot", "\n".join(message_lines)):
            return

        self.stop_event.clear()
        self.update_status("running", "Bot is scanning for shifts...")
        self.start_button.configure(state="disabled", text=f"Running {len(runs)} account(s)...")
        self.add_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.refresh_stats()
        self.active_runs = len(runs)
        self.bot_threads = []

        for run in runs:
            thread = threading.Thread(target=lambda r=run: asyncio.run(run_automation(self.config, r["shifts"], r["room"], r["cooldown"], self.log_queue, self.stop_event, credentials=r["credentials"], account_label=r["label"])), daemon=True)
            self.bot_threads.append(thread)
            thread.start()

    def check_run_completion(self):
        """Reset UI when all automation threads have finished."""
        self.bot_threads = [t for t in self.bot_threads if t.is_alive()]
        self.active_runs = len(self.bot_threads)
        if not self.bot_threads:
            if self.bot_status != "error":
                self.update_status("idle", "Ready to start")
            self.start_button.configure(state="normal", text="Start Bot")
            self.add_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def update_log_from_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                # Use the new formatted logging method
                self.add_log_message(message)

                # Play sound notifications for important events
                if "🎉 Shift booked successfully!" in message or "✅ BOOKED:" in message:
                    # Play success sound in background thread
                    threading.Thread(target=lambda: self.play_notification_sound("success"), daemon=True).start()
                elif "FATAL ERROR" in message or "Setup Failed" in message:
                    # Play error sound in background thread
                    threading.Thread(target=lambda: self.play_notification_sound("error"), daemon=True).start()
                elif "BOT FINISHED" in message and "🎉 All target shifts processed!" in message:
                    # Play completion sound in background thread
                    threading.Thread(target=lambda: self.play_notification_sound("complete"), daemon=True).start()

                if "BOT FINISHED" in message or "FATAL ERROR" in message or "Setup Failed" in message or "🛑 Bot stopped" in message:
                    if "FATAL ERROR" in message or "Setup Failed" in message:
                        self.update_status("error", "Error occurred")
                    self.check_run_completion()
        except queue.Empty: pass
        finally: self.after(100, self.update_log_from_queue)

# ==============================================================================
# --- 🚀 SCRIPT EXECUTION ---
# ==============================================================================
if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = BotApp()
    app.mainloop()
