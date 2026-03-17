# 🚀 Quick Start - V Scanner 2.0

## ⚡ 60 Second Setup

```bash
# 1. Navigate to cli folder
cd cli

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python main.py

# Done! ✅ ADB & scrcpy auto-download, you're ready to scan
```

**First run will download tools (~100MB total). Subsequent runs use cached tools - no downloads needed!**

---

## 🆕 NEW: Automatic Tools Download

V Scanner 2.0 now **automatically downloads and manages all required tools**:

### What Gets Auto-Downloaded
- 📥 **ADB** - Android Debug Bridge (60MB from Google)
- 📥 **scrcpy** - Screen mirroring tool (30MB from GitHub)

### How It Works
1. First run → detects missing tools
2. Auto-downloads from official sources
3. Extracts to `cli/tools/` folder
4. Caches for next time → instant load
5. Works completely offline after first run

**No admin rights needed • Cross-platform • Zero manual setup**

➡️ **[Details: See TOOLS_SYSTEM.md](./TOOLS_SYSTEM.md)**

---

## 👀 What You'll See

### Step 1: Beautiful Banner
```
╔════════════════════════════════════════════════════════════════════╗
║                                                                    ║
║                     🔒 V-SCANNER 2.0                        ║
║            Mobile Security & Privacy Auditor                      ║
║                                                                    ║
║          🔐 Scan • Analyze • Protect • Defend               ║
║                                                                    ║
╚════════════════════════════════════════════════════════════════════╝
```

### Step 2: Auto-Setup Begins
```
[bold cyan]Initializing V Scanner...[/bold cyan]

🔧 Tool Setup

[green]✓ ADB available[/green]
[green]✓ scrcpy available[/green]

🔍 Checking Dependencies...
[green]✓ Python Packages - All installed[/green]
[green]✓ ADB (Android Debug Bridge) - Available[/green]
[green]✓ scrcpy (Screen Mirroring) - Installed[/green]
```

### Step 3: Animated Startup
```
   ▹ Initializing Security Engine... ✓
   ▹ Loading Vulnerability Database... ✓
   ▹ Connecting to Android Device... ✓
   ▹ Syncing Device Configuration... ✓
   ▹ Preparing Analysis Framework... ✓
```

### Step 4: Main Menu
```
╔════════════════════════════════════════════╗
║         🔒 MAIN MENU - V SCANNER          ║
╚════════════════════════════════════════════╝

  1   📱  List Applications
  2   🔍  Analyze Single App
  3   🔒  Full Device Scan
  4   ⚙️   Admin Operations
  5   📡  Sensor Monitoring
  6   ℹ️   Full Device Info
  7   📊  Demo Mode
  8   🔄  Change Device
  9   ⚙️   Reconfigure ADB
  10  📸  Screen Share
  11  ❌  Exit
```

---

## 📱 Your First Scan (5 Minutes)

### Step 1: Connect Android Device
- Plug in via **USB cable**
- Go to **Settings → Developer Options**
- Enable **USB Debugging**
- Tap **"Allow"** when device prompts
- App auto-detects! ✅

### Step 2: Choose a Scan
```
Select option (1-11): 3
```

### Step 3: Select App & Analyze
```
🔍 Analyzing Instagram...

[Scanning process with progress bar]

📊 Security Analysis: Instagram
├─ Dangerous Permissions: 8
├─ SDK Issues: 1
├─ Network Risks: 2
└─ Overall Risk: MEDIUM 🟡
```

### Step 4: View Results
```
📊 Security Scan Complete!

✓ 87 apps analyzed
🔴 High Risk: 4 apps
🟡 Medium Risk: 12 apps
🟢 Low Risk: 71 apps

Score: 62/100 🟡
```

---

## 🎯 Common Tasks

### Full Device Security Audit
```
Menu → [3] Full Device Scan
→ Choose scan options
→ Watch analysis
→ Get comprehensive report ✅
```

