package com.vsecurity.scanner.data.local

import androidx.room.*
import com.vsecurity.scanner.data.model.*
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.flow.Flow

/**
 * Room Database for V Scanner
 */
@Database(
    entities = [
        ScannedApp::class,
        SensorAccessLog::class,
        PrivacyAlert::class,
        AppSensorStats::class,
        DailySensorSummary::class
    ],
    version = 1,
    exportSchema = false
)
@TypeConverters(Converters::class)
abstract class VScannerDatabase : RoomDatabase() {
    abstract fun scannedAppDao(): ScannedAppDao
    abstract fun sensorAccessLogDao(): SensorAccessLogDao
    abstract fun privacyAlertDao(): PrivacyAlertDao
    abstract fun appSensorStatsDao(): AppSensorStatsDao
    abstract fun dailySummaryDao(): DailySummaryDao
}

/**
 * Type converters for complex types
 */
class Converters {
    private val gson = Gson()

    @TypeConverter
    fun fromStringList(value: List<String>): String {
        return gson.toJson(value)
    }

    @TypeConverter
    fun toStringList(value: String): List<String> {
        val type = object : TypeToken<List<String>>() {}.type
        return gson.fromJson(value, type) ?: emptyList()
    }

    @TypeConverter
    fun fromDangerousPermissionList(value: List<DangerousPermission>): String {
        return gson.toJson(value)
    }

    @TypeConverter
    fun toDangerousPermissionList(value: String): List<DangerousPermission> {
        val type = object : TypeToken<List<DangerousPermission>>() {}.type
        return gson.fromJson(value, type) ?: emptyList()
    }

    @TypeConverter
    fun fromRiskLevel(value: RiskLevel): String {
        return value.name
    }

    @TypeConverter
    fun toRiskLevel(value: String): RiskLevel {
        return RiskLevel.valueOf(value)
    }

    @TypeConverter
    fun fromSensorType(value: SensorType): String {
        return value.name
    }

    @TypeConverter
    fun toSensorType(value: String): SensorType {
        return SensorType.valueOf(value)
    }

    @TypeConverter
    fun fromAlertType(value: AlertType): String {
        return value.name
    }

    @TypeConverter
    fun toAlertType(value: String): AlertType {
        return AlertType.valueOf(value)
    }

    @TypeConverter
    fun fromPermissionCategory(value: PermissionCategory): String {
        return value.name
    }

    @TypeConverter
    fun toPermissionCategory(value: String): PermissionCategory {
        return PermissionCategory.valueOf(value)
    }
}

/**
 * DAO for scanned apps
 */
@Dao
interface ScannedAppDao {
    @Query("SELECT * FROM scanned_apps ORDER BY riskScore DESC")
    suspend fun getAllApps(): List<ScannedApp>

    @Query("SELECT * FROM scanned_apps WHERE packageName = :packageName")
    suspend fun getApp(packageName: String): ScannedApp?

    @Query("SELECT * FROM scanned_apps WHERE riskLevel IN ('CRITICAL', 'HIGH') ORDER BY riskScore DESC")
    suspend fun getHighRiskApps(): List<ScannedApp>

    @Query("SELECT COUNT(*) FROM scanned_apps")
    suspend fun getAppCount(): Int

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertApp(app: ScannedApp)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertApps(apps: List<ScannedApp>)

    @Delete
    suspend fun deleteApp(app: ScannedApp)

    @Query("DELETE FROM scanned_apps")
    suspend fun deleteAllApps()

    @Query("SELECT * FROM scanned_apps WHERE riskLevel = :level ORDER BY riskScore DESC")
    suspend fun getAppsByRiskLevel(level: RiskLevel): List<ScannedApp>
}

/**
 * DAO for sensor access logs
 */
@Dao
interface SensorAccessLogDao {
    @Query("SELECT * FROM sensor_access_logs ORDER BY accessTime DESC LIMIT :limit")
    suspend fun getRecentLogs(limit: Int = 100): List<SensorAccessLog>

    @Query("SELECT * FROM sensor_access_logs WHERE packageName = :packageName ORDER BY accessTime DESC LIMIT :limit")
    suspend fun getLogsForApp(packageName: String, limit: Int = 50): List<SensorAccessLog>

