# V Scanner - Embedded Tools System

## Overview
V Scanner now includes an **embedded tools management system** that automatically downloads and manages ADB and scrcpy locally in the `cli/tools/` folder.

## How It Works

### 1. Automatic Tool Download (First Run)
When you start V Scanner for the first time:
- The app checks if ADB and scrcpy are in the `cli/tools/` folder
- If missing, it automatically downloads them from official sources:
  - **ADB**: From Google's Android SDK repository
  - **scrcpy**: From GitHub releases
- Tools are extracted and cached locally

### 2. On Every Startup
The app runs these checks in order:
1. **tools_manager.py** → Checks and downloads tools if missing
2. **auto_setup.py** → Verifies tools are ready
3. **dependency_checker.py** → Checks Python packages
4. App starts normally

## File Structure

```
cli/
├── tools/                    # Auto-created on first run
│   ├── platform-tools/       # ADB executable
│   │   ├── adb.exe          (Windows)
│   │   └── adb              (macOS/Linux)
│   └── scrcpy/              # scrcpy executable
│       ├── scrcpy.exe       (Windows)
│       └── scrcpy           (macOS/Linux)
├── tools_manager.py         # Main tool downloader
├── auto_setup.py            # Auto-setup orchestrator
├── adb_setup.py             # ADB management
└── main.py                  # Uses the above modules
```

## Key Features

### ✅ Platform Support
- **Windows**: Downloads Windows builds automatically
- **macOS**: Downloads macOS builds (x86_64 and ARM64)
- **Linux**: Downloads Linux builds automatically

### ✅ No Manual Installation Required
Users no longer need to:
- Download Android SDK Platform Tools
- Download scrcpy separately
- Set up system PATH variables
- Install Homebrew/apt packages

### ✅ Automatic Updates
Tools are downloaded once and cached. To re-download:
```python
from tools_manager import setup_adb, setup_scrcpy
setup_adb()    # Force re-download ADB
setup_scrcpy() # Force re-download scrcpy
```

## Main Components

### `tools_manager.py`
Handles downloading and extracting tools:
- `check_tool_exists(tool_type)` - Verify tool is installed
- `get_adb_path()` - Get ADB executable path
- `get_scrcpy_path()` - Get scrcpy executable path
- `setup_adb()` - Download/setup ADB
- `setup_scrcpy()` - Download/setup scrcpy
- `ensure_tools()` - Main function that runs on startup

### `auto_setup.py`
Orchestrates tool setup:
- `check_and_setup()` - Main setup function (called on app start)
- `check_tool_status()` - Display tool status
- `interactive_tool_setup()` - Manual tool management menu

### `adb_setup.py`
Manages ADB configuration:
- `get_adb_path()` - Get ADB with fallback (local → system → manual)
- `check_adb_valid()` - Verify ADB works
- `interactive_adb_setup()` - Manual ADB setup

## Usage in Code

### Using the Local Tools
```python
from tools_manager import get_adb_path, get_scrcpy_path

adb_exe = get_adb_path()
scrcpy_exe = get_scrcpy_path()

# Use them like normal
subprocess.run([adb_exe, 'devices'])
subprocess.run([scrcpy_exe, '-s', device_id])
```

### Checking if Tools Are Available
```python
from tools_manager import check_tool_exists

if check_tool_exists('adb'):
    print("ADB is ready!")

if not check_tool_exists('scrcpy'):
    print("Screen mirroring not available")
```

## Download URLs

The system downloads from these official sources:

### ADB (Android Debug Bridge)
- Windows: https://dl.google.com/android/repository/platform-tools-latest-windows.zip
- macOS: https://dl.google.com/android/repository/platform-tools-latest-darwin.zip
- Linux: https://dl.google.com/android/repository/platform-tools-latest-linux.zip

### scrcpy (Screen Mirroring)
- GitHub Releases: https://github.com/Genymobile/scrcpy/releases/download/v2.4/
- Platform-specific builds available

## Troubleshooting

### Tools folder permissions error
Solution: Ensure `cli/` folder has write permissions

### Download timeout
Solution: Check internet connection, tools will retry on next startup

### Manual tool re-download
Edit `tools_manager.py` and call `ensure_tools()` directly:
```bash
cd cli
python -c "from tools_manager import ensure_tools; ensure_tools()"
```

## Benefits

✅ **Zero Configuration** - Works out of the box
✅ **Cross-Platform** - Same experience on Windows, macOS, Linux
✅ **Portable** - Tools bundled with app, no system dependencies
✅ **Automatic Updates** - Can be enhanced to auto-update tools
✅ **Offline-Ready** - After first download, works without internet
✅ **No Admin Rights** - No system-wide installation needed

---

**Created**: 2026-03-17
**V Scanner Version**: 2.0
