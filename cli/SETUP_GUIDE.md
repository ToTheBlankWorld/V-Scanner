# V Scanner 2.0 - Automated ADB Setup & GEMINI-Style CLI

## 🚀 What's New

### 1. **Automated ADB Setup**
The app now automatically downloads, installs, and configures the Android Debug Bridge (ADB) - no manual setup required!

**Features:**
- ✅ Auto-detects if ADB is installed
- ✅ Automatically downloads platform-tools if missing
- ✅ Configures adb_config.json automatically
- ✅ Falls back to manual configuration if needed
- ✅ Works on Windows, macOS, and Linux

### 2. **Beautiful GEMINI-Style CLI Interface**
Transform your terminal experience with a modern, colorful interface inspired by Google's Gemini AI design.

**Features:**
- 🎨 Gradient banners and stylized headers
- ✨ Animated startup sequence
- 🎯 Responsive animated device selector
- 📊 Enhanced visual feedback for all operations
- 🎪 Loading spinners and progress animations
- 📱 Device-aware interface styling

---

## 📦 Installation

### Prerequisites
```bash
pip install -r requirements.txt
```

### Required Packages (Already in requirements.txt)
- `adb-shell>=0.4.3` - ADB interface
- `rich>=13.0.0` - Beautiful terminal output
- `click>=8.0.0` - CLI utilities
- `jinja2>=3.0.0` - Report templating
- `requests>=2.28.0` - HTTP requests
- `pyyaml>=6.0` - YAML support
- `colorama>=0.4.6` - Cross-platform colors
- `tabulate>=0.9.0` - Table formatting

---

## 🚀 Quick Start

### First Run (Automatic ADB Setup)
```bash
python main.py
```

The app will:
1. Display a beautiful banner
2. Run startup animations
3. Automatically configure ADB
4. Download platform-tools if needed
5. Connect to your Android device

### Subsequent Runs
```bash
python main.py
```

ADB configuration is saved, so it runs instantly!

---

## 📋 Features Overview

### Main Menu
```
┌─────────────────────────────────────┐
│    🔒 MAIN MENU - V SCANNER         │
├─────────────────────────────────────┤
│ 1  📱  Select Android Device        │
│ 2  📲  List Applications            │
│ 3  🔍  Analyze Single App           │
│ 4  🔒  Full Device Scan             │
│ 5  ⚙   Admin Operations             │
│ 6  📡  Sensor Monitoring            │
│ 7  📊  Demo Mode                    │
│ 8  ⚙   Reconfigure ADB              │
│ 9  ❌  Exit                         │
└─────────────────────────────────────┘
```

### Key Features

1. **📱 Select Android Device**
   - Auto-detects connected devices
   - Animated device selection interface
   - Shows device model, Android version, and more

2. **📲 List Applications**
   - View all installed apps or system apps only
   - Real-time filtering and sorting
   - Display app names and package IDs

3. **🔍 Analyze Single App**
   - Deep security analysis of any installed app
   - Scans for dangerous permissions
   - Outdated SDK warnings
   - Detects insecure URLs/hardcoded values

4. **🔒 Full Device Scan**
   - Comprehensive security audit of all apps
   - Configurable scan options
   - Generate reports in HTML, JSON, or text format
   - Security score calculation

5. **⚙️ Admin Operations**
   - Uninstall apps
   - Launch/open apps
   - Force stop apps
   - App management utilities

6. **📡 Sensor Monitoring**
   - List all device sensors
   - Sensor access logging
   - Track sensor usage

7. **📊 Demo Mode**
   - View sample reports without a device
   - Perfect for testing and demos

---

## 🔧 Configuration

### Manual ADB Setup
If automatic setup fails, you can manually configure ADB:

1. Download [Android SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools)
2. Extract to your desired location
3. Run the app and select "Reconfigure ADB Path"
4. Enter the path to `adb.exe` (Windows) or `adb` (macOS/Linux)

### ADB Configuration File
```json
{
  "adb_path": "/path/to/adb.exe"
}
```

---

## 📊 New Modules

### 1. `adb_setup.py`
**Automated ADB setup and configuration**

```python
from adb_setup import get_adb_path

# Automatically setup ADB
adb_path = get_adb_path()
```

**Key Functions:**
- `setup_adb_automatic()` - Auto-setup with fallback
- `download_and_setup_platform_tools()` - Download latest platform-tools
- `interactive_adb_setup()` - Manual configuration
- `get_adb_path()` - Get configured ADB path

### 2. `ui_styles.py`
**Beautiful terminal UI components**

