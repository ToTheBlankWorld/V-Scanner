# V Scanner Usage Guide

## Overview

V Scanner is a comprehensive mobile security toolkit consisting of:
1. **CLI Tool** - Interactive Python scanner with GEMINI-style UI
2. **Android App** - Native app with vulnerability scanning and Privacy Guardian features

---

## 🖥️ CLI Tool Usage

### Prerequisites

- **Python 3.8+** (3.10+ recommended)
- **Android device with USB debugging enabled**
- **Internet connection** (for first-time ADB setup)
- **Note:** ADB is automatically downloaded! No manual installation needed.

### Installation & Startup

```bash
cd cli
pip install -r requirements.txt
python main.py
```

**On first run:**
- The CLI will automatically download Android Platform Tools
- ADB will be configured automatically
- Then the interactive menu will appear

### Menu System

After startup, you'll see an interactive menu with 10 options:

```
 1. 📲 List Applications
 2. 🔍 Analyze Single App
 3. 🔒 Full Device Scan
 4. ⚙️  Admin Operations
 5. 📡 Sensor Monitoring
 6. ℹ️  Full Device Info
 7. 📊 Demo Mode
 8. 🔄 Change Device
 9. ⚙️  Reconfigure ADB
 10. ❌ Exit
```

### Menu Options Explained

#### Option 1: 📲 List Applications
Lists all installed applications with their details.
- Choose to include system apps or third-party only
- Shows app name, package name
- Total count displayed

#### Option 2: 🔍 Analyze Single App
Performs detailed security analysis on a specific app.
- Enter package name to analyze
- Shows vulnerabilities and risks
- Detailed permission analysis

#### Option 3: 🔒 Full Device Scan
Scans ALL installed apps and generates comprehensive security report.
- Analyzes all applications
- Professional report generation (HTML/JSON/TXT)
- Risk classification
- Saves to cli/reports/ directory

#### Option 4: ⚙️ Admin Operations
Advanced administrative functions:
- Pull APK files
- Force stop applications
- Uninstall applications
- Open applications
- View system logs

#### Option 5: 📡 Sensor Monitoring
Real-time monitoring of device sensors and hardware.

**Option 5.1:** Live Hardware Usage
- Real-time CPU usage
- RAM tracking
- Camera, Microphone, GPS detection
- Continuous updates (2-second intervals)

**Option 5.2:** All Sensor Values
- Static sensor readings
- Accelerometer, Gyroscope, Magnetometer
- Temperature sensors
- Continuous updates with details

#### Option 6: ℹ️ Full Device Info
Comprehensive device information with 7 panels:

- 🔧 **Hardware** - Model, Manufacturer, Board
- 🔐 **System** - Android version, API, Security patch
- 💾 **Memory/Storage** - RAM, storage metrics
- 🌐 **Network** - IP, MAC, Bluetooth details
- 🔑 **Identifiers** - IMEI, Serial, IMSI
- 🔨 **Build** - Fingerprint, Display ID, Bootloader  
- 🌍 **Locale** - Timezone, language settings

#### Option 7: 📊 Demo Mode
Demonstration with sample data (no device required).

#### Option 8: 🔄 Change Device
Switch to a different connected device.

#### Option 9: ⚙️ Reconfigure ADB
Fix ADB connections or re-download tools.

#### Option 10: ❌ Exit
Close the application.

### Device Selection

**On First Start:**
- CLI auto-detects connected devices
- 1 device found → auto-selects
- >1 devices found → asks you to choose
- 0 devices found → error message

**Device Info Shown:**
- Auto-displays 3-panel summary on selection
- Shows hardware and system specs

---

## 📱 Android App Usage

### Installation

1. Build:
   ```bash
   cd android
   ./gradlew assembleRelease
   ```

2. Install:
   ```bash
   adb install app/build/outputs/apk/release/app-release.apk
   ```

### Permissions Required

- **Query All Packages** - Scan for apps
- **Package Usage Stats** - Usage data (manual grant)
- **Foreground Service** - Background monitoring
- **Post Notifications** - Alerts

### Features

#### Dashboard
- Security score (0-100)
- Risk summary
- Recent alerts
- Sensor usage stats

#### Scanner
- Analyze all apps
- View risk classifications
- Detailed reports

#### Guardian
- Sensor monitoring
- Alert configuration
- Access logs

#### Alerts
- Security notifications
- Filter by type
- Dismiss/review

#### Settings
- Preferences
- Data management
- Permission control

---

## 🔍 Risk Levels

**High Risk** - Outdated SDK (<API 23), 6+ dangerous permissions

**Medium Risk** - Outdated SDK (API 23-28), 3-5 permissions

**Low Risk** - Recent SDK (API 29+), minimal permissions

---

## 📞 Support

For issues, visit the project repository.