    @Query("SELECT * FROM sensor_access_logs WHERE sensorType = :sensorType ORDER BY accessTime DESC LIMIT :limit")
    suspend fun getLogsBySensorType(sensorType: SensorType, limit: Int = 50): List<SensorAccessLog>

    @Query("SELECT * FROM sensor_access_logs WHERE isSuspicious = 1 ORDER BY accessTime DESC LIMIT :limit")
    suspend fun getSuspiciousLogs(limit: Int = 50): List<SensorAccessLog>

    @Query("SELECT * FROM sensor_access_logs WHERE accessTime > :startTime")
    suspend fun getLogsSince(startTime: Long): List<SensorAccessLog>

    @Insert
    suspend fun insertLog(log: SensorAccessLog)

    @Query("DELETE FROM sensor_access_logs WHERE accessTime < :beforeTime")
    suspend fun deleteOldLogs(beforeTime: Long)

    @Query("SELECT * FROM sensor_access_logs ORDER BY accessTime DESC LIMIT :limit")
    fun getRecentLogsFlow(limit: Int = 100): kotlinx.coroutines.flow.Flow<List<SensorAccessLog>>

    @Query("DELETE FROM sensor_access_logs")
    suspend fun deleteAllLogs()
}

/**
 * DAO for privacy alerts
 */
@Dao
interface PrivacyAlertDao {
    @Query("SELECT * FROM privacy_alerts ORDER BY timestamp DESC LIMIT :limit")
    suspend fun getRecentAlerts(limit: Int = 50): List<PrivacyAlert>

    @Query("SELECT * FROM privacy_alerts WHERE wasAcknowledged = 0 ORDER BY timestamp DESC")
    suspend fun getUnacknowledgedAlerts(): List<PrivacyAlert>

    @Query("SELECT COUNT(*) FROM privacy_alerts WHERE wasAcknowledged = 0")
    suspend fun getUnacknowledgedCount(): Int

    @Insert
    suspend fun insertAlert(alert: PrivacyAlert)

    @Query("UPDATE privacy_alerts SET wasAcknowledged = 1 WHERE id = :alertId")
    suspend fun acknowledgeAlert(alertId: Long)

    @Query("UPDATE privacy_alerts SET wasAcknowledged = 1")
    suspend fun acknowledgeAllAlerts()

    @Query("DELETE FROM privacy_alerts WHERE timestamp < :beforeTime")
    suspend fun deleteOldAlerts(beforeTime: Long)

    @Query("DELETE FROM privacy_alerts")
    suspend fun deleteAllAlerts()

    @Query("DELETE FROM privacy_alerts WHERE id = :alertId")
    suspend fun deleteAlert(alertId: Long)
}

/**
 * DAO for app sensor statistics
 */
@Dao
interface AppSensorStatsDao {
    @Query("SELECT * FROM app_sensor_stats ORDER BY (cameraAccessCount + microphoneAccessCount + locationAccessCount) DESC")
    suspend fun getAllStats(): List<AppSensorStats>

    @Query("SELECT * FROM app_sensor_stats WHERE packageName = :packageName")
    suspend fun getStatsForApp(packageName: String): AppSensorStats?

    @Query("SELECT * FROM app_sensor_stats ORDER BY totalBackgroundAccesses DESC LIMIT :limit")
    suspend fun getTopBackgroundAccessors(limit: Int = 10): List<AppSensorStats>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrUpdate(stats: AppSensorStats)

    @Query("DELETE FROM app_sensor_stats")
    suspend fun deleteAll()

    @Query("DELETE FROM app_sensor_stats")
    suspend fun deleteAllStats()
}

/**
 * DAO for daily sensor summaries
 */
@Dao
interface DailySummaryDao {
    @Query("SELECT * FROM daily_sensor_summary ORDER BY date DESC LIMIT :days")
    suspend fun getRecentSummaries(days: Int = 7): List<DailySensorSummary>

    @Query("SELECT * FROM daily_sensor_summary WHERE date = :date")
    suspend fun getSummaryForDate(date: String): DailySensorSummary?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertOrUpdate(summary: DailySensorSummary)

    @Query("DELETE FROM daily_sensor_summary WHERE date < :beforeDate")
    suspend fun deleteOldSummaries(beforeDate: String)

    @Query("DELETE FROM daily_sensor_summary")
    suspend fun deleteAllSummaries()
}
