# Mobile Security Suite

A comprehensive mobile security toolkit consisting of:
1. **Vulnerability Scanner** - Scans installed Android apps for security issues
2. **Privacy Guardian** - Monitors sensor usage and alerts on suspicious activity

## Project Structure

```
V Scanner/
├── cli/                    # Cross-platform CLI tool (Python)
│   ├── scanner.py          # Main CLI scanner
│   ├── permissions.py      # Permission analysis
│   ├── report_generator.py # Report generation
│   └── requirements.txt    # Python dependencies
│
├── android/                # Android Application
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── java/com/vsecurity/
│   │   │   │   ├── scanner/        # Vulnerability scanner
│   │   │   │   ├── guardian/       # Privacy guardian
│   │   │   │   ├── ui/             # User interface
│   │   │   │   └── utils/          # Utilities
│   │   │   ├── res/                # Resources
│   │   │   └── AndroidManifest.xml
│   │   └── build.gradle
│   ├── build.gradle
│   └── settings.gradle
│
└── docs/                   # Documentation
    └── USAGE.md
```

## Features

### Vulnerability Scanner
- List all installed apps with permission summaries
- Flag risky permissions (SMS, Contacts, Camera, Location, Microphone)
- Detect outdated SDK versions
- Identify insecure hardcoded URLs
- Generate detailed security assessment reports

### Privacy Guardian
- Real-time sensor access monitoring
- Background service for continuous protection
- Alerts for suspicious sensor access
- Dashboard with usage trends
- Permission audit recommendations

## Quick Start

### CLI Tool (Python)
```bash
cd cli
pip install -r requirements.txt
python scanner.py --help
```

### Android App
```bash
cd android
./gradlew assembleDebug
```

## Requirements

### CLI
- Python 3.8+
- ADB (Android Debug Bridge) for device connectivity

### Android App
- Android 8.0 (API 26) or higher
- Device with USB debugging enabled (for CLI connectivity)

## License
MIT License
