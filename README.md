# Mobile Security Suite

A comprehensive mobile security toolkit consisting of:
1. **Vulnerability Scanner** - Scans installed Android apps for security issues
2. **Privacy Guardian** - Monitors sensor usage and alerts on suspicious activity

## 🚀 New Features (Latest)

- ⚙️ **Automatic ADB Setup** - Platform Tools auto-downloaded and configured
- 🎨 **Enhanced Interactive CLI** - GEMINI-style UI with animations and styled menus
- 📱 **Smart Device Selection** - Auto-detects single device, prompts for multiple
- 📊 **Device Information Panels** - Comprehensive device metadata display
- 🔍 **Real-time Hardware Monitoring** - Live CPU, RAM, camera, mic, GPS tracking
- 📡 **Advanced Sensor Monitoring** - Option 1 for live hardware, Option 2 for all sensors
- ℹ️ **Full Device Info** - 7-panel display with IMEI, MAC, IP, Bluetooth, timezone, etc.
- 🎯 **Improved App Listing** - Shows actual app names instead of activity names

## Project Structure

```
V Scanner/
├── README.md
├── MASTER_README.md        # Complete project overview
├── cli/                    # Cross-platform CLI tool (Python)
│   ├── main.py             # Interactive menu system
│   ├── scanner.py          # ADB interface & vulnerability scanner
│   ├── ui_styles.py        # UI components with styling
│   ├── adb_setup.py        # Automatic ADB/platform-tools setup
│   ├── permissions.py      # Permission analysis
│   ├── report_generator.py # Report generation
│   └── requirements.txt    # Python dependencies
│
├── android/                # Android Application
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── java/com/vsecurity/
│   │   │   │   ├── scanner/         # Vulnerability scanner
│   │   │   │   ├── guardian/        # Privacy guardian
│   │   │   │   ├── ui/              # User interface
│   │   │   │   └── data/            # Data layer
│   │   │   ├── res/                 # Resources
│   │   │   └── AndroidManifest.xml
│   │   └── build.gradle
│   ├── build.gradle
│   └── settings.gradle
│
└── docs/                   # Complete documentation
    ├── USAGE.md
    ├── ARCHITECTURE.md
    └── More...
```

## Features

### Vulnerability Scanner
- List all installed apps with intelligent app name parsing
- Flag risky permissions (SMS, Contacts, Camera, Location, Microphone)
- Detect outdated SDK versions
- Identify insecure hardcoded URLs
- Professional report generation (HTML, JSON, Text)

### Privacy Guardian
- Real-time sensor access monitoring
- Background alerts for suspicious activity
- Dashboard with usage analytics
- On-device logging with retention
- Permission audit recommendations

### CLI Tool Enhancements
- **Automatic Setup** - ADB auto-downloaded on first run
- **Interactive Menu** - GEMINI-style UI with 10 options
- **Smart Device Selection** - Auto-detect and auto-select
- **Device Info Display** - 7-panel comprehensive viewer
- **Real-time Monitoring** - Live hardware & sensor tracking

## Quick Start

### CLI Tool (Python)
```bash
cd cli
pip install -r requirements.txt
python main.py
```
**ADB is automatically downloaded and configured on first run!**

### Android App
```bash
cd android
./gradlew assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

## Requirements

### CLI
- Python 3.8+ (3.10+ recommended)
- Windows, Linux, or macOS
- Internet connection (for first-time ADB setup)
- **Note:** No manual ADB installation needed!

### Android App
- Android 8.0 (API 26) or higher
- Device with USB debugging enabled

## Documentation

See [MASTER_README.md](MASTER_README.md) for complete features, architecture, API references, and deployment guides.

## License
MIT License
