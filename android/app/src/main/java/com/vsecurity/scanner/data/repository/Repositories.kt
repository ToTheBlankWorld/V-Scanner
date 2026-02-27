package com.vsecurity.scanner.data.repository

import com.vsecurity.scanner.data.local.*
import com.vsecurity.scanner.data.model.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for Guardian-related data operations
 */
@Singleton
class GuardianRepository @Inject constructor(
    private val sensorAccessLogDao: SensorAccessLogDao,
    private val privacyAlertDao: PrivacyAlertDao,
    private val appSensorStatsDao: AppSensorStatsDao,
    private val dailySummaryDao: DailySummaryDao
) {
    /**
     * Log a sensor access event
     */
    suspend fun logSensorAccess(log: SensorAccessLog) = withContext(Dispatchers.IO) {
        sensorAccessLogDao.insertLog(log)
    }

    /**
     * Save a privacy alert
     */
    suspend fun saveAlert(alert: PrivacyAlert) = withContext(Dispatchers.IO) {
        privacyAlertDao.insertAlert(alert)
    }

    /**
     * Get recent sensor access logs
     */
    suspend fun getRecentLogs(limit: Int = 100): List<SensorAccessLog> = withContext(Dispatchers.IO) {
        sensorAccessLogDao.getRecentLogs(limit)
    }

    /**
     * Get logs for a specific app
     */
    suspend fun getLogsForApp(packageName: String): List<SensorAccessLog> = withContext(Dispatchers.IO) {
        sensorAccessLogDao.getLogsForApp(packageName)
    }

    /**
     * Get suspicious activity logs
     */
    suspend fun getSuspiciousLogs(): List<SensorAccessLog> = withContext(Dispatchers.IO) {
        sensorAccessLogDao.getSuspiciousLogs()
    }

    /**
     * Get recent alerts
     */
    suspend fun getRecentAlerts(limit: Int = 50): List<PrivacyAlert> = withContext(Dispatchers.IO) {
        privacyAlertDao.getRecentAlerts(limit)
    }

    /**
     * Get unacknowledged alerts
     */
    suspend fun getUnacknowledgedAlerts(): List<PrivacyAlert> = withContext(Dispatchers.IO) {
        privacyAlertDao.getUnacknowledgedAlerts()
    }

    /**
     * Get count of unacknowledged alerts
     */
    suspend fun getUnacknowledgedAlertCount(): Int = withContext(Dispatchers.IO) {
        privacyAlertDao.getUnacknowledgedCount()
    }

    /**
     * Acknowledge an alert
     */
    suspend fun acknowledgeAlert(alertId: Long) = withContext(Dispatchers.IO) {
        privacyAlertDao.acknowledgeAlert(alertId)
    }

    /**
     * Acknowledge all alerts
     */
    suspend fun acknowledgeAllAlerts() = withContext(Dispatchers.IO) {
        privacyAlertDao.acknowledgeAllAlerts()
    }

    /**
     * Update app sensor statistics
     */
    suspend fun updateAppStats(
        packageName: String,
        appName: String,
        sensorType: SensorType,
        wasBackground: Boolean
    ) = withContext(Dispatchers.IO) {
        val existing = appSensorStatsDao.getStatsForApp(packageName) ?: AppSensorStats(
            packageName = packageName,
            appName = appName
        )

        val updated = when (sensorType) {
            SensorType.CAMERA -> existing.copy(
                cameraAccessCount = existing.cameraAccessCount + 1,
                lastCameraAccess = System.currentTimeMillis(),
                totalBackgroundAccesses = if (wasBackground) existing.totalBackgroundAccesses + 1 else existing.totalBackgroundAccesses,
                lastUpdated = System.currentTimeMillis()
            )
            SensorType.MICROPHONE -> existing.copy(
                microphoneAccessCount = existing.microphoneAccessCount + 1,
                lastMicrophoneAccess = System.currentTimeMillis(),
                totalBackgroundAccesses = if (wasBackground) existing.totalBackgroundAccesses + 1 else existing.totalBackgroundAccesses,
                lastUpdated = System.currentTimeMillis()
            )
            SensorType.LOCATION -> existing.copy(
                locationAccessCount = existing.locationAccessCount + 1,
                lastLocationAccess = System.currentTimeMillis(),
                totalBackgroundAccesses = if (wasBackground) existing.totalBackgroundAccesses + 1 else existing.totalBackgroundAccesses,
                lastUpdated = System.currentTimeMillis()
            )
            SensorType.BODY_SENSORS -> existing.copy(
                bodySensorAccessCount = existing.bodySensorAccessCount + 1,
                totalBackgroundAccesses = if (wasBackground) existing.totalBackgroundAccesses + 1 else existing.totalBackgroundAccesses,
                lastUpdated = System.currentTimeMillis()
            )
            else -> existing
        }

        appSensorStatsDao.insertOrUpdate(updated)
    }

    /**
     * Get all app sensor statistics
     */
    suspend fun getAllAppStats(): List<AppSensorStats> = withContext(Dispatchers.IO) {
        appSensorStatsDao.getAllStats()
    }

    /**
     * Get apps with most background accesses
     */
    suspend fun getTopBackgroundAccessors(limit: Int = 10): List<AppSensorStats> = withContext(Dispatchers.IO) {
        appSensorStatsDao.getTopBackgroundAccessors(limit)
    }

    /**
     * Update daily sensor summary
     */
    suspend fun updateDailySummary(date: String) = withContext(Dispatchers.IO) {
        val startOfDay = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.getDefault())
            .parse(date)?.time ?: return@withContext

        val logs = sensorAccessLogDao.getLogsSince(startOfDay)
        
        val cameraCount = logs.count { it.sensorType == SensorType.CAMERA }
        val micCount = logs.count { it.sensorType == SensorType.MICROPHONE }
        val locationCount = logs.count { it.sensorType == SensorType.LOCATION }
        val backgroundCount = logs.count { it.wasInBackground }
        
        val uniqueCameraApps = logs.filter { it.sensorType == SensorType.CAMERA }.map { it.packageName }.distinct().size
        val uniqueMicApps = logs.filter { it.sensorType == SensorType.MICROPHONE }.map { it.packageName }.distinct().size
        val uniqueLocationApps = logs.filter { it.sensorType == SensorType.LOCATION }.map { it.packageName }.distinct().size
        
        val alertCount = privacyAlertDao.getRecentAlerts().count { 
            it.timestamp >= startOfDay && it.timestamp < startOfDay + 86400000 
        }

        val summary = DailySensorSummary(
            date = date,
            totalCameraAccesses = cameraCount,
            totalMicrophoneAccesses = micCount,
            totalLocationAccesses = locationCount,
            totalBackgroundAccesses = backgroundCount,
            uniqueAppsUsingCamera = uniqueCameraApps,
            uniqueAppsUsingMicrophone = uniqueMicApps,
            uniqueAppsUsingLocation = uniqueLocationApps,
            alertsTriggered = alertCount
        )

        dailySummaryDao.insertOrUpdate(summary)
    }

    /**
     * Get recent daily summaries for chart display
     */
    suspend fun getRecentDailySummaries(days: Int = 7): List<DailySensorSummary> = withContext(Dispatchers.IO) {
        dailySummaryDao.getRecentSummaries(days)
    }

    /**
     * Get recent sensor access logs as a Flow
     */
    fun getRecentSensorLogs(limit: Int = 100) = sensorAccessLogDao.getRecentLogsFlow(limit)

    /**
     * Clear all sensor logs
     */
    suspend fun clearSensorLogs() = withContext(Dispatchers.IO) {
        sensorAccessLogDao.deleteAllLogs()
    }

    /**
     * Delete a specific alert
     */
    suspend fun deleteAlert(alertId: Long) = withContext(Dispatchers.IO) {
        privacyAlertDao.deleteAlert(alertId)
    }

    /**
     * Clear all alerts
     */
    suspend fun clearAllAlerts() = withContext(Dispatchers.IO) {
        privacyAlertDao.deleteAllAlerts()
    }

    /**
     * Clear all guardian data
     */
    suspend fun clearAllData() = withContext(Dispatchers.IO) {
        sensorAccessLogDao.deleteAllLogs()
        privacyAlertDao.deleteAllAlerts()
        appSensorStatsDao.deleteAllStats()
        dailySummaryDao.deleteAllSummaries()
    }
}

