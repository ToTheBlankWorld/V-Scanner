# V Scanner Usage Guide

## Overview

V Scanner is a comprehensive mobile security toolkit consisting of:
1. **CLI Tool** - Cross-platform Python scanner for analyzing Android apps via ADB
2. **Android App** - Native app with vulnerability scanning and Privacy Guardian features

---

## CLI Tool Usage

### Prerequisites

- Python 3.8 or higher
- ADB (Android Debug Bridge) installed and in PATH
- Android device with USB debugging enabled

### Installation

```bash
cd cli
pip install -r requirements.txt
```

### Commands

#### List Installed Apps
```bash
python scanner.py list-apps
```

Lists all installed apps on the connected device.

Options:
- `--include-system` - Include system apps in the list

#### Analyze Single App
```bash
python scanner.py analyze com.example.app
```

Performs detailed security analysis on a specific package.

Output includes:
- Package information
- Target SDK version assessment
- Dangerous permissions analysis
- Risk level calculation

#### Full Device Scan
```bash
python scanner.py scan
```

Scans all installed apps and generates a comprehensive report.

Options:
- `--output [path]` - Output directory for reports (default: ./reports)
- `--format [html|json|text]` - Report format (default: html)
- `--include-system` - Include system apps in scan

#### Demo Mode
```bash
python scanner.py demo
```

Runs a demonstration with sample data (no device required).

### Example Workflow

```bash
# Connect device and verify ADB connection
adb devices

# Run full security scan
python scanner.py scan --output ./my_reports --format html

# Analyze specific app of concern
python scanner.py analyze com.suspicious.app
```

---

## Android App Usage

### Installation

1. Build the app using Android Studio or Gradle:
   ```bash
   cd android
   ./gradlew assembleRelease
   ```

2. Install the APK on your device:
   ```bash
   adb install app/build/outputs/apk/release/app-release.apk
   ```

### Permissions Required

The app requires these permissions:
- **Query All Packages** - To scan installed apps
- **Package Usage Stats** - For app usage monitoring (requires manual grant in Settings)
- **Foreground Service** - For Privacy Guardian background monitoring
- **Post Notifications** - For security alerts

### Features

#### Dashboard
- **Security Score** - Overall device security rating (0-100)
- **Risk Summary** - Count of high/medium/low risk apps
- **Recent Alerts** - Latest security notifications
- **Sensor Usage** - Today's camera/mic/location access

#### Vulnerability Scanner
1. Tap the **Scanner** tab
2. Press **Start Scan** to analyze all installed apps
3. View results sorted by risk level
4. Filter by risk category (High/Medium/Low)
5. Tap any app for detailed permission analysis

#### Privacy Guardian
1. Enable Guardian from the **Guardian** tab
2. Configure which sensors to monitor:
   - Camera
   - Microphone
   - Location
3. Set alert preferences for background access
4. View recent sensor access logs

#### Alerts
- View all security and privacy alerts
- Filter by alert type
- Dismiss individual or all alerts
- See which apps triggered each alert

#### Settings
- **Scanner Settings**
  - Include/exclude system apps
  - Enable auto-scan on app install
- **Guardian Settings**
  - Toggle individual sensor monitoring
  - Configure background check intervals
- **Data Management**
  - Clear scan history
  - Clear sensor logs
  - Export data

---

## Understanding Risk Levels

### High Risk
Apps with:
- Very outdated target SDK (< API 23)
- Multiple dangerous permissions (6+)
- Camera + Microphone + Location access
- SMS/Call log access

### Medium Risk
Apps with:
- Outdated target SDK (API 23-28)
- Moderate dangerous permissions (3-5)
- Some sensitive data access

### Low Risk
Apps with:
- Current target SDK (API 29+)
- Minimal dangerous permissions (0-2)
- Standard functionality permissions

---

## Dangerous Permissions Reference

| Permission | Category | Risk Level |
|------------|----------|------------|
| CAMERA | Camera | High |
| RECORD_AUDIO | Microphone | High |
| ACCESS_FINE_LOCATION | Location | High |
| READ_CONTACTS | Contacts | Medium |
| READ_CALL_LOG | Phone | High |
| READ_SMS | SMS | High |
| READ_EXTERNAL_STORAGE | Storage | Medium |
| BODY_SENSORS | Sensors | Medium |

---

## Privacy Guardian Alerts

### Alert Types

1. **Background Access** - App accessed sensor while in background
2. **Excessive Usage** - Unusually frequent sensor access
3. **Suspicious Timing** - Sensor access at unusual hours (night)
4. **New Permission** - App was granted new sensitive permission

### Recommended Actions

- Review apps with frequent alerts
- Revoke unnecessary permissions
- Consider uninstalling high-risk apps
- Report suspicious behavior

---

## Troubleshooting

### CLI Issues

**"No devices found"**
- Ensure USB debugging is enabled
- Check device is connected: `adb devices`
- Try: `adb kill-server && adb start-server`

**"Permission denied"**
- Grant shell access: Enable USB debugging (Security settings) on device

### App Issues

**"Usage access required"**
- Go to Settings > Apps > Special access > Usage access
- Enable for V Scanner

**Guardian not detecting accesses**
- Ensure app has all required permissions
- Check that Guardian service is running (notification visible)
- Some accesses may not be detectable on all devices

---

## Best Practices

1. **Regular Scans** - Scan after installing new apps
2. **Review Permissions** - Check why apps need specific permissions
3. **Enable Guardian** - Monitor sensor access continuously
4. **Act on Alerts** - Don't ignore high-risk warnings
5. **Keep Updated** - Ensure apps target recent SDKs

---

## Support

For issues or feature requests, please open an issue on the project repository.