```python
from ui_styles import print_gradient_banner, print_main_menu

# Display impressive banner
print_gradient_banner()

# Show styled menu
print_main_menu()
```

**Key Functions:**
- `print_gradient_banner()` - Impressive startup banner
- `print_startup_animation()` - Animated initialization
- `print_main_menu()` - Styled main menu
- `print_device_selector_animation()` - Animated device picker
- `print_security_score_card()` - Beautiful score display
- `print_success_message()` - Success notifications
- `print_error_message()` - Error notifications
- `print_scan_complete_animation()` - Completion animation

---

## 🎨 UI Highlights

### Startup Sequence
```
⠋ Initializing Security Engine...
✓ ✓ ✓ ✓ ✓
```

### Device Selection
```
🔍 Scanning for Android Devices...
   ✓ Found 1 device(s)

#  Device ID               Status
1  emulator-5554           ● Connected
```

### Security Score
```
┌─────────────────────────────────────┐
│   DEVICE SECURITY SCORE             │
├─────────────────────────────────────┤
│                                     │
│        🟢 [85/100]                  │
│                                     │
├─────────────────────────────────────┤
│  Total Apps:    42
│  🔴 High Risk:   2
│  🟡 Medium Risk: 5
│  🟢 Low Risk:    35
└─────────────────────────────────────┘
```

---

## 📝 Usage Examples

### Example 1: Scan Device on First Run
```bash
$ python main.py
[Beautiful Banner displays]
[Startup animation runs]
🤖 Automated ADB Setup
✓ Found ADB in system PATH
✓ ADB ready: adb
🔍 Scanning for Android devices...
✓ Found 1 device(s) ready

Main Menu appears...
```

### Example 2: Analyze a Single App
```
Select option (1-9): 3
Enter package name to analyze: com.instagram.android
Enable deep APK analysis? (slower)
[1] No (quick analysis)
[2] Yes (search for URLs and hardcoded values)
Select (1 or 2): 2
🔍 Analyzing com.instagram.android...

[Beautiful analysis report displays]
```

### Example 3: Full Device Scan
```
Select option (1-9): 4
Configure scan options:
[1] Include system apps?
[a] No (third-party only)
[b] Yes (all apps)
Select (a or b): a

[Scanning progress with animated bar]
████████████░░░░░░░░ 60.0%

[Scan complete animation]
✓ SCAN COMPLETE
Analysis successful!
```

---

## 🐛 Troubleshooting

### ADB Not Found
**Problem:** "ADB not found in system PATH"

**Solution:**
1. Manually run the app again (it will auto-download)
2. Or provide the ADB path manually
3. Check [Android SDK Platform Tools](https://developer.android.com/tools)

### No Devices Detected
**Problem:** "No Android devices found!"

**Solution:**
1. Enable USB Debugging on your Android device
2. Connect via USB cable
3. Tap "Allow" when prompted on device
4. Restart ADB: `adb kill-server && adb start-server`

### Permission Errors
**Problem:** "Permission denied" when downloading platform-tools

**Solution:**
1. Run with administrator/sudo privileges
2. Or manually provide an existing ADB path

### Windows-Specific Issues
- Ensure USB drivers are installed
- Try different USB ports
- Disable USB Selective Suspend in Power Options

---

## 📚 Documentation

- [Full Architecture](../docs/ARCHITECTURE.md)
- [Privacy Guardian](../docs/PRIVACY_GUARDIAN_README.md)
- [Deployment Guide](../docs/DEPLOYMENT_CHECKLIST.md)
- [Usage Guide](../docs/USAGE.md)

---

## 🔐 Security

V Scanner runs completely locally. No data is sent to external servers.
- All analysis is on-device
- Reports are generated locally
- Your Android data stays on your device

---

## 💡 Tips & Tricks

1. **Use Demo Mode** - Try option 7 to see sample reports without a device
2. **Save Reports** - Generate HTML reports for easy sharing
3. **Batch Analysis** - Use the full scan for comprehensive security audit
4. **Deep Analysis** - Use deep APK scanning to find hardcoded values and URLs

---

## 🚀 Version History

### v2.0 (Latest)
- ✨ Automated ADB setup with auto-download
- 🎨 GEMINI-style beautiful CLI interface
- ✨ Animated startup and interactions
- 🎯 Improved device detection
- 📊 Enhanced visual feedback

### v1.0
- Basic security scanning
- Device analysis
- App permission checking

---

## 📞 Support

For issues or questions:
1. Check the troubleshooting section
2. Review the [documentation](../docs/)
3. Check device USB debugging settings
4. Verify ADB connectivity with: `adb devices`

---

**Enjoy scanning with style! 🎨🔒**
