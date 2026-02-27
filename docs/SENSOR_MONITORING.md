# Privacy Guardian - Sensor Monitoring Guide

## Overview

The Privacy Guardian is a background monitoring service that continuously tracks when apps access sensitive sensors on your device. It alerts you to suspicious activity like:
- ✅ Camera access while screen is off
- ✅ Microphone recording in the background
- ✅ GPS location tracking at night
- ✅ Unusually frequent sensor access

---

## How It Works

### 1. **Continuous Monitoring**

The Guardian service runs in the background and checks every 5 seconds for sensor access attempts by all installed apps (except whitelisted ones).

It monitors:
- **Camera** (`android:camera`)
- **Microphone** (`android:record_audio`)
- **Location** (`android:fine_location` and `android:coarse_location`)
- **Body Sensors** (accelerometer, gyroscope)

### 2. **Detection Methods**

Uses **AppOpsManager** (Android API) to check when apps access sensors:
- No root required
- Works on all Android 10+
- Validates against device state (screen on/off, app in foreground/background)

### 3. **Alert Triggering**

The Guardian creates alerts when:

| Condition | Alert Type | Example |
|-----------|-----------|---------|
| App uses sensor while **screen is OFF** | Screen Off Access | Facebook accessing camera at 3 AM |
| App uses sensor while **running in BACKGROUND** | Background Access | Instagram recording audio while minimized |
| App accesses sensor **>10 times per hour** | Frequent Access | TikTok accessing camera repeatedly during video creation |
| **Suspicious pattern detected** | Suspicious Pattern | App accessing multiple sensors together unusually |

### 4. **Logging & Storage**

Every sensor access is logged with:
- Package name & app name
- Sensor type
- Access timestamp  
- Whether it was background/foreground
- Screen state (on/off)
- Suspicious flag & reason

Storage: Local SQLite database (never sent to cloud)

---

## Enabling & Using Guardian

### Step 1: Grant Permissions

Install the app and go to **Settings** tab:

1. **Enable Guardian** toggle → Turn ON
2. Grant **Package Usage Stats** permission (required for background detection)
   - Settings > Apps > Special access > Usage access → Enable V Scanner
3. Grant notification permission when prompted

### Step 2: Configure Monitoring

In **Guardian** tab, select which sensors to monitor:

```
📷 Monitor Camera    ☑️
🎤 Monitor Microphone ☑️
📍 Monitor Location   ☑️
```

### Step 3: Adjust Alert Sensitivity

In **Settings** tab under "Guardian Settings":

- **Alert on background access**: Alert if app uses sensor while minimized
- **Alert on screen-off access**: Alert if sensor is used while screen is locked
- **Alert on frequent access**: Alert if >10 accesses per hour (configurable)

### Step 4: Monitor Activity

Open **Guardian** tab to see:
- ✅ Real-time sensor activity
- ✅ Which apps are accessing which sensors
- ✅ Usage trends (chart showing daily activity)
- ✅ Apps using most background accesses

---

## Alerts & Notifications

### Alert Types

#### 🔴 **Background Sensor Access**
App accessed a sensor while running in the background (not visible on screen).

**Example**: WhatsApp accessing microphone while you're using another app

**Normal?** Sometimes - voice calling apps, fitness trackers  
**Suspicious?** Games, social media should rarely access sensors in background

---

#### 🔴 **Screen Off Access**
App accessed a sensor while device screen was locked/off.

**Example**: Camera access at 3 AM when device is in pocket

**Normal?** Almost never  
**Suspicious?** Almost always - very concerning sign

---

#### ⚠️ **Frequent Access**
App accessed the same sensor >10 times in one hour.

**Example**: TikTok accessing camera 50 times while recording video

**Normal?** Video/streaming apps during use  
**Suspicious?** Frequent access at random times

---

#### ⚠️ **Suspicious Pattern**
Multiple sensors accessed together in unusual ways.

**Example**: Using camera, microphone, AND location while screen is off

**Normal?** Rare  
**Suspicious?** Strong indicator of malware/spyware

---

## Dashboard Features

### Security Score
Overall device security rating (0-100) based on:
- Number of high-risk apps
- Guardian alerts triggered
- Suspicious patterns detected

**Score Calculation**:
```
Score = 100 - (High Risk Apps × 5) - (Suspicious Accesses × 2)
```

### Sensor Usage Today
Shows widget of:
- 📷 Camera accesses (count)
- 🎤 Microphone accesses (count)
- 📍 Location accesses (count)

### Recent Alerts
List of latest privacy alerts with:
- App name that triggered alert
- Sensor type
- Alert type
- Time of alert
- Dismiss button

### Usage Trends
7-day chart showing:
- Daily camera accesses
- Daily microphone accesses
- Daily location accesses

---

## Data Management

### View Detailed Logs

**Guardian tab** → **Recent Activity**

Shows every sensor access logged with:
- Timestamp
- App name
- Sensor type
- Background? / Screen off?
- Flagged as suspicious?

### Acknowledge Alerts

**Alerts tab** → Select alert → **Dismiss**

Marking alert as "dismissed" removes it from unread count but keeps in history.

### Clear Data

**Settings** → **Data Management**

