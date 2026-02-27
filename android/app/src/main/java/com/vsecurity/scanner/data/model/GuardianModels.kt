package com.vsecurity.scanner.data.model

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Represents a sensor access event logged by the Privacy Guardian
 */
@Entity(tableName = "sensor_access_logs")
data class SensorAccessLog(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val packageName: String,
    val appName: String,
    val sensorType: SensorType,
    val accessTime: Long,
    val duration: Long = 0,
    val wasInBackground: Boolean,
    val wasScreenOff: Boolean = false,
    val isSuspicious: Boolean = false,
    val suspiciousReason: String? = null
)

/**
 * Types of sensors that can be monitored
 */
enum class SensorType {
    CAMERA,
    MICROPHONE,
    LOCATION,
    BODY_SENSORS,
    ACCELEROMETER,
    GYROSCOPE
}

/**
 * Privacy alert notification
 */
@Entity(tableName = "privacy_alerts")
data class PrivacyAlert(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val packageName: String,
    val appName: String,
    val alertType: AlertType,
    val sensorType: SensorType,
    val message: String,
    val timestamp: Long,
    val wasAcknowledged: Boolean = false
)

/**
 * Types of privacy alerts
 */
enum class AlertType {
    BACKGROUND_SENSOR_ACCESS,
    FREQUENT_ACCESS,
    FIRST_TIME_ACCESS,
    SCREEN_OFF_ACCESS,
    SUSPICIOUS_PATTERN
}

/**
 * Aggregated sensor usage statistics for an app
 */
@Entity(tableName = "app_sensor_stats")
data class AppSensorStats(
    @PrimaryKey
    val packageName: String,
    val appName: String,
    val cameraAccessCount: Int = 0,
    val microphoneAccessCount: Int = 0,
    val locationAccessCount: Int = 0,
    val bodySensorAccessCount: Int = 0,
    val totalBackgroundAccesses: Int = 0,
    val lastCameraAccess: Long? = null,
    val lastMicrophoneAccess: Long? = null,
    val lastLocationAccess: Long? = null,
    val lastUpdated: Long = System.currentTimeMillis()
)

/**
 * Daily sensor usage summary
 */
@Entity(tableName = "daily_sensor_summary")
data class DailySensorSummary(
    @PrimaryKey
    val date: String, // YYYY-MM-DD format
    val totalCameraAccesses: Int = 0,
    val totalMicrophoneAccesses: Int = 0,
    val totalLocationAccesses: Int = 0,
    val totalBackgroundAccesses: Int = 0,
    val uniqueAppsUsingCamera: Int = 0,
    val uniqueAppsUsingMicrophone: Int = 0,
    val uniqueAppsUsingLocation: Int = 0,
    val alertsTriggered: Int = 0
)

/**
 * Guardian monitoring settings
 */
data class GuardianSettings(
    val isEnabled: Boolean = true,
    val monitorCamera: Boolean = true,
    val monitorMicrophone: Boolean = true,
    val monitorLocation: Boolean = true,
    val alertOnBackgroundAccess: Boolean = true,
    val alertOnScreenOffAccess: Boolean = true,
    val alertOnFrequentAccess: Boolean = true,
    val frequentAccessThreshold: Int = 10, // per hour
    val whitelistedApps: Set<String> = emptySet()
)

/**
 * Permission audit recommendation
 */
data class PermissionRecommendation(
    val packageName: String,
    val appName: String,
    val permission: String,
    val currentlyGranted: Boolean,
    val recommendation: RecommendationType,
    val reason: String,
    val priority: Int // 1 = highest
)

enum class RecommendationType {
    REVOKE,
    KEEP,
    DOWNGRADE, // e.g., from "Always" to "While using app"
    REVIEW
}
