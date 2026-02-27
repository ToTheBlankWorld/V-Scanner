# Privacy Guardian - Architecture & Component Diagram

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE LAYER                      │
├──────────────┬──────────────┬──────────────┬──────────────────────┤
│  Dashboard   │   Guardian   │    Alerts    │      Settings        │
│   Screen     │    Screen    │    Screen    │       Screen         │
└──────────────┴──────────────┴──────────────┴──────────────────────┘
         ↓             ↓             ↓                ↓
┌─────────────────────────────────────────────────────────────────┐
│                     VIEWMODEL LAYER (MVVM)                       │
├──────────────┬──────────────┬──────────────┬──────────────────────┤
│  Dashboard   │  Guardian    │   Alerts     │     Settings         │
│  ViewModel   │  ViewModel   │  ViewModel   │     ViewModel        │
└──────────────┴──────────────┴──────────────┴──────────────────────┘
         ↓                                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                  REPOSITORY LAYER (Data Access)                  │
├─────────────────────────────────────────────────────────────────┤
│          GuardianRepository      |    ScannerRepository          │
│  - logSensorAccess()             |    - getAllApps()             │
│  - saveAlert()                   |    - saveApps()               │
│  - getRecentLogs()               |    - getHighRiskApps()        │
│  - getUnacknowledgedAlerts()     |                               │
│  - acknowledgeAlert()                                             │
│  - updateAppStats()                                              │
│  - updateDailySummary()                                          │
│  - clearAllData()                                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      ROOM DATABASE LAYER                         │
├──────────────┬──────────────┬──────────────┬──────────────────────┤
│SensorAccessLogDao│PrivacyAlertDao│AppSensorStatsDao│DailySummaryDao
│                │              │              │                    │
│getRecentLogs   │getRecent     │getAllStats   │getRecent          │
│insertLog       │Alerts        │getStats      │Summaries          │
│getSuspicious   │insertAlert   │TopBackground │insertOrUpdate     │
│getLogsSince    │acknowledge   │Accessors     │deleteOldSummaries │
│deleteOldLogs   │deleteAlert   │insertOrUpdate│deleteAllSummaries │
│deleteAllLogs   │deleteAll     │deleteAll     │                    │
└──────────────┴──────────────┴──────────────┴──────────────────────┘
         ↓             ↓             ↓                ↓
┌─────────────────────────────────────────────────────────────────┐
│                      LOCAL SQLITE TABLES                         │
├──────────────┬──────────────┬──────────────┬──────────────────────┤
│SensorAccess  │PrivacyAlerts │AppSensor     │DailySensor         │
│   Logs       │              │   Stats      │   Summary           │
│              │              │              │                     │
│ id (PK)      │ id (PK)      │packageName   │date (PK)            │
│packageName   │packageName   │appName       │totalCameraAccesses  │
│appName       │appName       │cameraCount   │totalMicroAccesses   │
│sensorType    │alertType     │microphoneC   │totalLocationAccess  │
│accessTime    │sensorType    │locationC     │totalBackground      │
│wasInBG       │message       │bodyS..Count  │uniqueAppsUsing...   │
│wasScreenOff  │timestamp     │totalBG       │alertsTriggered      │
│isSuspicious  │acknowledged  │lastAccess    │                     │
│suspiciousR..  │              │lastUpdated   │                     │
└──────────────┴──────────────┴──────────────┴──────────────────────┘
```

---

## Service Flow Diagram

```
┌──────────────────────────────────────────────────────────────┐
│         PRIVACY GUARDIAN SERVICE (Background)                │
│         PrivacyGuardianService.kt                             │
└──────────────────────────────────────────────────────────────┘
         ↓
    onCreate()
    onStartCommand()
    startForeground(NOTIFICATION)
         ↓
    startMonitoring()
    [Job runs every 5 seconds]
         ↓
┌──────────────────────────────────────────────────────────────┐
│              MONITORING LOOP (Every 5 seconds)                │
├──────────────────────────────────────────────────────────────┤
│
│  1. Get Device State
│     ├─ powerManager.isInteractive? (screen on/off)
│     ├─ getForegroundApp() via UsageStatsManager
│     └─ Get list of installed packages
│
│  2. For Each Monitored Sensor
│     ├─ If monitorCamera: checkSensorOp("android:camera")
│     ├─ If monitorMicrophone: checkSensorOp("android:record_audio")
│     ├─ If monitorLocation: checkSensorOp("android:fine_location")
│     └─ etc.
│
│  3. For Each Package (App)
│     ├─ Skip whitelisted apps
│     ├─ Skip Guardian app itself
│     └─ Query AppOpsManager for sensor access
│
│  4. If Access Detected
│     ├─ Get app name
│     ├─ Get last access time
│     └─ Determine if within monitoring interval (5 sec)
│
│  5. For Each Access Event
│     └─ Call handleSensorAccess()
│
└──────────────────────────────────────────────────────────────┘
         ↓
