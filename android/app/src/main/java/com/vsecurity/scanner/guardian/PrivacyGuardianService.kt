package com.vsecurity.scanner.guardian

import android.app.AppOpsManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.vsecurity.scanner.R
import com.vsecurity.scanner.data.model.*
import com.vsecurity.scanner.data.repository.GuardianRepository
import com.vsecurity.scanner.ui.MainActivity
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.text.SimpleDateFormat
import java.util.*
import javax.inject.Inject

/**
 * Background service that monitors sensor access by apps
 */
@AndroidEntryPoint
class PrivacyGuardianService : Service() {

    @Inject
    lateinit var repository: GuardianRepository

    private val binder = LocalBinder()
    private val serviceScope = CoroutineScope(Dispatchers.Default + SupervisorJob())
    
    private var monitoringJob: Job? = null
    private var isMonitoring = false

    private val _monitoringState = MutableStateFlow<MonitoringState>(MonitoringState.Idle)
    val monitoringState: StateFlow<MonitoringState> = _monitoringState

    private lateinit var appOpsManager: AppOpsManager
    private lateinit var usageStatsManager: UsageStatsManager
    private lateinit var powerManager: PowerManager
    private lateinit var notificationManager: NotificationManager
    private lateinit var packageManager: PackageManager

    private var settings: GuardianSettings = GuardianSettings()
    private val recentAccesses = mutableMapOf<String, MutableList<Long>>()

