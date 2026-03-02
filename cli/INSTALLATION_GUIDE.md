# V Scanner - Installation & Setup Guide

## Quick Start (Automated Setup)

The easiest way to set up V Scanner with all its dependencies is to run the automated setup script:

```bash
python setup.py
```

This will:
1. ✅ Install all Python dependencies from `requirements.txt`
2. ✅ Install scrcpy (for live screen mirroring)
3. ✅ Install/verify ADB (Android Debug Bridge)
4. ✅ Show instructions for any manual steps needed

## What Gets Installed

### Python Dependencies
These are automatically installed via pip:
- `adb-shell` - Android Debug Bridge interface
- `rich` - Beautiful terminal UI
- `click` - Command-line framework
- `jinja2` - Template engine
- `requests` - HTTP library
- `pyyaml` - YAML parser
- `colorama` - Color terminal output
- `tabulate` - Table formatting

### System Tools (Installed by setup.py)

#### scrcpy (Screen Mirroring & Control)
Enables live screen mirroring with mouse/keyboard control

**Windows:**
```bash
scoop install scrcpy
```
Or use Chocolatey: `choco install scrcpy`
Or download: https://github.com/Genymobile/scrcpy/releases

**macOS:**
```bash
brew install scrcpy
```

**Linux:**
```bash
sudo apt install scrcpy
```

#### ADB - Android Debug Bridge
Required for device communication

**Windows:**
- Download Android Studio/SDK Platform Tools from: https://developer.android.com/studio
- Or: `scoop install adb`

**macOS:**
```bash
brew install android-platform-tools
```

**Linux:**
```bash
sudo apt install android-tools-adb
```

## Manual Installation (If Automated Setup Doesn't Work)

### Step 1: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Install scrcpy

**Windows (Scoop):**
```powershell
# Install Scoop if not already installed
iwr -useb get.scoop.sh | iex

# Install scrcpy
scoop install scrcpy
```

**Windows (Chocolatey):**
```powershell
choco install scrcpy
```

**macOS:**
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install scrcpy
brew install scrcpy
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install scrcpy
```

### Step 3: Install ADB

**Windows:**
Download from Android Studio: https://developer.android.com/studio/releases/platform-tools

**macOS:**
```bash
brew install android-platform-tools
```

**Linux:**
```bash
sudo apt install android-tools-adb
```

## Verify Installation

After running setup, verify all dependencies are installed:

```bash
python main.py
```

The app will automatically check all dependencies on startup and inform you of any missing components.

## Device Setup (Android)

Before using V Scanner, prepare your Android device:

1. **Enable USB Debugging:**
   - Go to Settings → About Phone
   - Tap "Build Number" 7 times to enable Developer Mode
   - Go back to Settings → Developer Options
   - Enable "USB Debugging"

2. **Connect via USB:**
   - Connect device to computer with USB cable
   - Allow file transfer when prompted on device
   - Verify connection: `adb devices` (should show your device)

3. **Grant Permissions:**
   - First run may require permission grants on the device
   - Follow on-screen prompts

## Dependency Checker

V Scanner automatically checks all dependencies when it starts:

```
🔍 Checking Dependencies...

Component                       Status
──────────────────────────────────────
Python Packages                 ✓ All installed
scrcpy (Screen Mirroring)       ✓ Installed
ADB (Android Debug Bridge)      ✓ Available
```

If any component is missing, it will:
1. Show which component is missing
2. Attempt automatic installation
3. Provide manual installation instructions

## Troubleshooting

### "scrcpy is not installed"
Run: `python setup.py` and select the option to install scrcpy for your OS

### "ADB not found"
- Windows: Download Android SDK Platform Tools
- macOS: `brew install android-platform-tools`
- Linux: `sudo apt install android-tools-adb`

### Device not recognized
1. Connect device with USB cable
2. Enable USB Debugging in Developer Options
3. Run: `adb devices` to verify connection
4. Approve any prompts on the device

### Python package installation fails
Try upgrading pip first:
```bash
python -m pip install --upgrade pip
```

Then install requirements:
```bash
python -m pip install -r requirements.txt
```

## Running V Scanner

Once setup is complete:

```bash
python main.py
```

The app will:
1. Check all dependencies
2. Display the banner and startup animation
3. Auto-detect connected Android devices
4. Present an interactive menu with options

## Features Requiring Full Setup

- **Device Scanner**: Requires ADB
- **Screen Mirroring**: Requires scrcpy
- **Admin Operations**: Requires ADB and device access
- **Vulnerability Scanning**: Requires ADB

## Platform-Specific Notes

### Windows
- Use PowerShell or Command Prompt
- For Scoop/Chocolatey, ensure they're installed
- May need to enable script execution: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### macOS
- Requires Homebrew (installed by setup.py if needed)
- May require password for ADB installation

### Linux
- Most distributions use apt/snap
- May require sudo for installation
- Some systems use `adb` or `android-tools-adb` package name

## Getting Help

For issues with:
- **Python dependencies**: Check `requirements.txt`
- **scrcpy**: Visit https://github.com/Genymobile/scrcpy
- **ADB**: Visit https://developer.android.com
- **V Scanner**: Check README.md and documentation

---

**Last Updated:** March 2, 2026
