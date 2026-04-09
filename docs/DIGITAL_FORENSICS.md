# 🔬 Digital Forensics - Complete Guide

**V Scanner 2.0 includes a powerful digital forensics module for extracting and analyzing device data.**

---

## 📋 Overview

The Digital Forensics module provides 8 different extraction operations:

| # | Operation | Purpose |
|---|-----------|---------|
| 1 | Extract App Databases | Pull all .db files from selected app |
| 2 | Extract App Shared Prefs | Pull app configuration XML files |
| 3 | Extract App Files | Pull app data files folder (recursive) |
| 4 | Extract System Logs | Pull logcat dump |
| 5 | Extract Installed Packages | List all installed applications |
| 6 | Extract Running Processes | Snapshot of active processes |
| 7 | Extract WiFi Networks | Pull saved WiFi network configs |
| 8 | Generate Report | Create comprehensive case report |

---

## 🚀 Getting Started

### **Access Forensics Module**

From main menu:
```
Select: 9 (or Digital Forensics option)

🔍 DIGITAL FORENSICS - ROOTED ✓

  📱 [1] Extract App Databases
  ⚙️  [2] Extract App Shared Prefs
  📁 [3] Extract App Files
  📋 [4] Extract System Logs
  📦 [5] Extract Installed Packages
  ⚡ [6] Extract Running Processes
  🌐 [7] Extract WiFi Networks
  📝 [8] Generate Report
  ❌ [0] Back to Main Menu
```

---

## 📱 Option 1: Extract App Databases

**Extracts all .db files from selected app**

### How It Works

1. Choose app type: System Apps or Third-Party Apps
2. Browse paginated list (50 apps per page)
3. Select app by number
4. All database files extracted automatically

### Navigation

```
Select: 1          → Choose app #1
Select: 25         → Choose app #25  
Select: next       → Show next 50 apps
Select: pkg:com.whatsapp  → Use custom package name
```

### Output Structure

```
CaseFolder/
└── Device_database/
    └── com.whatsapp/
        └── databases/
            ├── wa.db
            ├── msgstore.db
            ├── axolotl.db
            ├── chatsettings.db
            └── ...more files
```

### File Types Extracted

- `.db` - SQLite database files
- `.db-journal` - Transaction journals
- `.db-wal` - Write-ahead log
- `.db-shm` - Shared memory

---

## ⚙️ Option 2: Extract App Shared Preferences

**Extracts app configuration and settings**

### How It Works

Similar to database extraction, but targets shared_prefs folder which contains XML configuration files.

### Output Structure

```
CaseFolder/
└── Device_database/
    └── com.app.name/
        └── shared_prefs/
            ├── preferences.xml
            ├── settings.xml
            └── ...config files
```

### What It Contains

- User preferences
- App settings
- Configuration values
- Stored flags and states

---

## 📁 Option 3: Extract App Files

**Extracts app's data files folder**

### How It Works

Recursively extracts entire files folder, preserving directory structure.

### Output Structure

```
CaseFolder/
└── Device_database/
    └── com.app.name/
        └── files/
            ├── file1.txt
            ├── subfolder/
            │   ├── file2.json
            │   └── file3.dat
            └── ...more files
```

### What It Contains

- Downloaded files
- Cached data
- Generated documents
- App-specific data files

---

## 📋 Option 4: Extract System Logs

**Pulls complete logcat dump**

### How It Works

Captures all system and app logs in real-time.

### Output

```
CaseFolder/
└── system_logs.txt
```

Contains:
- App crashes
- System errors
- Debug messages
- Performance logs
- Timestamps for all events

---

## 📦 Option 5: Extract Installed Packages

**Lists all installed applications**

### Output

```
CaseFolder/
└── installed_packages.txt
```

Format:
```
Total Packages: 359

android.overlay.common
com.android.apps.docs
com.android.browser
com.android.calculator2
...
```

---

## ⚡ Option 6: Extract Running Processes

**Snapshot of active processes**

### Output

```
CaseFolder/
└── running_processes.txt
```

Shows:
- Process ID (PID)
- User running process
- Memory usage
- Process name

---

## 🌐 Option 7: Extract WiFi Networks

**Pull saved WiFi network configurations**

### Output

```
CaseFolder/
└── wifi_networks.txt
```

Contains:
- Network SSIDs
- Connection history
- Signal strength info
- Frequency bands