/**
 * Repository for scanned app data
 */
@Singleton
class ScannerRepository @Inject constructor(
    private val scannedAppDao: ScannedAppDao
) {
    /**
     * Get all scanned apps
     */
    suspend fun getAllApps(): List<ScannedApp> = withContext(Dispatchers.IO) {
        scannedAppDao.getAllApps()
    }

    /**
     * Get high-risk apps
     */
    suspend fun getHighRiskApps(): List<ScannedApp> = withContext(Dispatchers.IO) {
        scannedAppDao.getHighRiskApps()
    }

    /**
     * Get app by package name
     */
    suspend fun getApp(packageName: String): ScannedApp? = withContext(Dispatchers.IO) {
        scannedAppDao.getApp(packageName)
    }

    /**
     * Save scanned app
     */
    suspend fun saveApp(app: ScannedApp) = withContext(Dispatchers.IO) {
        scannedAppDao.insertApp(app)
    }

    /**
     * Save multiple apps
     */
    suspend fun saveApps(apps: List<ScannedApp>) = withContext(Dispatchers.IO) {
        scannedAppDao.insertApps(apps)
    }

    /**
     * Get apps by risk level
     */
    suspend fun getAppsByRiskLevel(level: RiskLevel): List<ScannedApp> = withContext(Dispatchers.IO) {
        scannedAppDao.getAppsByRiskLevel(level)
    }

    /**
     * Clear all scan data
     */
    suspend fun clearAllData() = withContext(Dispatchers.IO) {
        scannedAppDao.deleteAllApps()
    }

    /**
     * Get total app count
     */
    suspend fun getAppCount(): Int = withContext(Dispatchers.IO) {
        scannedAppDao.getAppCount()
    }
}
