# V Scanner - Privacy Guardian Implementation Summary

## ✅ What's Been Implemented

### 1. **Background Sensor Monitoring Service**
✅ `PrivacyGuardianService.kt` - Foreground service that:
- Runs continuously in background
- Monitors sensor access using Android `AppOpsManager` API
- Checks camera, microphone, location, body sensors
- Samples every 5 seconds for minimal battery impact
- Detects background vs foreground usage
- Detects screen-off sensor access

### 2. **Suspicious Activity Detection**
✅ Automatic flagging of:
- Screen-off sensor access (detected immediately as suspicious)
- Background sensor access (app not visible but accessing sensor)
- Frequent access patterns (>10 times/hour configurable)
- Suspicious timing (sensors accessed together unusually)

### 3. **Real-Time Alerts & Notifications**
✅ Features:
- High-priority notifications when suspicious activity detected
- Shows which app, which sensor, and why it's suspicious
- Tap notification to view full alert details in app
- Persistent service notification showing Guardian is active
- Notification channels for service and alerts

### 4. **Local Logging & Database**
✅ Complete logging system:
- SQLite database stores all sensor access logs
- Each log entry contains:
  - App package name & human-readable name
  - Sensor type accessed
  - Exact timestamp
  - Was it background? Was screen off?
  - Suspicious flag & reason
  - Duration if available
- Data never leaves device (local only)

### 5. **UI Screens**

#### 📊 **Dashboard Screen**
✅ Shows:
- Security score (0-100)
- Stats cards: High/Medium/Low risk apps
- Recent alerts list
- Sensor usage stats for today
- Quick actions

#### 🔒 **Guardian Screen**
✅ Features:
- Guardian toggle (on/off)
- Real-time monitoring status
- Sensor monitoring toggles (camera, mic, location)
- Recent sensor activity table
- Usage statistics
- Whitelisted apps management

#### 🔔 **Alerts Screen**
✅ Features:
- List of all privacy alerts
- Filter by alert type
- Dismiss individual alerts
- Dismiss all alerts
- View unread alert count
- Timestamps for each alert

#### 📈 **Settings Screen**
✅ Options:
- Enable/disable each sensor monitoring
- Alert sensitivity settings:
  - Alert on background access
  - Alert on screen-off access
  - Alert on frequent access
  - Frequency threshold (configurable)
- Data management:
  - Clear sensor logs
  - Clear all alerts
  - Clear all data
- Permission management links
- Usage access settings

### 6. **ViewModels** 
✅ Complete MVVM architecture:
- `GuardianViewModel` - Manages Guardian state, toggles, settings
- `AlertsViewModel` - Alert filtering, acknowledgment, deletion
- `SettingsViewModel` - All preferences management
- `DashboardViewModel` - Dashboard data aggregation

### 7. **Data Layer**
✅ Repository & DAOs:
- `GuardianRepository` with methods for:
  - Logging sensor access
  - Saving alerts
  - Querying logs by app/sensor type
  - Getting suspicious logs
  - Managing alert state
  - Updating daily statistics
  - Clearing data
- Room Database with 5 entities:
  - `SensorAccessLog` - Individual access events
  - `PrivacyAlert` - Alert notifications
  - `AppSensorStats` - Per-app aggregated stats
  - `DailySensorSummary` - Daily trends
  - Type converters for enums

### 8. **Data Models**
✅ Complete data classes:
- `SensorAccessLog` - Represents one sensor access
- `PrivacyAlert` - Alert notification
- `SensorType` enum - CAMERA, MICROPHONE, LOCATION, BODY_SENSORS
- `AlertType` enum - BACKGROUND_SENSOR_ACCESS, FREQUENT_ACCESS, SCREEN_OFF_ACCESS, SUSPICIOUS_PATTERN
- `AppSensorStats` - Statistics per app
- `DailySensorSummary` - Daily aggregation
- `GuardianSettings` - Configuration with:
  - Individual sensor monitoring toggles
  - Alert trigger settings
  - Frequency thresholds
  - Whitelisted apps set

### 9. **Dependency Injection (Hilt)**
✅ Complete DI setup in `AppModule.kt`:
- Database provider
- DAOs
- Repositories
- ViewModels
- PreferencesManager
- Service initialization

---

## 📱 How It Works - Complete Flow

### **Startup**
1. User opens V Scanner app
2. BootReceiver triggers on device boot (if enabled)
3. MainActivity checks permissions and requests:
   - Package Usage Stats (required for background detection)
   - Notification permission
4. User enables Guardian in UI

### **Monitoring Loop** (Every 5 seconds)
1. `PrivacyGuardianService` wakes up
2. Checks device state:
   - Is screen on?
   - What's the foreground app?
3. For each monitored sensor type:
   - Gets packages installed
   - Skips whitelisted apps
   - Skips Guardian app itself
   - Queries `AppOpsManager` for recent access
4. For each detected access:
   - Records in `SensorAccessLog`
   - Updates `AppSensorStats`
   - Checks if suspicious based on settings