┌──────────────────────────────────────────────────────────────┐
│         handleSensorAccess() - Analyze & Store               │
├──────────────────────────────────────────────────────────────┤
│
│  1. Track Recent Accesses
│     ├─ Create key: "package:sensorType"
│     ├─ Add current time to list
│     └─ Keep only last hour (clean old)
│
│  2. Determine Suspicious
│     ├─ IF isBackground && alertOnBackgroundAccess → SUSPICIOUS
│     ├─ IF isScreenOff && alertOnScreenOffAccess → SUSPICIOUS
│     ├─ IF hits/hour > threshold && alertOnFrequent → SUSPICIOUS
│     └─ Reason: (assigned for alert message)
│
│  3. Create Log Entry
│     └─ SensorAccessLog(...)
│        ├─ packageName, appName
│        ├─ sensorType, accessTime
│        ├─ wasInBackground, wasScreenOff
│        ├─ isSuspicious, suspiciousReason
│        └─ STORE IN DATABASE
│
│  4. Update Statistics
│     └─ AppSensorStats(...)
│        ├─ Increment count for sensor type
│        ├─ Update last access time
│        ├─ Increment background count if needed
│        └─ STORE IN DATABASE
│
│  5. Create Alert (If Suspicious)
│     ├─ Determine AlertType (BACKGROUND|SCREEN_OFF|FREQUENT)
│     └─ PrivacyAlert(...)
│        ├─ packageName, appName
│        ├─ alertType, sensorType
│        ├─ message, timestamp
│        └─ STORE IN DATABASE
│
│  6. Show Notification
│     └─ NotificationCompat.Builder(ALERT_CHANNEL)
│        ├─ setContentTitle("Privacy Alert")
│        ├─ setContentText(message)
│        ├─ setContentIntent(tap → Alerts tab)
│        └─ SHOW TO USER
│
└──────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagram

```
                    ┌─────────────────────┐
                    │   Android Device    │
                    │                     │
                    │  ┌──────────────┐   │
                    │  │ Apps Running │   │
                    │  │              │   │
                    │  │ • Instagram  │   │
                    │  │ • Facebook   │   │
                    │  │ • Google Maps│   │
                    │  │ • Etc...     │   │
                    │  └──────────────┘   │
                    └──────────┬──────────┘
                               │
                   ┌───────────┴───────────┐
                   │                       │
            ┌──────▼──────┐         ┌──────▼──────┐
            │  AppOpsManager       │  UsageStats  │
            │  (Sensor Access)     │  (Foreground)│
            └──────┬──────┘        └──────┬──────┘
                   │                       │
                   └───────────┬───────────┘
                               │
                    ┌──────────▼──────────┐
                    │ PrivacyGuardian     │
                    │ Service             │
                    │ (Monitoring Logic)  │
                    └──────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
         ┌──────▼────┐  ┌──────▼────┐  ┌────▼────┐
         │  Log      │  │  Update   │  │  Create │
         │  Access   │  │  Stats    │  │  Alert  │
         └──────┬────┘  └──────┬────┘  └────┬────┘
                │              │            │
                └──────────────┼────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Room Database     │
                    │   (Local Storage)   │
                    ├─────────────────────┤
                    │ • SensorAccessLog   │
                    │ • PrivacyAlert      │
                    │ • AppSensorStats    │
                    │ • DailySummary      │
                    └──────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
        ┌───────▼────┐  ┌──────▼──────┐ ┌───▼────┐
        │  Guardian  │  │  Alerts     │ │Settings│
        │  ViewModel │  │  ViewModel  │ │ViewModel
        └───────┬────┘  └──────┬──────┘ └───┬────┘
                │              │            │
                └──────────────┼────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   UI Screens        │
                    │                     │
                    │  • Guardian Tab     │
                    │  • Alerts Tab       │
                    │  • Dashboard        │
                    │  • Settings         │
                    └─────────────────────┘
```

---

## Component Relationships

