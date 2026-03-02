"""
V Scanner - Complete Setup Script
Installs all Python dependencies and system tools required to run the application
"""

import subprocess
import sys
import os
import platform
from pathlib import Path

def print_header(text):
    """Print formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def run_command(cmd, description):
    """Run a command with error handling."""
    print(f"[*] {description}...")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"[✓] {description} - Success!")
            return True
        else:
            print(f"[✗] {description} - Failed!")
            if result.stderr:
                print(f"    Error: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[✗] {description} - Timeout!")
        return False
    except Exception as e:
        print(f"[✗] {description} - Error: {str(e)[:200]}")
        return False

def main():
    print_header("V SCANNER - COMPLETE SETUP")
    
    system = platform.system()
    
    # Step 1: Install Python dependencies
    print_header("Step 1: Installing Python Dependencies")
    
    requirements_file = Path(__file__).parent / "requirements.txt"
    if requirements_file.exists():
        cmd = f"{sys.executable} -m pip install -r {requirements_file}"
        if run_command(cmd, "Installing Python packages"):
            print("[✓] All Python dependencies installed!")
        else:
            print("[!] Failed to install some Python packages. Try manually:")
            print(f"    {sys.executable} -m pip install -r {requirements_file}")
    else:
        print(f"[!] requirements.txt not found at {requirements_file}")
    
    # Step 2: Install scrcpy
    print_header("Step 2: Installing scrcpy (Screen Mirroring)")
    
    scrcpy_installed = False
    
    if system == "Windows":
        print("[*] Detected Windows - Installing via Scoop...")
        
        # Check if Scoop is installed
        try:
            subprocess.run(["scoop", "--version"], capture_output=True, timeout=5)
            scoop_available = True
        except:
            scoop_available = False
        
        if scoop_available:
            cmd = 'powershell -Command "Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force; scoop install scrcpy"'
            scrcpy_installed = run_command(cmd, "Installing scrcpy via Scoop")
        else:
            print("[!] Scoop not found. Attempting to install Scoop first...")
            scoop_cmd = 'powershell -Command "iwr -useb get.scoop.sh | iex"'
            if run_command(scoop_cmd, "Installing Scoop"):
                cmd = 'powershell -Command "Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force; scoop install scrcpy"'
                scrcpy_installed = run_command(cmd, "Installing scrcpy via Scoop")
        
        if not scrcpy_installed:
            print("\n[!] Could not auto-install scrcpy. Manual options:")
            print("    Option 1 (Scoop):     scoop install scrcpy")
            print("    Option 2 (Chocolatey): choco install scrcpy")
            print("    Option 3 (Manual):    Download from https://github.com/Genymobile/scrcpy/releases")
    
    elif system == "Darwin":  # macOS
        print("[*] Detected macOS - Installing via Homebrew...")
        
        try:
            subprocess.run(["brew", "--version"], capture_output=True, timeout=5)
            brew_available = True
        except:
            brew_available = False
        
        if brew_available:
            scrcpy_installed = run_command("brew install scrcpy", "Installing scrcpy via Homebrew")
        else:
            print("[!] Homebrew not found. Installing Homebrew first...")
            if run_command('/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"', "Installing Homebrew"):
                scrcpy_installed = run_command("brew install scrcpy", "Installing scrcpy via Homebrew")
        
        if not scrcpy_installed:
            print("\n[!] Could not auto-install scrcpy. Manual:")
            print("    brew install scrcpy")
    
    elif system == "Linux":
        print("[*] Detected Linux - Installing via apt...")
        
        if run_command("sudo apt update", "Updating apt cache"):
            scrcpy_installed = run_command("sudo apt install -y scrcpy", "Installing scrcpy via apt")
        
        if not scrcpy_installed:
            print("\n[!] Could not auto-install scrcpy. Manual:")
            print("    sudo apt install scrcpy")
    
    # Step 3: Install ADB
    print_header("Step 3: Installing Android Debug Bridge (ADB)")
    
    adb_installed = False
    
    try:
        result = subprocess.run(["adb", "version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("[✓] ADB is already installed!")
            adb_installed = True
    except:
        pass
    
    if not adb_installed:
        if system == "Windows":
            print("[!] ADB not found. Manual installation options:")
            print("    Option 1: Download Android Studio and SDK Platform Tools")
            print("             https://developer.android.com/studio/releases/platform-tools")
            print("    Option 2: choco install android-sdk")
            print("    Option 3: scoop install adb")
        
        elif system == "Darwin":
            print("[*] Installing ADB via Homebrew...")
            adb_installed = run_command("brew install android-platform-tools", "Installing ADB via Homebrew")
            
            if not adb_installed:
                print("[!] Manual installation:")
                print("    brew install android-platform-tools")
        
        elif system == "Linux":
            print("[*] Installing ADB via apt...")
            if run_command("sudo apt update", "Updating apt cache"):
                adb_installed = run_command("sudo apt install -y android-tools-adb", "Installing ADB via apt")
    
    # Final summary
    print_header("SETUP SUMMARY")
    
    print("\n[✓] Setup Process Completed!")
    print("\nNow you can run V Scanner with:")
    print("  python main.py")
    print("\nMake sure to:")
    print("  1. Connect your Android device via USB")
    print("  2. Enable USB Debugging on your device")
    print("  3. Allow USB file transfer when prompted on the device")
    print("\nFor more information, see README.md")
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!] Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[✗] Setup failed with error: {str(e)}")
        sys.exit(1)