    companion object {
        const val CHANNEL_ID = "privacy_guardian_channel"
        const val ALERT_CHANNEL_ID = "privacy_alert_channel"
        const val NOTIFICATION_ID = 1001
        const val MONITORING_INTERVAL = 5000L // 5 seconds

        // AppOps constants for sensor access
        const val OP_CAMERA = "android:camera"
        const val OP_RECORD_AUDIO = "android:record_audio"
        const val OP_FINE_LOCATION = "android:fine_location"
        const val OP_COARSE_LOCATION = "android:coarse_location"
        const val OP_BODY_SENSORS = "android:body_sensors"

        fun startService(context: Context) {
            val intent = Intent(context, PrivacyGuardianService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stopService(context: Context) {
            context.stopService(Intent(context, PrivacyGuardianService::class.java))
        }
    }

    inner class LocalBinder : Binder() {
        fun getService(): PrivacyGuardianService = this@PrivacyGuardianService
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        initializeManagers()
        createNotificationChannels()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground()
        startMonitoring()
        return START_STICKY
    }

    override fun onDestroy() {
        stopMonitoring()
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun initializeManagers() {
        appOpsManager = getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        usageStatsManager = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        packageManager = this.packageManager
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // Main service channel
            val serviceChannel = NotificationChannel(
                CHANNEL_ID,
                "Privacy Guardian Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Monitors sensor access by apps"
                setShowBadge(false)
            }

            // Alert channel
            val alertChannel = NotificationChannel(
                ALERT_CHANNEL_ID,
                "Privacy Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Alerts for suspicious sensor access"
                enableVibration(true)
            }

            notificationManager.createNotificationChannel(serviceChannel)
            notificationManager.createNotificationChannel(alertChannel)
        }
    }

    private fun startForeground() {
        val notification = createServiceNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun createServiceNotification(): Notification {
        val intent = Intent(this, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            this, 0, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Privacy Guardian Active")
            .setContentText("Monitoring sensor access...")
            .setSmallIcon(R.drawable.ic_shield)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    /**
     * Start monitoring sensor accesses
     */
    fun startMonitoring() {
        if (isMonitoring) return

        isMonitoring = true
        _monitoringState.value = MonitoringState.Active

        monitoringJob = serviceScope.launch {
            while (isActive && isMonitoring) {
                try {
                    checkSensorAccesses()
                } catch (e: Exception) {
                    _monitoringState.value = MonitoringState.Error(e.message ?: "Unknown error")
                }
                delay(MONITORING_INTERVAL)
            }
        }
    }

    /**
     * Stop monitoring
     */
    fun stopMonitoring() {
        isMonitoring = false
        monitoringJob?.cancel()
        _monitoringState.value = MonitoringState.Idle
    }

    /**
     * Update monitoring settings
     */
    fun updateSettings(newSettings: GuardianSettings) {
        settings = newSettings
    }

    /**
     * Check for sensor accesses using AppOpsManager
     */
    private suspend fun checkSensorAccesses() {
        val currentTime = System.currentTimeMillis()
        val isScreenOn = powerManager.isInteractive
        val foregroundApp = getForegroundApp()

        // Check each sensor type
        if (settings.monitorCamera) {
            checkSensorOp(OP_CAMERA, SensorType.CAMERA, currentTime, isScreenOn, foregroundApp)
        }
        if (settings.monitorMicrophone) {
            checkSensorOp(OP_RECORD_AUDIO, SensorType.MICROPHONE, currentTime, isScreenOn, foregroundApp)
        }
        if (settings.monitorLocation) {
            checkSensorOp(OP_FINE_LOCATION, SensorType.LOCATION, currentTime, isScreenOn, foregroundApp)
            checkSensorOp(OP_COARSE_LOCATION, SensorType.LOCATION, currentTime, isScreenOn, foregroundApp)
        }

        // Update daily summary
        updateDailySummary(currentTime)
    }

    /**
     * Check a specific sensor operation for all apps
     */
    private suspend fun checkSensorOp(
        opName: String,
        sensorType: SensorType,
        currentTime: Long,
        isScreenOn: Boolean,
        foregroundApp: String?
    ) {
        val packages = getInstalledPackages()

        for (packageName in packages) {
            if (settings.whitelistedApps.contains(packageName)) continue
            if (packageName == this.packageName) continue

            try {
                val appInfo = packageManager.getApplicationInfo(packageName, 0)
                val uid = appInfo.uid

                // Get app ops history (API 29+)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val opsForPackage = appOpsManager.getOpsForPackage(uid, packageName)
                    
                    opsForPackage?.forEach { entry ->
                        entry.ops?.forEach { op ->
                            val lastAccess = op.getLastAccessTime(
                                AppOpsManager.OP_FLAGS_ALL_TRUSTED
                            )
                            
                            // If access was within monitoring interval
                            if (lastAccess > currentTime - MONITORING_INTERVAL) {
                                val isBackground = foregroundApp != packageName
                                val appName = packageManager.getApplicationLabel(appInfo).toString()
                                
                                handleSensorAccess(
                                    packageName = packageName,
                                    appName = appName,
                                    sensorType = sensorType,
                                    accessTime = lastAccess,
                                    isBackground = isBackground,
                                    isScreenOff = !isScreenOn
                                )
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                // Skip package if we can't get info
            }
        }
    }

    /**
     * Handle a detected sensor access
     */
    private suspend fun handleSensorAccess(
        packageName: String,
        appName: String,
        sensorType: SensorType,
        accessTime: Long,
        isBackground: Boolean,
        isScreenOff: Boolean
    ) {
        // Track recent accesses for frequency detection
        val key = "$packageName:$sensorType"
        val accesses = recentAccesses.getOrPut(key) { mutableListOf() }
        accesses.add(accessTime)
        
        // Keep only last hour of accesses
        val oneHourAgo = accessTime - (60 * 60 * 1000)
        accesses.removeAll { it < oneHourAgo }

        // Determine if suspicious
        var isSuspicious = false
        var suspiciousReason: String? = null

        when {
            isBackground && settings.alertOnBackgroundAccess -> {
                isSuspicious = true
                suspiciousReason = "Background sensor access"
            }
            isScreenOff && settings.alertOnScreenOffAccess -> {
                isSuspicious = true
                suspiciousReason = "Sensor access while screen off"
            }
            accesses.size > settings.frequentAccessThreshold && settings.alertOnFrequentAccess -> {
                isSuspicious = true
                suspiciousReason = "Frequent access (${accesses.size} times/hour)"
            }
        }

        // Log the access
        val logEntry = SensorAccessLog(
            packageName = packageName,
            appName = appName,
            sensorType = sensorType,
            accessTime = accessTime,
            wasInBackground = isBackground,
            wasScreenOff = isScreenOff,
            isSuspicious = isSuspicious,
            suspiciousReason = suspiciousReason
        )
        repository.logSensorAccess(logEntry)

        // Update app stats
        repository.updateAppStats(packageName, appName, sensorType, isBackground)

        // Send alert if suspicious
        if (isSuspicious) {
            sendPrivacyAlert(packageName, appName, sensorType, suspiciousReason!!)
        }
    }

    /**
     * Send privacy alert notification
     */
    private suspend fun sendPrivacyAlert(
        packageName: String,
        appName: String,
        sensorType: SensorType,
        reason: String
    ) {
        val alertType = when {
            reason.contains("Background") -> AlertType.BACKGROUND_SENSOR_ACCESS
            reason.contains("screen off") -> AlertType.SCREEN_OFF_ACCESS
            reason.contains("Frequent") -> AlertType.FREQUENT_ACCESS
            else -> AlertType.SUSPICIOUS_PATTERN
        }

        // Save alert to database
        val alert = PrivacyAlert(
            packageName = packageName,
            appName = appName,
            alertType = alertType,
            sensorType = sensorType,
            message = "$appName: $reason using ${sensorType.name}",
            timestamp = System.currentTimeMillis()
        )
        repository.saveAlert(alert)

        // Show notification
        showAlertNotification(appName, sensorType, reason)
    }

    private fun showAlertNotification(appName: String, sensorType: SensorType, reason: String) {
        val sensorIcon = when (sensorType) {
            SensorType.CAMERA -> "📷"
            SensorType.MICROPHONE -> "🎤"
            SensorType.LOCATION -> "📍"
            else -> "⚠️"
        }

        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            putExtra("navigate_to", "alerts")
        }
        
        val pendingIntent = PendingIntent.getActivity(
            this, System.currentTimeMillis().toInt(), intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val notification = NotificationCompat.Builder(this, ALERT_CHANNEL_ID)
            .setContentTitle("$sensorIcon Privacy Alert")
            .setContentText("$appName: $reason")
            .setSmallIcon(R.drawable.ic_alert)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        val notificationId = (System.currentTimeMillis() % 10000).toInt()
        notificationManager.notify(notificationId, notification)
    }

    /**
     * Get the current foreground app
     */
    private fun getForegroundApp(): String? {
        val time = System.currentTimeMillis()
        val usageEvents = usageStatsManager.queryEvents(time - 10000, time)
        var foregroundApp: String? = null
        
        val event = UsageEvents.Event()
        while (usageEvents.hasNextEvent()) {
            usageEvents.getNextEvent(event)
            if (event.eventType == UsageEvents.Event.ACTIVITY_RESUMED) {
                foregroundApp = event.packageName
            }
        }
        
        return foregroundApp
    }

    private fun getInstalledPackages(): List<String> {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.getInstalledApplications(
                PackageManager.ApplicationInfoFlags.of(0)
            )
        } else {
            @Suppress("DEPRECATION")
            packageManager.getInstalledApplications(0)
        }.map { it.packageName }
    }

    private suspend fun updateDailySummary(currentTime: Long) {
        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        val today = dateFormat.format(Date(currentTime))
        repository.updateDailySummary(today)
    }
}

sealed class MonitoringState {
    object Idle : MonitoringState()
    object Active : MonitoringState()
    data class Error(val message: String) : MonitoringState()
}
