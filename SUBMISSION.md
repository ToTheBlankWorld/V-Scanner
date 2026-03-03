<p align="center">
  <img src="https://img.shields.io/badge/V--Scanner-Mobile%20Security%20Suite-blueviolet?style=for-the-badge&logo=android" alt="V-Scanner Badge"/>
</p>

<h1 align="center">V-Scanner — Mobile App Vulnerability Scanner</h1>

<p align="center">
  <b>A cross-platform security toolkit (Android App + CLI) that scans installed apps for vulnerabilities, monitors real-time sensor access, and generates actionable security reports.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Android%20%7C%20CLI-green?style=flat-square" />
  <img src="https://img.shields.io/badge/Language-Kotlin%20%7C%20Python-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/Android%20SDK-26--35-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" />
</p>

---

## Table of Contents

| # | Section |
|---|---------|
| 1 | [Problem Understanding](#1-problem-understanding) |
| 2 | [Key Challenges](#2-key-challenges) |
| 3 | [Proposed Solution & Technical Approach](#3-proposed-solution--technical-approach) |
| 4 | [System Architecture](#4-system-architecture) |
| 5 | [Technology Stack](#5-technology-stack) |
| 6 | [Feature Breakdown](#6-feature-breakdown) |
| 7 | [Risk Scoring Algorithm — Deep Dive](#7-risk-scoring-algorithm--deep-dive) |
| 8 | [Privacy Guardian — Real-Time Sensor Monitoring](#8-privacy-guardian--real-time-sensor-monitoring) |
| 9 | [Permission Intelligence Database](#9-permission-intelligence-database) |
| 10 | [Innovative Features & Unique Angles](#10-innovative-features--unique-angles) |
| 11 | [Screenshots & Demo](#11-screenshots--demo) |
| 12 | [Installation & Setup](#12-installation--setup) |
| 13 | [Project Structure](#13-project-structure) |
| 14 | [Future Scope](#14-future-scope) |
| 15 | [Team & Repository](#15-team--repository) |

---

## 1. Problem Understanding

Modern Android devices contain **200+ installed apps** on average, each requesting a varying set of permissions. Users grant these permissions without fully understanding the privacy implications. The core problems are:

- **Permission Overreach** — Many apps request permissions far beyond their functional needs (e.g., a flashlight app requesting SMS and contacts access).
- **Outdated SDKs** — Apps targeting older Android SDKs bypass critical security features like runtime permissions (pre-Android 6.0) and background access restrictions.
- **Insecure Hardcoded Data** — Some APKs contain hardcoded HTTP URLs, API keys, Firebase credentials, and AWS secrets — making them vulnerable to interception and credential theft.
- **Silent Sensor Access** — Apps can access the camera, microphone, and GPS in the background without the user's knowledge, creating serious privacy violations.
- **No Centralized Visibility** — Android provides no single view for users to understand the combined security posture of all their installed apps.

**V-Scanner addresses all five problems** through a dual-platform approach: a native Android app for on-device scanning and real-time monitoring, and a Python CLI tool for remote forensic analysis via ADB.

---

## 2. Key Challenges

| Challenge | Description | Our Approach |
|-----------|-------------|--------------|
| **False Positives** | Legitimate apps (WhatsApp, Google Maps) naturally require many permissions. A naive scoring system would flag them as high-risk. | **Trust-based risk normalization** — Apps verified from Play Store get a 35% risk reduction; known trusted packages get an additional 30% reduction; system apps get 50% reduction. |
| **Sensor Access Detection** | `AppOpsManager.checkOpNoThrow()` only checks if a permission *policy* allows access—it doesn't detect *actual* sensor usage. | **Usage-time correlation** — We cross-reference `UsageStatsManager` events with permission grants and foreground/background state to identify actual sensor access patterns. |
| **Background Monitoring Battery Impact** | Continuously polling sensors drains the battery. | **Optimized 5-second polling intervals** with `PowerManager` integration — monitoring automatically adjusts based on screen state. The service runs as a lightweight foreground service with minimal wake locks. |
| **API Compatibility (SDK 26–35)** | Android APIs change across 10 major versions. `getInstallerPackageName()` is deprecated; `getInstallSourceInfo()` is API 30+. | **Dual-path API calls** with version checks — we use the modern API when available and gracefully degrade on older devices. |
| **Permission Complexity** | Android has 200+ permissions; categorizing and risk-weighting them requires domain expertise. | **Curated database of 28 dangerous permissions** across 11 categories, each with expert-assigned risk levels, human-readable descriptions, threat explanations, and secure alternative recommendations. |
| **Sideloaded App Detection** | Sideloaded apps bypass Play Store's safety checks and are inherently riskier. | **Multi-store installer verification** — We query the installer source (Play Store, Samsung Galaxy Store, Amazon Appstore, Huawei AppGallery) and flag apps from unknown sources. |

---

## 3. Proposed Solution & Technical Approach

V-Scanner is a **complete mobile security assessment platform** with two execution modes:

### 3.1 Native Android App (On-Device)

A Material3 Android application that runs directly on the device and provides:

- **One-tap full device scan** — Scans all installed apps, analyzes permissions, calculates risk scores, and generates a sortable/filterable security report.
- **Privacy Guardian** — A persistent foreground service that monitors camera, microphone, and location access in real-time, detects suspicious patterns (background access, screen-off access, excessive frequency), and pushes instant notifications.
- **Security Dashboard** — A at-a-glance view of the device's overall security posture with risk distribution, active alerts, and sensor usage trends.
- **Actionable Intelligence** — Each flagged permission includes a human-readable explanation of why it's dangerous, what the real-world risk is, and what the secure alternative is.

### 3.2 Python CLI Tool (Remote via ADB)

A cross-platform terminal tool for security researchers and power users:

- **Remote app scanning** — List, analyze, and report on apps installed on a connected Android device over ADB.
- **Live sensor monitoring** — Continuously poll `dumpsys camera|audio|location` to detect real-time hardware access.
- **APK binary analysis** — Grep APK files for insecure URLs, hardcoded credentials, API keys, Firebase config, and AWS secrets.
- **Report generation** — Export findings as interactive HTML reports, structured JSON, or formatted terminal output.
- **Device administration** — Uninstall apps, force-stop processes, gather full device info, and mirror the screen via `scrcpy`.

### 3.3 Why Two Platforms?

| Aspect | Android App | CLI Tool |
|--------|-------------|----------|
| User | Everyday users | Security researchers |
| Access | On-device, no setup | Remote via ADB |
| Real-time | Yes (foreground service) | Yes (polling `dumpsys`) |
| Reporting | In-app UI | HTML / JSON / Text |
| Sensor Monitoring | Background Guardian | Live terminal feed |
| Device Admin | No | Yes (uninstall, force-stop) |

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      V-SCANNER PLATFORM                         │
├────────────────────────────┬────────────────────────────────────┤
│      ANDROID APP           │          CLI TOOL                  │
│   (On-Device Scanning)     │     (Remote via ADB)               │
│                            │                                    │
│  ┌──────────────────────┐  │  ┌──────────────────────────────┐  │
│  │    Jetpack Compose    │  │  │     Rich Terminal UI         │  │
│  │  Material3 Dark UI    │  │  │   GEMINI-Inspired Design     │  │
│  └──────────┬───────────┘  │  └──────────────┬───────────────┘  │
│             │              │                 │                   │
│  ┌──────────▼───────────┐  │  ┌──────────────▼───────────────┐  │
│  │    MVVM ViewModels    │  │  │   Click CLI Framework        │  │
│  │  (StateFlow / Hilt)   │  │  │   Interactive Menu System    │  │
│  └──────────┬───────────┘  │  └──────────────┬───────────────┘  │
│             │              │                 │                   │
│  ┌──────────▼───────────┐  │  ┌──────────────▼───────────────┐  │
│  │   AppScanner Engine   │  │  │   ADBInterface Scanner       │  │
│  │  PermissionDatabase   │  │  │   permissions.py Analyzer    │  │
│  │  Risk Scoring Engine  │  │  │   APK Binary Scanner         │  │
│  └──────────┬───────────┘  │  └──────────────┬───────────────┘  │
│             │              │                 │                   │
│  ┌──────────▼───────────┐  │  ┌──────────────▼───────────────┐  │
│  │  Privacy Guardian     │  │  │   dumpsys Sensor Monitor     │  │
│  │  Service (Foreground) │  │  │   Live Camera/Mic/GPS Feed   │  │
│  │  5-sec Polling Loop   │  │  │   2-sec Polling Loop         │  │
│  └──────────┬───────────┘  │  └──────────────┬───────────────┘  │
│             │              │                 │                   │
│  ┌──────────▼───────────┐  │  ┌──────────────▼───────────────┐  │
│  │   Room Database v2    │  │  │   Jinja2 HTML Reports        │  │
│  │   DataStore Prefs     │  │  │   JSON / Text Export         │  │
│  │   5 Tables, 5 DAOs    │  │  │   Console Rich Tables        │  │
│  └──────────────────────┘  │  └──────────────────────────────┘  │
│                            │                                    │
│  ◆ PackageManager API      │  ◆ ADB Shell Commands              │
│  ◆ AppOpsManager API       │  ◆ dumpsys (camera, audio, GPS)    │
│  ◆ UsageStatsManager API   │  ◆ pm list packages                │
│  ◆ PowerManager API        │  ◆ APK binary grep                 │
└────────────────────────────┴────────────────────────────────────┘
```

### Android App — Internal Architecture (Clean MVVM)

```
┌─────────────────────────────────────────────────┐
│                 UI Layer                         │
│   DashboardScreen  ScannerScreen  GuardianScreen │
│   AlertsScreen     SettingsScreen                │
└──────────────────────┬──────────────────────────┘
                       │ Observes StateFlow
┌──────────────────────▼──────────────────────────┐
│              ViewModel Layer                     │
│  DashboardVM  ScannerVM  GuardianVM  AlertsVM   │
│  SettingsVM    (@HiltViewModel / Inject)         │
└──────────────────────┬──────────────────────────┘
                       │ Calls suspend functions
┌──────────────────────▼──────────────────────────┐
│            Repository Layer                      │
│    ScannerRepository    GuardianRepository       │
└──────────────────────┬──────────────────────────┘
                       │ Room DAO queries
┌──────────────────────▼──────────────────────────┐
│              Data Layer                          │
│   VScannerDatabase (Room v2) + DataStore Prefs   │
│   5 Entities │ 5 DAOs │ 16 Preference Keys       │
└─────────────────────────────────────────────────┘
```

---

## 5. Technology Stack

### Android Application

| Technology | Version | Purpose |
|:-----------|:--------|:--------|
| **Kotlin** | 1.9.20 | Primary language with coroutines & Flow |
| **Jetpack Compose** | BOM 2023.10.01 | Declarative UI framework |
| **Material3** | BOM-managed | Design system with dynamic colors |
| **Dagger Hilt** | 2.48 | Compile-time dependency injection |
| **Room** | 2.6.1 | Local SQLite ORM with Flow-based queries |
| **Jetpack DataStore** | 1.0.0 | Type-safe preferences storage |
| **Navigation Compose** | 2.7.5 | Screen routing & bottom navigation |
| **WorkManager** | 2.9.0 | Reliable background task scheduling |
| **Vico Charts** | 1.13.0 | 7-day usage trend visualization |
| **Coroutines** | 1.7.3 | Structured concurrency |
| **Gson** | 2.10.1 | JSON serialization for Room converters |
| **Android SDK** | 26–35 | Supports Android 8.0 to Android 15 |

### CLI Tool

| Technology | Version | Purpose |
|:-----------|:--------|:--------|
| **Python** | 3.x | Runtime |
| **Rich** | ≥13.0.0 | Terminal tables, panels, progress bars |
| **Click** | ≥8.0.0 | CLI argument parsing |
| **Jinja2** | ≥3.0.0 | HTML report templating |
| **adb-shell** | ≥0.4.3 | Python ADB bridge |
| **scrcpy** | External | Real-time screen mirroring |

### Build & Infrastructure

| Tool | Version |
|:-----|:--------|
| **Gradle** | 8.2 |
| **Android Gradle Plugin** | 8.2.0 |
| **JDK** | 17 (Android Studio JBR) |
| **ProGuard/R8** | Enabled for release builds |
| **Git** | Version control |

---

## 6. Feature Breakdown

### 6.1 Android App — 5 Core Screens

#### Dashboard
> The central security overview — at a glance, users understand their device's security posture.

- **Overall Security Score** (0–100) with color-coded gauge
- **Quick Stats Strip**: Apps Scanned · High Risk Apps · Alerts Today · Guardian Status
- **Today's Sensor Usage**: Camera, Microphone, Location, Background access counts
- **Recent Alerts**: Last 3 privacy alerts with sensor icons
- **High Risk Apps**: Top 5 apps by risk score
- **Quick Actions**: Scan Now button, Guardian toggle

<!-- 📸 SCREENSHOT: Dashboard Screen -->
> **[SCREENSHOT PLACEHOLDER — Dashboard Screen: Show the main dashboard with security score, stats cards, and recent alerts]**

---

#### Scanner
> Scans all installed apps and produces a detailed security assessment with color-coded risk scores.

- **One-tap scan** with real-time progress bar and per-app status
- **Risk-categorized app list** (sorted by score descending)
- **Filter chips**: All / Critical / High / Medium / Low
- **Per-app card** shows:
  - Color-coded risk score badge (0–100)
  - App name with **✅ Play Store verified blue tick** for verified apps
  - Total permissions count + dangerous permissions count
- **Detailed bottom sheet** (tap any app):
  - Risk level breakdown with circular progress indicator
  - SDK information (Target SDK, Min SDK)
  - **Installer source** (Google Play Store / Samsung Galaxy Store / Unknown / Pre-installed)
  - Install date and last update date
  - Dangerous permissions grouped by category with risk badges
  - Per-permission: description, risks, and mitigation recommendations
  - Safe permissions summary count

<!-- 📸 SCREENSHOT: Scanner Screen — App List -->
> **[SCREENSHOT PLACEHOLDER — Scanner Screen: Show the app list with risk scores, filter chips, and the Play Store verified blue tick on apps]**

<!-- 📸 SCREENSHOT: Scanner Screen — App Detail Bottom Sheet -->
> **[SCREENSHOT PLACEHOLDER — App Detail Bottom Sheet: Show the expanded detail view with risk score, permissions grouped by category, installer source info]**

---

#### Privacy Guardian
> Real-time sensor monitoring service that detects and alerts on suspicious app behavior.

- **Master toggle** to enable/disable Guardian service
- **Per-sensor toggles**: Camera · Microphone · Location
- **Alert condition toggles**: Background Access · Screen-Off Access · Frequent Access
- **Recently Active Apps** section with per-sensor access counts
- **7-Day Sensor Usage Trend** chart (Vico bar chart)
- **Daily Summary** cards

<!-- 📸 SCREENSHOT: Guardian Screen -->
> **[SCREENSHOT PLACEHOLDER — Guardian Screen: Show the Guardian controls with toggles, recently active apps section, and 7-day usage chart]**

---

#### Alerts
> Chronological list of all privacy alerts triggered by the Guardian service.

- **Unread count** badge in header
- **Sensor type filter chips**: Camera / Microphone / Location
- **Alert cards** with: sensor icon + color, app name, alert message, relative timestamp, alert type badge (Background / Frequent / Screen-Off / Suspicious)
- **Dismiss individual alerts** or **Clear All**
- **Empty state** with green checkmark when no alerts exist

<!-- 📸 SCREENSHOT: Alerts Screen -->
> **[SCREENSHOT PLACEHOLDER — Alerts Screen: Show alert cards with different sensor types and alert badges]**

---

#### Settings
> Full configuration control for scanner behavior, Guardian tuning, data management, and appearance.

- **Permissions Section**: Usage Access and Notification permission status with Grant buttons (status **updates live** when returning from system settings)
- **Scanner**: Include System Apps toggle
- **Privacy Guardian**: Enable Guardian, Start on Boot toggles
- **Alert Threshold**: Configurable slider (5–50 per hour)
- **Data Management**: Clear Scan History / Clear Sensor Logs / Clear All Alerts (with confirmation dialogs)
- **Appearance**: Dark / Light theme toggle
- **About**: Version info

<!-- 📸 SCREENSHOT: Settings Screen -->
> **[SCREENSHOT PLACEHOLDER — Settings Screen: Show the settings sections with permission status, toggles, and threshold slider]**

---

### 6.2 CLI Tool — Key Features

| Feature | Description |
|:--------|:------------|
| **List All Apps** | Enumerate installed packages with intelligent name resolution |
| **Single App Analysis** | Deep-dive: permissions, SDK risk, insecure URL detection |
| **Full Device Scan** | Batch analyze all apps with configurable depth |
| **Live Sensor Monitor** | Real-time camera/mic/GPS usage feed (2-sec refresh) |
| **Hardware Sensor Values** | CPU-Z style: accelerometer, gyroscope, magnetometer, proximity, light, barometer |
| **Full Device Info** | Hardware, System, Memory, Network, Identifiers, Build info panels |
| **APK Binary Analysis** | Detect insecure HTTP URLs, hardcoded API keys, Firebase config, AWS credentials |
| **HTML Report Export** | Dark-themed interactive HTML reports with expandable app cards and risk meters |
| **JSON/Text Export** | Machine-readable output for CI/CD integration |
| **Screen Mirroring** | Live screen share via `scrcpy` with mouse/keyboard |
| **App Administration** | Uninstall, force-stop, launch apps remotely |

<!-- 📸 SCREENSHOT: CLI — Main Menu -->
> **[SCREENSHOT PLACEHOLDER — CLI Main Menu: Show the GEMINI-inspired terminal UI with the main interactive menu]**

<!-- 📸 SCREENSHOT: CLI — Full Device Scan Results -->
> **[SCREENSHOT PLACEHOLDER — CLI Scan Results: Show a scan in progress or completed scan with colored risk tables]**

<!-- 📸 SCREENSHOT: CLI — Live Sensor Monitor -->
> **[SCREENSHOT PLACEHOLDER — CLI Sensor Monitor: Show the real-time sensor monitoring feed with active app detection]**

<!-- 📸 SCREENSHOT: CLI — HTML Report -->
> **[SCREENSHOT PLACEHOLDER — CLI HTML Report: Show the generated dark-themed HTML report with app cards and risk meters]**

---

## 7. Risk Scoring Algorithm — Deep Dive

Our risk scoring algorithm avoids the **false-positive trap** where legitimate apps like WhatsApp or Google Maps would score as "Critical" simply because they require many permissions.

### Scoring Pipeline

```
Step 1: Permission Weight Accumulation
─────────────────────────────────────
For each dangerous permission found:
  CRITICAL permission → +12 points
  HIGH     permission → +7  points
  MEDIUM   permission → +3  points
  LOW      permission → +1  point
  INFO     permission → +0  points

Step 2: Normalization (Prevents Inflation)
─────────────────────────────────────────
  average_weight = raw_score / number_of_dangerous_permissions
  normalized_score = average_weight × 5     (max ~60 from averages)

Step 3: Critical Permission Bonus
─────────────────────────────────
  score += critical_permission_count × 8    (SMS, background location, overlay)

Step 4: SDK Age Penalty
───────────────────────
  targetSdk < 23 (pre-Marshmallow) → +15   (no runtime permissions!)
  targetSdk < 26 (pre-Oreo)        → +8
  targetSdk < 28 (pre-Pie)         → +3

Step 5: Trust Reduction ★ (Unique to V-Scanner)
────────────────────────────────────────────────
  Play Store verified   → score × 0.65  (35% reduction)
  Known trusted package → score × 0.70  (30% reduction)
  System app            → score × 0.50  (50% reduction)

Step 6: Classification
──────────────────────
  ≥ 70 → CRITICAL (Red)
  ≥ 50 → HIGH     (Orange)
  ≥ 25 → MEDIUM   (Yellow)
  ≥ 8  → LOW      (Green)
  < 8  → INFO     (Blue)
```

### Why This Works

| Scenario | Naive Approach | V-Scanner |
|:---------|:---------------|:----------|
| WhatsApp (Camera + Mic + Location + Contacts + Storage) | Score: 53 → HIGH ❌ | Score: 15 → LOW ✅ (Play Store + trusted package reductions) |
| Random sideloaded app with SMS + Overlay + Background Location | Score: 75 → CRITICAL | Score: 82 → CRITICAL ✅ (no trust reduction, CRITICAL bonuses) |
| Google Maps (Fine Location + Coarse Location + Camera) | Score: 30 → MEDIUM ❌ | Score: 8 → LOW ✅ (Play Store + Google package reductions) |
| Sideloaded flashlight with SMS + Contacts + Phone | Score: 48 → MEDIUM | Score: 62 → HIGH ✅ (no trust, suspicious permission combo) |

### Multi-Store Installer Detection

V-Scanner doesn't just check Google Play — it identifies installers from **5 app stores**:

| Installer Package | Store Name |
|:------------------|:-----------|
| `com.android.vending` | Google Play Store |
| `com.sec.android.app.samsungapps` | Samsung Galaxy Store |
| `com.amazon.venezia` | Amazon Appstore |
| `com.huawei.appmarket` | Huawei AppGallery |
| `null` (system app) | Pre-installed |
| Any other / `null` | Unknown (flagged) |

---

## 8. Privacy Guardian — Real-Time Sensor Monitoring

### How It Works

```
┌───────────────────────────────────────────────┐
│         PrivacyGuardianService                │
│         (Foreground Service)                  │
│                                               │
│  ┌─────────────────────────────────────────┐  │
│  │  Every 5 seconds:                       │  │
│  │                                         │  │
│  │  1. Check: Is screen on or off?         │  │
│  │     └─ PowerManager.isInteractive       │  │
│  │                                         │  │
│  │  2. Identify foreground app             │  │
│  │     └─ UsageStatsManager.queryEvents    │  │
│  │                                         │  │
│  │  3. For each sensor (Camera/Mic/GPS):   │  │
│  │     └─ Is monitoring enabled? (prefs)   │  │
│  │     └─ AppOpsManager: who has access?   │  │
│  │     └─ Cross-ref with recent activity   │  │
│  │     └─ Is app in background?            │  │
│  │     └─ Is screen off?                   │  │
│  │     └─ Is access frequency suspicious?  │  │
│  │                                         │  │
│  │  4. If suspicious → Log + Alert         │  │
│  │     └─ Insert SensorAccessLog (Room)    │  │
│  │     └─ Insert PrivacyAlert (Room)       │  │
│  │     └─ Push notification (high priority)│  │
│  │     └─ Update DailySensorSummary        │  │
│  └─────────────────────────────────────────┘  │
│                                               │
│  Settings synced live from DataStore:         │
│  • monitorCamera / monitorMicrophone          │
│  • monitorLocation / alertOnBackground        │
│  • alertOnScreenOff / alertOnFrequent         │
│  • frequentThreshold / whitelistedApps        │
└───────────────────────────────────────────────┘
```

### Alert Types

| Alert Type | Trigger Condition | Severity |
|:-----------|:------------------|:---------|
| `BACKGROUND_SENSOR_ACCESS` | App accesses sensor while not in foreground | High |
| `SCREEN_OFF_ACCESS` | App accesses sensor while screen is off | Critical |
| `FREQUENT_ACCESS` | App exceeds threshold (default: 10/hour) per sensor | Medium |
| `SUSPICIOUS_PATTERN` | Combination of background + screen-off + frequent | Critical |

### Notifications

Each alert pushes a high-priority notification with:
- Sensor-specific emoji (📷 Camera / 🎤 Microphone / 📍 Location)
- App name and alert description
- Tap-to-open action launching the Alerts screen

### Boot Persistence

The `BootReceiver` listens for both `BOOT_COMPLETED` and `QUICKBOOT_POWERON` intents, reads the Guardian preference, and auto-starts the service if it was previously enabled.

---

## 9. Permission Intelligence Database

V-Scanner maintains a curated database of **28 dangerous Android permissions** across **11 categories**.

Each entry contains:
- **Risk Level** (CRITICAL / HIGH / MEDIUM / LOW / INFO)
- **Human-Readable Name** (e.g., "Read SMS" instead of `android.permission.READ_SMS`)
- **Plain-English Description** of what the permission allows
- **Real-World Risks** — What can go wrong (e.g., "Can read OTP/2FA codes", "Unauthorized SMS charges")
- **Recommended Mitigations** — What the user should do
- **Secure Alternatives** — What the developer should have used instead

### Permission Categories

| Category | Permissions Tracked | Highest Risk |
|:---------|:-------------------|:-------------|
| **SMS** | READ_SMS, SEND_SMS, RECEIVE_SMS | 🔴 CRITICAL |
| **Location** | FINE_LOCATION, COARSE_LOCATION, BACKGROUND_LOCATION | 🔴 CRITICAL |
| **Storage** | READ_STORAGE, WRITE_STORAGE, MANAGE_ALL_FILES | 🔴 CRITICAL |
| **Special** | SYSTEM_ALERT_WINDOW, REQUEST_INSTALL_PACKAGES | 🔴 CRITICAL |
| **Camera** | CAMERA | 🟠 HIGH |
| **Microphone** | RECORD_AUDIO | 🟠 HIGH |
| **Contacts** | READ_CONTACTS, WRITE_CONTACTS, GET_ACCOUNTS | 🟠 HIGH |
| **Phone** | READ_PHONE_STATE, CALL_PHONE, READ/WRITE_CALL_LOG, PROCESS_OUTGOING_CALLS | 🟠 HIGH |
| **Calendar** | READ_CALENDAR, WRITE_CALENDAR | 🟡 MEDIUM |
| **Sensors** | BODY_SENSORS, ACTIVITY_RECOGNITION | 🟡 MEDIUM |
| **Network** | INTERNET, ACCESS_WIFI_STATE | 🟢 LOW |

---

## 10. Innovative Features & Unique Angles

### ✅ Play Store Verified Badge (Blue Tick)

**This is a standout feature.** In the Scanner screen, every app installed from the Google Play Store displays a **verified blue checkmark** (✅) next to its name — similar to social media verification badges.

This instantly communicates trust to users:
- **Blue tick present** → App came from a verified store → Lower risk
- **No blue tick** → App was sideloaded or from an unknown source → Higher scrutiny needed

The verification extends beyond just Google Play — we detect **5 different app stores** and display the installer source in the app detail sheet.

<!-- 📸 SCREENSHOT: Play Store Verified Badge Close-up -->
> **[SCREENSHOT PLACEHOLDER — Blue Tick Feature: Show a close-up of the scanner app list with the verified blue tick visible next to Play Store apps, and absent on sideloaded apps]**

---

### Other Innovative Features

| Feature | Innovation |
|:--------|:-----------|
| **Trust-Based Risk Normalization** | Unlike static scoring, our algorithm considers the *source* of the app. A banking app from Play Store with many permissions scores differently than an unknown app with the same permissions. |
| **Zero Network Architecture** | V-Scanner makes **zero network calls**. All analysis, logging, and reporting happens 100% on-device. No data ever leaves the phone — true privacy-first design. |
| **Screen-Off Sensor Detection** | We flag apps accessing camera/microphone/GPS when the screen is off — a strong indicator of surveillance or spyware behavior. |
| **Frequency-Based Anomaly Detection** | Configurable threshold (5–50/hour) detects apps that access sensors obsessively, even if each individual access seems benign. |
| **Boot-Persistent Guardian** | Guardian service survives device reboots via `BOOT_COMPLETED` receiver — continuous protection without user intervention. |
| **Cross-Platform Parity** | Both CLI and Android app perform the same core analysis, ensuring consistent results regardless of the tool used. |
| **APK Binary Scanning (CLI)** | The CLI tool doesn't just check permissions — it scans APK binaries for hardcoded secrets: HTTP URLs, API keys, Firebase credentials, AWS access keys. |
| **Live Sensor Feed (CLI)** | Real-time 2-second polling of `dumpsys camera`, `dumpsys audio`, and `dumpsys location` with process identification — shows exactly which app is using which sensor *right now*. |
| **Smart App Name Resolution (CLI)** | Intelligent package-name-to-human-name parser with a 20+ entry cache for popular apps, handling edge cases like `com.google.android.apps.*` and `com.samsung.*` patterns. |
| **Dark-Themed HTML Reports (CLI)** | Generated reports use a modern dark UI with CSS grid, expandable cards, risk meters, and color-coded badges — not just raw text dumps. |

---

## 11. Screenshots & Demo

### Android App Screenshots

| Screen | Description |
|:-------|:------------|
| **Dashboard** | Security overview with score gauge, stats, alerts, and sensor usage |
| **Scanner — App List** | Color-coded risk scores, Play Store verified badges, permission counts |
| **Scanner — App Detail** | Full security breakdown with permissions categorized and recommendations |
| **Guardian** | Real-time sensor toggles, active apps, 7-day usage trend chart |
| **Alerts** | Privacy alert cards with sensor filters and dismiss actions |
| **Settings** | Live permission status, Guardian config, data management, theme toggle |

<!-- 📸 SCREENSHOTS: Android App (All 6 Screens) -->

> **[SCREENSHOT PLACEHOLDER — Dashboard Screen]**
>
> *The main dashboard showing overall security score, quick stats (apps scanned, high risk, alerts today), recent alerts, and today's sensor usage breakdown.*

---

> **[SCREENSHOT PLACEHOLDER — Scanner Screen with Verified Badges]**
>
> *The scanner results showing color-coded risk scores (green/yellow/orange/red), the Play Store verified blue tick on trusted apps, and filter chips for Critical/High/Medium/Low.*

---

> **[SCREENSHOT PLACEHOLDER — App Detail Bottom Sheet]**
>
> *Expanded app detail showing: risk score gauge, installer source ("Google Play Store"), SDK info, total vs risky permission counts, dangerous permissions grouped by category, and the green "safe permissions" summary at the bottom.*

---

> **[SCREENSHOT PLACEHOLDER — Guardian Screen]**
>
> *Privacy Guardian controls with master toggle, per-sensor toggles (Camera/Mic/Location), alert condition toggles, recently active apps section, and the 7-day sensor usage bar chart.*

---

> **[SCREENSHOT PLACEHOLDER — Alerts Screen]**
>
> *Alert cards showing different alert types: Background Camera Access (red), Frequent Microphone Access (orange), Screen-Off Location Access (purple), with sensor filter chips at the top.*

---

> **[SCREENSHOT PLACEHOLDER — Settings Screen]**
>
> *Full settings view with: Usage Access permission (granted/green checkmark), Notification permission status, Include System Apps toggle, Guardian toggles, alert threshold slider, data management section, and Dark Theme toggle.*

---

### CLI Tool Screenshots

> **[SCREENSHOT PLACEHOLDER — CLI Main Menu]**
>
> *The GEMINI-inspired terminal UI with gradient banner, device info panel, and the 11-option interactive menu.*

---

> **[SCREENSHOT PLACEHOLDER — CLI App Scan Results]**
>
> *Full device scan output showing color-coded risk table with app names, permission counts, risk levels, and SDK versions.*

---

> **[SCREENSHOT PLACEHOLDER — CLI Live Sensor Monitor]**
>
> *Real-time sensor monitoring feed showing Camera (idle/active), Microphone (active by "com.example.app"), and GPS (active) with 2-second refresh.*

---

> **[SCREENSHOT PLACEHOLDER — CLI HTML Report]**
>
> *The generated dark-themed HTML report showing expandable app cards with risk meters, permission breakdowns, and color-coded badges.*

---

> **[SCREENSHOT PLACEHOLDER — CLI Device Info]**
>
> *Full device information panels: Hardware, System, Memory, Network, Identifiers, Build.*

---

## 12. Installation & Setup

### Android App

```bash
# Clone the repository
git clone https://github.com/ToTheBlankWorld/V-Scanner.git
cd V-Scanner/android

# Build the debug APK
./gradlew assembleDebug

# Install on connected device
adb install app/build/outputs/apk/debug/app-debug.apk
```

Or use the **pre-built APK**: `VScanner-debug.apk` (16.3 MB) available in the repository root.

### CLI Tool

```bash
cd V-Scanner/cli

# Install Python dependencies
pip install -r requirements.txt

# Run the setup wizard
python setup.py

# Launch V-Scanner CLI
python main.py
```

### Requirements

| Component | Requirement |
|:----------|:------------|
| Android Device | Android 8.0+ (API 26+) |
| Android Build | JDK 17, Android SDK 35 |
| CLI | Python 3.8+, ADB installed |
| Device Connection | USB debugging enabled OR wireless ADB |

---

## 13. Project Structure

```
V-Scanner/
├── android/                          # Native Android Application
│   ├── app/
│   │   ├── build.gradle              # Dependencies & build config
│   │   ├── proguard-rules.pro        # R8/ProGuard rules
│   │   └── src/main/
│   │       ├── AndroidManifest.xml   # Permissions & components
│   │       ├── java/com/vsecurity/scanner/
│   │       │   ├── VScannerApplication.kt    # Hilt app entry
│   │       │   ├── scanner/
│   │       │   │   ├── AppScanner.kt         # Core scanning engine
│   │       │   │   └── PermissionDatabase.kt # 28 dangerous perms DB
│   │       │   ├── guardian/
│   │       │   │   ├── PrivacyGuardianService.kt  # Foreground monitor
│   │       │   │   └── BootReceiver.kt            # Boot persistence
│   │       │   ├── data/
│   │       │   │   ├── local/Database.kt          # Room DB v2 + DAOs
│   │       │   │   ├── model/AppModels.kt         # App entities
│   │       │   │   ├── model/GuardianModels.kt    # Sensor entities
│   │       │   │   ├── preferences/PreferencesManager.kt  # DataStore
│   │       │   │   └── repository/Repositories.kt # Data repos
│   │       │   ├── di/AppModule.kt               # Hilt DI module
│   │       │   └── ui/
│   │       │       ├── MainActivity.kt            # Single Activity
│   │       │       ├── navigation/Navigation.kt   # 5-tab bottom nav
│   │       │       ├── theme/Theme.kt             # Material3 theme
│   │       │       ├── screens/
│   │       │       │   ├── DashboardScreen.kt     # Security overview
│   │       │       │   ├── ScannerScreen.kt       # App scanner UI
│   │       │       │   ├── GuardianScreen.kt      # Sensor monitor
│   │       │       │   ├── AlertsScreen.kt        # Privacy alerts
│   │       │       │   └── SettingsScreen.kt      # Configuration
│   │       │       └── viewmodel/
│   │       │           ├── DashboardViewModel.kt
│   │       │           ├── ScannerViewModel.kt
│   │       │           ├── GuardianViewModel.kt
│   │       │           ├── AlertsViewModel.kt
│   │       │           └── SettingsViewModel.kt
│   │       └── res/
│   │           ├── drawable/          # Vector icons
│   │           ├── values/            # Colors, strings, themes
│   │           └── xml/               # Backup rules
│   ├── build.gradle                   # Root build config
│   ├── settings.gradle                # Project settings
│   └── gradle.properties              # JVM & build flags
│
├── cli/                              # Python CLI Tool
│   ├── main.py                       # Interactive menu (1532 lines)
│   ├── scanner.py                    # ADB interface (1876 lines)
│   ├── permissions.py                # Permission analyzer (679 lines)
│   ├── report_generator.py           # HTML/JSON reports (617 lines)
│   ├── ui_styles.py                  # Terminal UI (317 lines)
│   ├── setup.py                      # Cross-platform installer
│   ├── adb_setup.py                  # ADB path config
│   └── requirements.txt              # Python dependencies
│
├── docs/                             # Documentation
│   ├── ARCHITECTURE.md
│   ├── USAGE.md
│   └── ...
│
├── VScanner-debug.apk               # Pre-built debug APK (16.3 MB)
├── SUBMISSION.md                     # ← This document
└── README.md                         # Project README
```

---

## 14. Future Scope

| Enhancement | Description | Impact |
|:------------|:------------|:-------|
| **Network Traffic Analysis** | Monitor real-time DNS queries and HTTP/HTTPS connections per app | Detect data exfiltration, tracking domains, C2 communication |
| **ML-Based Anomaly Detection** | Train a model on normal sensor access patterns, flag deviations | Reduce false positives, catch novel spyware behavior |
| **Google Safe Browsing API** | Cross-reference app-embedded URLs against Google's threat database | Identify known phishing/malware domains in APKs |
| **VirusTotal Integration** | Submit APK hashes to VirusTotal for multi-engine malware scanning | Leverage 70+ AV engines for known-malware detection |
| **Permission Timeline** | Track how an app's permissions change across updates | Detect permission creep (app gradually requesting more permissions) |
| **Export & Share Reports** | PDF/HTML export from the Android app + share-to-email | Enable organizational security audits |
| **Multi-Device Dashboard** | CLI tool aggregating security posture across multiple managed devices | Enterprise fleet management use case |
| **iOS Support** | Extend CLI to scan iOS devices via `libimobiledevice` | Cross-platform organizational security |

---

## 15. Team & Repository

### GitHub Repository

🔗 **[https://github.com/ToTheBlankWorld/V-Scanner](https://github.com/ToTheBlankWorld/V-Scanner)**

### Quick Stats

| Metric | Value |
|:-------|:------|
| Total Source Files | 35+ |
| Lines of Code (CLI) | ~5,000+ |
| Lines of Code (Android) | ~5,500+ |
| Dangerous Permissions Tracked | 28 |
| Permission Categories | 11 |
| Trusted App Stores Detected | 5 |
| Room Database Tables | 5 |
| Preference Keys | 16 |
| Android UI Screens | 5 |
| CLI Menu Options | 11 |
| APK Size | 16.3 MB |

---

<p align="center">
  <b>Built with ❤️ for mobile security</b>
  <br/>
  <i>V-Scanner — Because your apps shouldn't spy on you.</i>
</p>