⚠️ **Note:** May contain encrypted passwords (requires root)

---

## 📝 Option 8: Generate Report

**Creates comprehensive forensics case report**

### Output

```
CaseFolder/
└── forensics_report.json
```

### Report Contents

```json
{
  "case_name": "case_20260410_001143",
  "generated": "2026-04-10T15:03:22",
  "device": {
    "model": "Xiaomi Redmi Note 11",
    "manufacturer": "Xiaomi",
    "brand": "Xiaomi",
    "android_version": "13",
    "api_level": "33",
    "build_id": "TP1A.220624.014",
    "kernel_version": "5.10.66",
    "security_patch": "2024-01-01"
  },
  "device_rooted": true,
  "root_method": "Apatch/Magisk/SuperUser",
  "system_info": {
    "installed_packages": 359,
    "running_processes": 245,
    "selinux_status": "Enforcing"
  },
  "extractions": [
    {
      "type": "app_databases",
      "app_name": "Whatsapp",
      "package": "com.whatsapp",
      "files": 49,
      "status": "success",
      "location": "..."
    }
  ],
  "summary": {
    "total_operations": 8,
    "successful": 7,
    "database_files": 49
  }
}
```

---

## 🗂️ Case Structure

Each forensics session creates a case folder:

```
cli/forensics_cases/
└── case_20260410_001143/              (Timestamp-based case folder)
    ├── metadata.json                   (Case info)
    ├── forensics_report.json           (Main report)
    ├── system_logs.txt
    ├── installed_packages.txt
    ├── running_processes.txt
    ├── wifi_networks.txt
    └── Device_database/
        ├── com.whatsapp/
        │   ├── databases/
        │   ├── shared_prefs/
        │   └── files/
        ├── com.instagram.android/
        │   └── ...
        └── ...more apps
```

---

## 🔒 Requirements

### **Root Access**

Most extraction operations require root access:
- ✅ App databases (requires root via su)
- ✅ App shared preferences (requires root)
- ✅ App files (requires root)
- ✅ WiFi networks (requires root)
- ✅ System logs (works without root, limited)
- ✅ Installed packages (works without root)
- ✅ Running processes (works without root, limited)

### **Supported Root Methods**

- Apatch
- Magisk
- SuperUser
- Any custom ROM with root

---

## 💡 Use Cases

### **App Data Recovery**

Extract databases from deleted or uninstalled apps if data still exists.

### **Security Audit**

Extract and analyze what data apps store locally.

### **Evidence Collection**

Gather forensic evidence for investigation or dispute resolution.

### **Compliance Check**

Verify what personal data is stored on device.

### **Performance Analysis**

Check app logs for crash reports and performance issues.

### **Privacy Review**

Audit WiFi networks and system processes for suspicious activity.

---

## ⚠️ Important Notes

1. **Device Must Be Connected** - Via USB with debugging enabled or wireless
2. **Root Required** - For most operations (device should already be rooted)
3. **Large Files** - Database extractions can be multiple MB
4. **Time Required** - First extraction may take 1-5 minutes
5. **Storage** - Ensure sufficient disk space on computer
6. **Privacy** - All data stays local - nothing sent anywhere

---

## 🔧 Advanced

### **Manual Package Entry**

If you know the exact package name:

```
Select: next
Select: pkg:com.example.app
```

This bypasses the app list entirely.

### **Direct API Usage**

```python
from digital_forensics import DeviceForensics

forensics = DeviceForensics(adb_interface)
forensics.create_case()
forensics.extract_app_databases("com.whatsapp", "Whatsapp")
forensics.generate_report()
```

---

## 📞 Troubleshooting

### **"Root access required"**

→ Device must be rooted (Magisk, Apatch, etc.)

### **"No databases folder found"**

→ Selected app doesn't have databases, or app path was incorrect

### **"Failed to stat remote object"**

→ File access denied - check root permissions

### **"Timeout extracting files"**

→ Large files taking too long - wait longer or check connection

---

## 📚 See Also

- [README.md](../README.md) - Main documentation
- [USAGE.md](./USAGE.md) - General usage guide
- [MASTER_README.md](../MASTER_README.md) - Comprehensive guide

---

**Last Updated:** April 10, 2026
**Version:** 2.0
**Status:** Fully Functional ✅