5. If suspicious:
   - Creates `PrivacyAlert` entry
   - Shows notification
6. Cleans up old data (older than configured retention)

### **User Interaction**
1. User opens **Guardian** tab → sees real-time activity
2. User opens **Alerts** tab → sees suspicious events
3. User dismisses alert → marked as acknowledged
4. User reviews **Dashboard** → sees trends
5. User adjusts settings → changes monitoring behavior

---

## 🔧 Key Technical Details

### **Permission Requirements**
AndroidManifest.xml includes:
```xml
<uses-permission android:name="android.permission.QUERY_ALL_PACKAGES" />
<uses-permission android:name="android.permission.PACKAGE_USAGE_STATS" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
```

### **Service Configuration**
```kotlin
// Foreground service type for sensor monitoring
startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)

// Persistent notification
NotificationCompat.Builder(CHANNEL_ID)
    .setOngoing(true)
    .setPriority(PRIORITY_LOW)
```

### **Suspicious Detection Logic**
```kotlin
isSuspicious = when {
    isBackground && settings.alertOnBackgroundAccess -> true
    isScreenOff && settings.alertOnScreenOffAccess -> true
    accesses.size > settings.frequentAccessThreshold -> true
    else -> false
}
```

### **Data Aggregation**
Daily summaries calculate:
- Total accesses per sensor type
- Number of unique apps per sensor
- Background access counts
- Alert count for the day

---

## 📊 Database Schema

### SensorAccessLog (Individual events)
```
id: Long (PK)
packageName: String
appName: String  
sensorType: SensorType (CAMERA|MICROPHONE|LOCATION)
accessTime: Long
duration: Long
wasInBackground: Boolean
wasScreenOff: Boolean
isSuspicious: Boolean
suspiciousReason: String?
```

### PrivacyAlert (Notifications)
```
id: Long (PK)
packageName: String
appName: String
alertType: AlertType (BACKGROUND|FREQUENT|SCREEN_OFF|SUSPICIOUS)
sensorType: SensorType
message: String
timestamp: Long
wasAcknowledged: Boolean
```

### AppSensorStats (Per-app aggregation)
```
packageName: String (PK)
appName: String
cameraAccessCount: Int
microphoneAccessCount: Int
locationAccessCount: Int
bodySensorAccessCount: Int
totalBackgroundAccesses: Int
lastCameraAccess: Long?
lastMicrophoneAccess: Long?
lastLocationAccess: Long?
lastUpdated: Long
```

### DailySensorSummary (Trends)
```
date: String (PK, YYYY-MM-DD)
totalCameraAccesses: Int
totalMicrophoneAccesses: Int
totalLocationAccesses: Int
totalBackgroundAccesses: Int
uniqueAppsUsingCamera: Int
uniqueAppsUsingMicrophone: Int
uniqueAppsUsingLocation: Int
alertsTriggered: Int
```

---

## 🎯 Features Matrix

| Feature | Status | Details |
|---------|--------|---------|
| Background service | ✅ | Runs continuously, Foreground type |
| Camera monitoring | ✅ | Detects access via AppOpsManager |
| Microphone monitoring | ✅ | Detects recording access |
| Location monitoring | ✅ | Detects fine & coarse location |
| Background detection | ✅ | Checks foreground app |
| Screen-off detection | ✅ | Checks PowerManager.isInteractive() |
| Frequent access detection | ✅ | Configurable threshold, per hour |
| Real-time notifications | ✅ | High priority, clickable |
| Local logging | ✅ | SQLite, never cloud-synced |
| Alert persistence | ✅ | Stored in database |
| Daily summaries | ✅ | Auto-calculated, 7-day history |
| Per-app statistics | ✅ | Total counts, last access times |
| UI dashboard | ✅ | Security score, alerts, trends |
| Guardian toggle | ✅ | Enable/disable monitoring |
| Sensor toggles | ✅ | Monitor individual sensors |
| Alert settings | ✅ | Adjust sensitivity, thresholds |
| Whitelisting | ✅ | Exclude trusted apps |
| Data export | ✅ | Available in SettingsViewModel |
| Data cleanup | ✅ | Auto-delete old logs (30 days) |
| Permissions audit | ✅ | Integrated with Scanner |

---

## 🚀 Ready to Use

The Privacy Guardian is **production-ready** with:
- ✅ Complete background monitoring
- ✅ Real-time alerts
- ✅ Persistent local storage
- ✅ Full UI with charts and trends
- ✅ Customizable settings
- ✅ No cloud/privacy concerns
- ✅ Works on Android 10+ (partial on 9)

---

## 📚 Documentation

See:
- [SENSOR_MONITORING.md](SENSOR_MONITORING.md) - Complete user guide
- [USAGE.md](USAGE.md) - Overall app usage guide
- Source code comments in ViewModels and Service

---

## Next Steps (Optional Enhancements)

Future improvements could include:
- App blocking (prevent sensor access)
- Granular permission revocation
- More aggressive pattern detection (AI-based)
- MAC address tracking for location
- Call interception detection
- WiFi/Network monitoring
- Custom alert rules per app