```
┌────────────────────────────────────────────────────────────┐
│                    ApplicationLayer                         │
│                  (VScannerApplication)                      │
│                    @HiltAndroidApp                          │
└────────────────────┬─────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
   ┌────▼────┐  ┌────▼────┐ ┌───▼─────┐
   │MainActivity│  │  Services   │ │ Receivers │
   │            │  │             │  │           │
   │ Navigation │  │ Privacy     │  │  Boot     │
   │ Bar (5     │  │ Guardian    │  │  Receiver │
   │ screens)   │  │ Service     │  │           │
   └────┬───────┘  └────────────┘  └───────────┘
        │
        │ ViewModels (DI)
        │
   ┌────▼──────────────────────────┐
   │    DI Module (AppModule.kt)    │
   │                                │
   │  ┌───────────────────────┐   │
   │  │ Provides:             │   │
   │  │ • Database            │   │
   │  │ • Repositories        │   │
   │  │ • ViewModels          │   │
   │  │ • Services            │   │
   │  │ • Preferences         │   │
   │  └───────────────────────┘   │
   └────────────────────────────┘
        │
        │ (injected into)
        │
   ┌────▼──────────────────────────┐
   │    GuardianViewModel           │
   │    ScannerViewModel            │
   │    AlertsViewModel             │
   │    SettingsViewModel           │
   │    DashboardViewModel          │
   └────┬───────────────────────────┘
        │ calls
        │
   ┌────▼────────────────────────────┐
   │ GuardianRepository               │
   │ ScannerRepository                │
   │ PreferencesManager               │
   └────┬─────────────────────────────┘
        │ calls
        │
   ┌────▼────────────────────────────┐
   │ DAOs & Database                  │
   │                                  │
   │ • SensorAccessLogDao             │
   │ • PrivacyAlertDao                │
   │ • AppSensorStatsDao              │
   │ • DailySummaryDao                │
   │ • ScannedAppDao                  │
   │                                  │
   │ ↓ (read/write)                   │
   │                                  │
   │ SQLite Database                  │
   │ (vscan_db)                       │
   └────────────────────────────────┘
```

---

## Alert Generation Flow

```
Sensor Access Detected
    ↓
Check if enabled in settings (monitorCamera, etc.)
    ↓
Get device state (screen on/off, foreground app)
    ↓
Log access: SensorAccessLog
    ├─ packageName
    ├─ sensorType
    ├─ accessTime
    ├─ wasInBackground
    ├─ wasScreenOff
    └─ isSuspicious: false (initially)
    ↓
Evaluate Suspicious
    ├─ IF backgroundAccess && alertOnBackground
    │   └─ isSuspicious = true, reason = "Background Access"
    │
    ├─ IF screenOff && alertOnScreenOff
    │   └─ isSuspicious = true, reason = "Screen Off Access"
    │
    ├─ IF frequentAccess && alertOnFrequent
    │   └─ isSuspicious = true, reason = "Frequent Access"
    │
    └─ ELSE
        └─ isSuspicious = false, reason = null
    ↓
IF isSuspicious
    ├─ Create PrivacyAlert entity
    │   ├─ alertType (BACKGROUND|SCREEN_OFF|FREQUENT|SUSPICIOUS)
    │   ├─ message (formatted for UI)
    │   ├─ timestamp (System.currentTimeMillis())
    │   └─ wasAcknowledged = false
    │
    ├─ Save to database
    │
    ├─ Show notification
    │   ├─ High priority
    │   ├─ Tap opens Alerts tab
    │   ├─ Shows app name + sensor + reason
    │   └─ Auto-dismiss after interaction
    │
    └─ Update UI (AlertsViewModel collects)
ELSE
    └─ Log only, no notification
    ↓
Update AppSensorStats
    ├─ Increment access count for sensor type
    ├─ Update lastAccessTime
    ├─ Increment background count if needed
    └─ Save to database
    ↓
(Every hour)
Update DailySensorSummary
    ├─ Aggregate all accesses for today
    ├─ Count by sensor type
    ├─ Count unique apps per sensor
    ├─ Count background accesses
    └─ Save to database
```

---

## Permission & API Requirements