Options:
- **Clear Scan History** - Remove vulnerability scanner results
- **Clear Sensor Logs** - Remove Guardian access logs
- **Clear All Alerts** - Remove all privacy notifications
- **Clear All Data** - Nuclear option: wipe everything

**⚠️ Warning**: Clearing data is permanent and cannot be undone!

---

## Whitelisting Apps

By default, all apps are monitored. You can whitelist safe apps:

1. Go to **Settings** → **Guardian Settings**
2. Scroll to "Whitelisted Apps"
3. Add apps you trust (e.g., default Camera app if you mostly use it manually)

**Note**: Whitelisted apps won't trigger alerts but their access will still be logged.

---

## Privacy & Security

### ✅ What V Scanner Does
- Runs completely local - no cloud sync
- Uses device Android APIs only
- Never accesses app data
- Never intercepts communications

### ✅ What V Scanner Does NOT Do
- ❌ Doesn't see app data
- ❌ Doesn't modify permissions
- ❌ Doesn't block app access
- ❌ Doesn't send data to servers
- ❌ Doesn't require root/admin access

### Data Storage
- Logs stored in encrypted local SQLite database
- Accessible only to V Scanner app
- Can be cleared at any time in Settings

---

## Troubleshooting

### Guardian Shows "No Activity"

**Problem**: No sensor access detected even though apps are using camera/mic

**Solutions**:
1. Verify **Package Usage Stats permission** is granted
   - Go to Settings > Apps > Special access > Usage access
   - Enable V Scanner
2. Try opening camera or voice recorder app
3. Some apps may not trigger detection (API limitations)

**Note**: Background detection works best on Android 10+

---

### Lots of Alerts for Normal Apps

**Problem**: Getting alerts for camera app, Google Phone, etc.

**Solutions**:
1. Reduce alert sensitivity in **Settings**
2. Whitelist trusted apps (Camera, Phone, Maps)
3. Disable "Alert on Frequent Access" if causing spam

---

### Guardian Not Running

**Problem**: Don't see persistent notification for Guardian service

**Solutions**:
1. Go to **Guardian tab** → Toggle Guardian OFF then ON
2. Check if app is not in Battery Saver/restricted mode
   - Settings > Apps > V Scanner > Battery > Not restricted
3. Restart device

---

## What Apps Should & Shouldn't Do

### ✅ NORMAL SENSOR USE

| App | Sensor | When | Why |
|-----|--------|------|-----|
| Camera | CAMERA | When you take photo | Expected |
| WhatsApp | MIC | During call | Expected |
| Google Maps | LOCATION | While navigating | Expected |
| Fitness App | ACCELEROMETER | While tracking workout | Expected |
| Default Phone | MIC | During call | Expected |

### ⚠️ SUSPICIOUS SENSOR USE

| App | Sensor | When | Reason |
|-----|--------|------|--------|
| "Free WiFi" | CAMERA | Screen off at night | Spyware? |
| Instagram | MIC | Background, not recording | Unnecessary |
| "Game Pro" | LOCATION | Continuously while gaming | Tracking? |
| Flashlight | CAMERA | Always enabled | Just needs LED |
| Weather App | LOCATION | Every 5 minutes indoors | Excessive |

---

## Recommended Settings

### For Privacy Maximalists
```
✓ Alert on background access
✓ Alert on screen-off access  
✓ Alert on frequent access
Frequency threshold: 5 (very sensitive)
Review logs: Weekly
Clear old data: Every month
```

### For Casual Users
```
✓ Alert on background access
✓ Alert on screen-off access
☐ Alert on frequent access (noise)
Frequency threshold: 15 (moderate)
Review logs: As needed
Clear old data: Every 3 months
```

### For Multi-Device Users
```
☐ Alert on background access (less intrusive)
✓ Alert on screen-off access (critical only)
☐ Alert on frequent access (too much noise)
Frequency threshold: 20 (relaxed)
Review logs: Rarely  
Clear old data: Every 6 months
```

---

## Integration with Other Features

### Vulnerability Scanner + Guardian

Use together for complete coverage:

1. **Scanner** checks permissions declared in APK
2. **Guardian** checks permissions actually being USED

Example: App declares camera permission (scanner flagged) AND actually uses it at 3 AM (guardian alerts)

### Dashboard

Central hub showing:
- Security score
- Guardian alerts summary
- Sensor usage trends
- Recent suspicious activity

---

## FAQ

**Q: Does this require root?**
A: No, uses official Android APIs available to any app

**Q: Does this drain battery?**
A: Minimal - checks every 5 seconds, runs in background service

**Q: Can I block apps from accessing sensors?**
A: Not in v1.0 - for now it only alerts. Future versions may support revocation

**Q: What about system apps?**
A: Monitored like any other app. Can be whitelisted if trusted

**Q: Does this work on Android 9 and below?**
A: Partial - older Android versions have limited sensor access APIs

**Q: Can I export the logs?**
A: In Settings > Export Data - generates JSON file

---

## Summary

Privacy Guardian empowers you to:
- ✅ See what apps are doing with your sensitive sensors
- ✅ Get instant alerts for suspicious behavior
- ✅ Track usage patterns over time
- ✅ Identify privacy-invasive apps
- ✅ Make informed decisions about what apps to trust

**Remember**: Your privacy matters. Monitor it!