### Analyze Single App
```
Menu → [2] Analyze Single App
→ Enter package name
→ Review detailed security report ✅
```

### View All Apps
```
Menu → [1] List Applications
→ Browse installed apps
→ See app details ✅
```

### No Device? Try Demo Mode
```
Menu → [7] Demo Mode
→ See sample reports without device ✅
```

### Manage Apps
```
Menu → [4] Admin Operations
→ Uninstall/Open/Force Stop apps ✅
```

### Live Screen Mirroring
```
Menu → [10] Screen Share
→ View phone screen on computer ✅
```

---

## 🔧 Troubleshooting

### Error: "Device not detected"
```
✓ Check USB cable is fully connected
✓ Enable USB Debugging in Settings
✓ Tap "Allow" when device prompts
✓ Try different USB port
✓ Restart ADB: Menu → [9] Reconfigure ADB
```

### Error: "Tool download failed"
```
✓ Check internet connection
✓ Check disk space (need ~100MB)
✓ Check firewall settings
✓ App will auto-retry on next startup
```

### Error: "Python packages missing"
```bash
pip install -r requirements.txt --upgrade
```

### Error: "scrcpy won't start"
```
✓ Check if scrcpy downloaded successfully
✓ Verify disk space
✓ Close any existing scrcpy windows
✓ Restart application
```

---

## 📊 What Each Menu Option Does

| # | Option | Purpose |
|---|--------|---------|
| 1 | 📱 List Apps | View all installed applications |
| 2 | 🔍 Analyze App | Deep security analysis of one app |
| 3 | 🔒 Full Scan | Complete device security audit |
| 4 | ⚙️ Admin Ops | Install/uninstall/manage apps |
| 5 | 📡 Sensors | Monitor device hardware sensors |
| 6 | ℹ️ Device Info | View device specifications |
| 7 | 📊 Demo Mode | See sample report (no device needed) |
| 8 | 🔄 Change Device | Switch to different device |
| 9 | ⚙️ Reconfigure ADB | Update ADB settings |
| 10 | 📸 Screen Share | Live phone screen mirroring |
| 11 | ❌ Exit | Close application |

---

## 📋 System Requirements

### Minimum
- Python 3.8+
- Windows/macOS/Linux
- 200MB free disk space
- Android 7.0+ device

### Recommended
- Python 3.10+
- 1GB free disk space
- Fast internet (first run only)
- Android 11+ device

---

## ✅ First-Run Checklist

- [ ] Python 3.8+ installed
- [ ] Navigate to `cli` folder
- [ ] Run `pip install -r requirements.txt`
- [ ] Run `python main.py`
- [ ] See beautiful banner
- [ ] Wait for auto-download (first time only)
- [ ] Connect Android device via USB
- [ ] Enable USB Debugging
- [ ] Tap "Allow" on device
- [ ] Choose menu option
- [ ] Enjoy scanning! 🎉

---

## 🌟 V Scanner 2.0 Highlights

✅ **Zero Setup** - Tools auto-download
✅ **Fast** - Caches tools locally
✅ **Beautiful** - GEMINI-inspired stunning UI
✅ **Smart** - Intelligent error handling
✅ **Portable** - Works anywhere
✅ **Secure** - All local, no data sent
✅ **Easy** - Intuitive for anyone

---

## 📚 Need More Information?

- **Tools System:** [TOOLS_SYSTEM.md](./TOOLS_SYSTEM.md) - How auto-download works
- **Full Guide:** [README.md](./README.md) - Complete documentation
- **Master Guide:** [MASTER_README.md](./MASTER_README.md) - Comprehensive reference
- **Technical Docs:** [docs/](./docs/) - Architecture & API details

---

## 🚀 Ready to Scan?

```bash
cd cli
python main.py
```

**Let V Scanner protect your Android device!** 🔒

---

**V Scanner 2.0** | Enterprise Android Security Auditor
*March 2026* | Production Ready ✅