```
┌──────────────────────────────────────────────────────────┐
│          Android Permissions & APIs Used                 │
├──────────────────────────────────────────────────────────┤
│
│ REQUIRED AndroidManifest.xml Permissions:
│  • QUERY_ALL_PACKAGES (Android 11+)
│    └─ Needed to enumerate all installed apps
│
│  • PACKAGE_USAGE_STATS
│    └─ Needed to detect foreground app, background detection
│    └─ User must grant in: Settings > Apps > Special access > Usage access
│
│  • FOREGROUND_SERVICE
│    └─ Needed to run Guardian service
│
│  • POST_NOTIFICATIONS (Android 13+)
│    └─ Needed to show alerts
│
│ RECOMMENDED (not required, but improves detection):
│  • READ_CALL_LOG
│  • READ_SMS
│  • RECORD_AUDIO
│  └─ To detect app permissions being used
│
├──────────────────────────────────────────────────────────┤
│ Android APIs Used:
│
│  • AppOpsManager
│    └─ getOpsForPackage(uid, packageName)
│    └─ Detects: camera, microphone, location access
│
│  • UsageStatsManager
│    └─ queryEvents(startTime, endTime)
│    └─ Detects: which app is in foreground
│
│  • PowerManager
│    └─ isInteractive
│    └─ Detects: if screen is on/off
│
│  • PackageManager
│    └─ getApplicationInfo()
│    └─ Gets: app names, icons, package info
│
│  • NotificationManager
│    └─ notify()
│    └─ Shows: alert notifications
│
│  • Room Database
│    └─ @Entity, @Dao, @Database
│    └─ Stores: logs locally
│
│  • DataStore
│    └─ Stores: guardian settings, preferences
│
└──────────────────────────────────────────────────────────┘
```

---

## Deployment Architecture

```
┌──────────────────────────────────────────────────────────┐
│              Android Device (User's Phone)                │
├──────────────────────────────────────────────────────────┤
│
│  ┌─────────────────────────────────────────────────────┐
│  │  V Scanner Application (APK)                         │
│  │                                                       │
│  │  ┌──────────────────────┐  ┌────────────────────┐   │
│  │  │  UI Layer            │  │  Service Layer     │   │
│  │  │  ─────────────────   │  │  ──────────────    │   │
│  │  │  • MainActivity      │  │  • PrivacyGuardian │   │
│  │  │  • Dashboard Screen  │  │    Service         │   │
│  │  │  • Guardian Screen   │  │  • BootReceiver    │   │
│  │  │  • Alerts Screen     │  │                    │   │
│  │  │  • Settings Screen   │  └────────────────────┘   │
│  │  │                      │                            │
│  │  │  ┌────────────────┐  │  ┌────────────────────┐   │
│  │  │  │ ViewModels     │  │  │ Local Storage      │   │
│  │  │  │ ──────────     │  │  │ ──────────────     │   │
│  │  │  │ • Dashboard    │  │  │ • SQLite DB        │   │
│  │  │  │ • Guardian     │  │  │ • DataStore        │   │
│  │  │  │ • Alerts       │  │  │ • Preferences      │   │
│  │  │  │ • Settings     │  │  │                    │   │
│  │  │  └────────────────┘  │  └────────────────────┘   │
│  │  │                      │                            │
│  │  │  ┌────────────────┐  │                            │
│  │  │  │ Repositories   │  │                            │
│  │  │  │ ──────────     │  │                            │
│  │  │  │ • Guardian     │  │                            │
│  │  │  │ • Scanner      │  │                            │
│  │  │  └────────────────┘  │                            │
│  │  └──────────────────────┘                            │
│  │                                                       │
│  │  ┌──────────────────────────────────────────────┐   │
│  │  │ Hilt Dependency Injection                    │   │
│  │  │ AppModule.kt                                 │   │
│  │  └──────────────────────────────────────────────┘   │
│  └─────────────────────────────────────────────────────┘
│
│  ┌─────────────────────────────────────────────────────┐
│  │  Android System Services (Used by Guardian)          │
│  │  ──────────────────────────────────────────────     │
│  │  • AppOpsManager (sensor monitoring)                 │
│  │  • UsageStatsManager (foreground app)                │
│  │  • PowerManager (screen state)                       │
│  │  • PackageManager (app info)                         │
│  │  • NotificationManager (alerts)                      │
│  └─────────────────────────────────────────────────────┘
│
│  ┌─────────────────────────────────────────────────────┐
│  │  Installed Apps (Being Monitored)                    │
│  │  ──────────────────────────────────────────────     │
│  │  • Instagram, Facebook, WhatsApp, etc.               │
│  │  (Guardian checks their sensor access)               │
│  └─────────────────────────────────────────────────────┘
│
└──────────────────────────────────────────────────────────┘
```

---

## Summary

This architecture provides:

✅ **Separation of Concerns** - Clean layers (UI, ViewModel, Repository, Database)  
✅ **Reactive Data Flow** - StateFlow for real-time UI updates  
✅ **Background Processing** - Service runs independently of UI  
✅ **Local Privacy** - All data stays on device  
✅ **Testability** - Repositories & ViewModels are testable  
✅ **Scalability** - New sensors can be added easily  
✅ **Performance** - Efficient sampling (5-second intervals)  
✅ **User Control** - Fine-grained settings & whitelisting  
