# Wardyati Shift Booker

Friendly guide for running the bot, now with multi-account booking.
This README assumes you have downloaded the bot as a zip file, which includes `bot.py`, the `ms-playwright` browser files, and `RUN BOT HIDDEN.vbs`.

## Prerequisites
1.  **Python**: Ensure Python is installed on your system and added to your system's PATH. You can download it from [python.org](https://www.python.org/downloads/).
2.  **FIRST TIME SETUP.bat**: This script automates the installation of necessary Python libraries (`playwright`, `customtkinter`) and downloads the Chromium browser required by Playwright. You *must* run this script once before running the bot for the first time.

## Setup & Run
1.  **Unzip the downloaded file**: Extract the contents of the zip file to a folder of your choice.
2.  Run `RUN BOT HIDDEN.vbs` to launch the bot in the background without a console window.
3.  On first launch of `bot.py`, enter your Wardyati username (email) and password when prompted.
4.  Fill in:
    - **Room Number**: From your Wardyati room URL (e.g., `2761`).
    - **Cooldown (sec)**: Delay between booking attempts (15–30 recommended).
    - **Date**: Copy exact date from Wardyati (e.g., `2025-12-01`).
    - **Shift Name**: Copy exact shift title (e.g., `Morning`, `Mid`, `Night`).
5.  Click **Add Shift to Target List** for each shift.
6.  Click **Start Bot**. The bot will log in, scan, and book when available with live log updates.

## New: Multi-account booking
- **Accounts panel**: Add multiple username/password pairs (saved locally to `accounts.json`, auto-loaded next run).
- **Main list vs account-specific** (per account):
  - **Use main list**: the account borrows the main Room/Cooldown/Shift list you set at the top.
  - **Account-specific setup**: give that account its own room, cooldown, and shift list.
- **Parallel runs**: Start launches one browser per account; log lines are prefixed with the account label.
- **Stop**: Stop button halts all active accounts at once.

## Features
- Sound notifications when shifts are booked.
- Light/dark theme toggle (moon/sun button).
- Progress bar while scanning.
- Room presets (save/load favorite setups).
- Keyboard shortcuts: F5 = Start | Esc = Stop | Ctrl+Enter = Add shift.
- Shift reordering (↑/↓ buttons) to set priority.
- Enhanced logs with timestamps, colors, and message counter.

## Important notes
- Keep the app window open while running.
- Stable internet recommended.
- Browser auto-closes 10 seconds after finishing.
- Login details and accounts stay local (`config.ini`, `accounts.json`, `room_presets.json`); none are uploaded.

## Troubleshooting
- Login fails: recheck username/password.
- Room error: ensure numeric room number from URL.
- Shifts not found: date and shift name must match Wardyati exactly.
- Python errors: if running from source, ensure Python is on PATH (the setup script can handle this).


## Tips
- Copy dates and shift names directly from the website to avoid typos.
- Start a few minutes before shifts drop.
- Scan interval is 0.2s by default (in `config.ini`).
- Use presets to quickly reload common room/cooldown/shift sets.
- Order shifts by priority; the bot books in list order.

Good luck booking your shifts!
