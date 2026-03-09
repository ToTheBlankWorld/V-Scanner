package com.vsecurity.scanner.data.preferences

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import com.vsecurity.scanner.data.model.GuardianSettings
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "vscanner_preferences")

@Singleton
class PreferencesManager @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val dataStore = context.dataStore

    companion object {
        val GUARDIAN_ENABLED = booleanPreferencesKey("guardian_enabled")
        val MONITOR_CAMERA = booleanPreferencesKey("monitor_camera")
        val MONITOR_MICROPHONE = booleanPreferencesKey("monitor_microphone")
        val MONITOR_LOCATION = booleanPreferencesKey("monitor_location")
        val ALERT_ON_BACKGROUND = booleanPreferencesKey("alert_on_background")
        val ALERT_ON_SCREEN_OFF = booleanPreferencesKey("alert_on_screen_off")
        val ALERT_ON_FREQUENT = booleanPreferencesKey("alert_on_frequent")
        val FREQUENT_THRESHOLD = intPreferencesKey("frequent_threshold")
        val WHITELISTED_APPS = stringSetPreferencesKey("whitelisted_apps")
        val INCLUDE_SYSTEM_APPS = booleanPreferencesKey("include_system_apps")
        val AUTO_SCAN_ON_INSTALL = booleanPreferencesKey("auto_scan_on_install")
        val LAST_SCAN_TIME = longPreferencesKey("last_scan_time")
        val DARK_THEME = booleanPreferencesKey("dark_theme")
        val FIRST_LAUNCH = booleanPreferencesKey("first_launch")
        val START_ON_BOOT = booleanPreferencesKey("start_on_boot")
        val NOTIFICATIONS_ENABLED = booleanPreferencesKey("notifications_enabled")
    }

    val guardianEnabled: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[GUARDIAN_ENABLED] ?: false }

    val monitorCamera: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[MONITOR_CAMERA] ?: true }

    val monitorMicrophone: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[MONITOR_MICROPHONE] ?: true }

    val monitorLocation: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[MONITOR_LOCATION] ?: true }

    val alertOnBackground: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[ALERT_ON_BACKGROUND] ?: true }

    val alertOnScreenOff: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[ALERT_ON_SCREEN_OFF] ?: true }

    val alertOnFrequent: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[ALERT_ON_FREQUENT] ?: true }

    val frequentThreshold: Flow<Int> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[FREQUENT_THRESHOLD] ?: 10 }

    val whitelistedApps: Flow<Set<String>> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[WHITELISTED_APPS] ?: emptySet() }

    val includeSystemApps: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[INCLUDE_SYSTEM_APPS] ?: false }

    val autoScanEnabled: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[AUTO_SCAN_ON_INSTALL] ?: true }

    val lastScanTime: Flow<Long> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[LAST_SCAN_TIME] ?: 0L }

    val darkTheme: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[DARK_THEME] ?: true }

    val firstLaunch: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[FIRST_LAUNCH] ?: true }

    val startOnBoot: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[START_ON_BOOT] ?: false }

    val notificationsEnabled: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[NOTIFICATIONS_ENABLED] ?: true }

    val guardianSettings: Flow<GuardianSettings> = combine(
        monitorCamera, monitorMicrophone, monitorLocation, alertOnBackground, alertOnScreenOff
    ) { camera, mic, location, background, screenOff ->
        GuardianSettings(
            isEnabled = true,
            monitorCamera = camera,
            monitorMicrophone = mic,
            monitorLocation = location,
            alertOnBackgroundAccess = background,
            alertOnScreenOffAccess = screenOff
        )
    }.combine(combine(alertOnFrequent, frequentThreshold, whitelistedApps) { frequent, threshold, whitelist ->
        Triple(frequent, threshold, whitelist)
    }) { settings, (frequent, threshold, whitelist) ->
        settings.copy(
            alertOnFrequentAccess = frequent,
            frequentAccessThreshold = threshold,
            whitelistedApps = whitelist
        )
    }

    suspend fun setGuardianEnabled(enabled: Boolean) { dataStore.edit { it[GUARDIAN_ENABLED] = enabled } }
    suspend fun setMonitorCamera(enabled: Boolean) { dataStore.edit { it[MONITOR_CAMERA] = enabled } }
    suspend fun setMonitorMicrophone(enabled: Boolean) { dataStore.edit { it[MONITOR_MICROPHONE] = enabled } }
    suspend fun setMonitorLocation(enabled: Boolean) { dataStore.edit { it[MONITOR_LOCATION] = enabled } }
    suspend fun setAlertOnBackground(enabled: Boolean) { dataStore.edit { it[ALERT_ON_BACKGROUND] = enabled } }
    suspend fun setAlertOnScreenOff(enabled: Boolean) { dataStore.edit { it[ALERT_ON_SCREEN_OFF] = enabled } }
    suspend fun setAlertOnFrequent(enabled: Boolean) { dataStore.edit { it[ALERT_ON_FREQUENT] = enabled } }
    suspend fun setFrequentThreshold(threshold: Int) { dataStore.edit { it[FREQUENT_THRESHOLD] = threshold } }
    suspend fun setWhitelistedApps(apps: Set<String>) { dataStore.edit { it[WHITELISTED_APPS] = apps } }
    suspend fun setIncludeSystemApps(include: Boolean) { dataStore.edit { it[INCLUDE_SYSTEM_APPS] = include } }
    suspend fun setAutoScanEnabled(enabled: Boolean) { dataStore.edit { it[AUTO_SCAN_ON_INSTALL] = enabled } }
    suspend fun setLastScanTime(time: Long) { dataStore.edit { it[LAST_SCAN_TIME] = time } }
    suspend fun setDarkTheme(dark: Boolean) { dataStore.edit { it[DARK_THEME] = dark } }
    suspend fun setFirstLaunch(first: Boolean) { dataStore.edit { it[FIRST_LAUNCH] = first } }
    suspend fun setStartOnBoot(enabled: Boolean) { dataStore.edit { it[START_ON_BOOT] = enabled } }
    suspend fun setNotificationsEnabled(enabled: Boolean) { dataStore.edit { it[NOTIFICATIONS_ENABLED] = enabled } }

    suspend fun addWhitelistedApp(packageName: String) {
        dataStore.edit { prefs ->
            val current = prefs[WHITELISTED_APPS] ?: emptySet()
            prefs[WHITELISTED_APPS] = current + packageName
        }
    }

    suspend fun removeWhitelistedApp(packageName: String) {
        dataStore.edit { prefs ->
            val current = prefs[WHITELISTED_APPS] ?: emptySet()
            prefs[WHITELISTED_APPS] = current - packageName
        }
    }

    suspend fun setGuardianSettings(settings: GuardianSettings) {
        dataStore.edit { prefs ->
            prefs[MONITOR_CAMERA] = settings.monitorCamera
            prefs[MONITOR_MICROPHONE] = settings.monitorMicrophone
            prefs[MONITOR_LOCATION] = settings.monitorLocation
            prefs[ALERT_ON_BACKGROUND] = settings.alertOnBackgroundAccess
            prefs[ALERT_ON_SCREEN_OFF] = settings.alertOnScreenOffAccess
            prefs[ALERT_ON_FREQUENT] = settings.alertOnFrequentAccess
            prefs[FREQUENT_THRESHOLD] = settings.frequentAccessThreshold
            prefs[WHITELISTED_APPS] = settings.whitelistedApps
        }
    }
}
