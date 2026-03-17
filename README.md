# 🔒 V Scanner 2.0 - Mobile Security & Privacy Auditor

**Enterprise-Grade Android Security Analysis Tool**
Version 2.0 | Advanced Vulnerability Detection | Real-time Device Analysis

---

## 🚀 Quick Start

### **One Command Installation**
```bash
cd cli
python main.py
```

That's it! The app will:
1. ✅ Auto-detect your OS (Windows/macOS/Linux)
2. ✅ Download ADB automatically
3. ✅ Download scrcpy automatically
4. ✅ Cache tools locally for future runs
5. ✅ Start scanning your device

### **What You Need**
- Python 3.8+
- Android device with USB debugging enabled
- USB cable

---

## 📋 Core Features

### 🔍 **Vulnerability Scanning**
- Full device security audit
- App permission analysis
- Hardcoded secret detection
- Suspicious URL patterns
- SDK compatibility issues
- Security configuration analysis

### 📱 **Device Management**
- List all installed applications
- View detailed app permissions
- Complete device information
- Device sensor monitoring
- App management tools
- Administrative operations

### 📊 **Advanced Tools**
- Deep APK analysis
- Live screen mirroring
- Comprehensive security reports
- Sensor data tracking
- Demo mode (no device needed)

---

## ⚡ NEW: Embedded Tools System

**V Scanner now automatically downloads and manages all required tools!**

### **What Gets Downloaded**
- 📥 **ADB (60MB)** - From Google's Android SDK
- 📥 **scrcpy (30MB)** - From GitHub Releases

### **How It Works**
✓ First run downloads everything automatically
✓ Tools cached locally → works offline after
✓ Cross-platform support (Windows/macOS/Linux)
✓ No admin rights needed
✓ Zero manual configuration

**See [TOOLS_SYSTEM.md](./TOOLS_SYSTEM.md) for details**

---

## 📥 Installation

### **Step 1: Install Python**
```bash
python --version  # Must be 3.8+
```

### **Step 2: Clone Project**
```bash
git clone https://github.com/ToTheBlankWorld/V-Scanner.git
cd V-Scanner
```

### **Step 3: Install Dependencies**
```bash
cd cli
pip install -r requirements.txt
```

### **Step 4: Start Scanner**
```bash
python main.py
```

**That's it!** Tools will auto-download on first run.

---

## 🎮 Usage

### **Main Menu**
```
1. 📱 List Applications       - View installed apps
2. 🔍 Analyze Single App      - Deep security analysis
3. 🔒 Full Device Scan        - Complete audit
4. ⚙️  Admin Operations       - App management
5. 📡 Sensor Monitoring       - Track sensors
6. ℹ️  Full Device Info       - Device details
7. 📊 Demo Mode               - See sample results
8. 🔄 Change Device           - Switch devices
9. ⚙️  Reconfigure ADB        - Update ADB
10. 📸 Screen Share            - Live mirroring
11. ❌ Exit                     - Quit
```

---

## 📊 Report Generation

Generates detailed security reports with:
- Dangerous permissions flagged
- Outdated SDK detection
- Hardcoded secrets found
- Suspicious URLs identified
- Overall risk assessment
- Recommendations

---

## 🏗️ Project Structure

```
V-Scanner/
├── cli/
│   ├── tools/                  ← Auto-created
│   │   ├── platform-tools/     ← ADB
│   │   └── scrcpy/             ← Screen mirror
│   ├── main.py                 ← Entry point
│   ├── scanner.py              ← Scan engine
│   ├── tools_manager.py        ← NEW: Tool manager
│   ├── auto_setup.py           ← NEW: Auto setup
│   ├── requirements.txt
│   └── ...more files
├── docs/                       ← Documentation
├── README.md                   ← This file
├── TOOLS_SYSTEM.md             ← NEW: Tools guide
└── QUICK_START.md              ← Quick ref
```

---

## 💻 System Requirements

### **Supported Platforms**
- ✅ Windows 10/11 (64-bit)
- ✅ macOS 10.15+ (Intel & M1/M2)
- ✅ Ubuntu/Debian Linux (64-bit)

### **Minimum Specs**
- Python 3.8+
- 200MB free disk space
- 512MB RAM
- Android 7.0+ device

### **Recommended**
- Python 3.10+
- 1GB free disk space
- 2GB RAM
- Fast internet (first run)

---

## 🔌 Device Connection

### **USB Connection**
1. Enable USB debugging on device
2. Connect via USB cable
3. Tap "Allow" on device
4. App auto-detects device

### **Wireless Connection (Android 11+)**
1. Device → Settings → Developer Options
2. Enable "Wireless Debugging"
3. Follow app's pairing guide
4. Enter pairing code & port

---

## 🔧 Advanced Usage

### **Check Tool Status**
```bash
cd cli
python -c "from tools_manager import ensure_tools; ensure_tools()"
```

### **Force Re-download Tools**
```python
from tools_manager import setup_adb, setup_scrcpy
setup_adb()    # Re-download ADB
setup_scrcpy() # Re-download scrcpy
```

### **Manual Tool Configuration**
```bash
cd cli
python
>>> from auto_setup import interactive_tool_setup
>>> interactive_tool_setup()
```

---

## 🐛 Troubleshooting

### **ADB not connecting**
```bash
cd cli/tools/platform-tools
./adb kill-server
./adb start-server
```

### **Device not detected**
- Enable USB debugging on device
- Try different USB port
- Restart ADB service
- Check USB cable

### **scrcpy download fails**
- Check internet connection
- Try manual re-download (will retry on next startup)
- Check disk space

### **Python packages missing**
```bash
pip install -r requirements.txt --upgrade
```

---

## 📚 Documentation

- **[TOOLS_SYSTEM.md](./TOOLS_SYSTEM.md)** - Embedded tools system detailed guide
- **[QUICK_START.md](./QUICK_START.md)** - Quick reference
- **[MASTER_README.md](./MASTER_README.md)** - Comprehensive guide
- **[docs/](./docs/)** - Technical documentation

---

## 🔒 Security & Privacy

- ✅ **Local only** - No data sent anywhere
- ✅ **No registration** - No account needed
- ✅ **Privacy respecting** - Honors device settings
- ✅ **Open source** - Audit the code
- ✅ **No telemetry** - No tracking

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🙏 Credits

- [scrcpy](https://github.com/Genymobile/scrcpy) - Screen mirroring
- [Android SDK](https://developer.android.com/) - ADB tool
- [Rich](https://rich.readthedocs.io/) - Terminal UI
- [Click](https://click.palletsprojects.com/) - CLI framework

---

**Version:** 2.0
**Last Updated:** March 17, 2026
**Status:** Production Ready ✅
