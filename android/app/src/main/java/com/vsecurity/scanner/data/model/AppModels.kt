package com.vsecurity.scanner.data.model

import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.TypeConverters
import com.vsecurity.scanner.data.local.Converters

/**
 * Represents an installed application with its security assessment
 */
@Entity(tableName = "scanned_apps")
@TypeConverters(Converters::class)
data class ScannedApp(
    @PrimaryKey
    val packageName: String,
    val appName: String,
    val versionName: String,
    val versionCode: Long,
    val targetSdk: Int,
    val minSdk: Int,
    val permissions: List<String>,
    val dangerousPermissions: List<DangerousPermission>,
    val riskScore: Int,
    val riskLevel: RiskLevel,
    val installTime: Long,
    val lastUpdateTime: Long,
    val isSystemApp: Boolean,
    val lastScanned: Long = System.currentTimeMillis()
)

/**
 * Risk level classification
 */
enum class RiskLevel {
    CRITICAL,
    HIGH,
    MEDIUM,
    LOW,
    INFO
}

/**
 * Represents a dangerous permission found in an app
 */
data class DangerousPermission(
    val name: String,
    val riskLevel: RiskLevel,
    val category: PermissionCategory,
    val description: String,
    val risks: List<String>,
    val mitigations: List<String>
)

/**
 * Categories of permissions
 */
enum class PermissionCategory {
    SMS,
    CONTACTS,
    CAMERA,
    LOCATION,
    MICROPHONE,
    STORAGE,
    PHONE,
    CALENDAR,
    SENSORS,
    NETWORK,
    SPECIAL
}

/**
 * Permission definition with risk assessment
 */
data class PermissionDefinition(
    val permission: String,
    val name: String,
    val riskLevel: RiskLevel,
    val category: PermissionCategory,
    val description: String,
    val risks: List<String>,
    val mitigations: List<String>,
    val secureAlternatives: List<String>
)

/**
 * Security scan report
 */
data class ScanReport(
    val scanTime: Long,
    val totalApps: Int,
    val criticalRiskApps: Int,
    val highRiskApps: Int,
    val mediumRiskApps: Int,
    val lowRiskApps: Int,
    val totalDangerousPermissions: Int,
    val mostCommonPermissions: List<Pair<String, Int>>,
    val apps: List<ScannedApp>
)
