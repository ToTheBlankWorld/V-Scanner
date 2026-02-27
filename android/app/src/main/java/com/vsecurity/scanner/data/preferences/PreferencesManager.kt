package com.vsecurity.scanner.data.preferences

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "vscanner_preferences")

/**
 * Manages app preferences using DataStore
 */
@Singleton
class PreferencesManager @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val dataStore = context.dataStore

    companion object {
        // Guardian Settings
        val GUARDIAN_ENABLED = booleanPreferencesKey("guardian_enabled")
        val MONITOR_CAMERA = booleanPreferencesKey("monitor_camera")
        val MONITOR_MICROPHONE = booleanPreferencesKey("monitor_microphone")
        val MONITOR_LOCATION = booleanPreferencesKey("monitor_location")
        val ALERT_ON_BACKGROUND = booleanPreferencesKey("alert_on_background")
        val ALERT_ON_SCREEN_OFF = booleanPreferencesKey("alert_on_screen_off")
        val ALERT_ON_FREQUENT = booleanPreferencesKey("alert_on_frequent")
        val FREQUENT_THRESHOLD = intPreferencesKey("frequent_threshold")
        val WHITELISTED_APPS = stringSetPreferencesKey("whitelisted_apps")
        
        // Scanner Settings
        val INCLUDE_SYSTEM_APPS = booleanPreferencesKey("include_system_apps")
        val AUTO_SCAN_ON_INSTALL = booleanPreferencesKey("auto_scan_on_install")
        val LAST_SCAN_TIME = longPreferencesKey("last_scan_time")
        
        // UI Settings
        val DARK_THEME = booleanPreferencesKey("dark_theme")
        val FIRST_LAUNCH = booleanPreferencesKey("first_launch")
    }

    // Guardian Settings
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

    // Scanner Settings
    val includeSystemApps: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[INCLUDE_SYSTEM_APPS] ?: false }

    val lastScanTime: Flow<Long> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[LAST_SCAN_TIME] ?: 0L }

    // UI Settings
    val darkTheme: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[DARK_THEME] ?: true }

    val firstLaunch: Flow<Boolean> = dataStore.data
        .catch { if (it is IOException) emit(emptyPreferences()) else throw it }
        .map { it[FIRST_LAUNCH] ?: true }

    // Update functions
    suspend fun setGuardianEnabled(enabled: Boolean) {
        dataStore.edit { it[GUARDIAN_ENABLED] = enabled }
    }

    suspend fun setMonitorCamera(enabled: Boolean) {
        dataStore.edit { it[MONITOR_CAMERA] = enabled }
    }

    suspend fun setMonitorMicrophone(enabled: Boolean) {
        dataStore.edit { it[MONITOR_MICROPHONE] = enabled }
    }

    suspend fun setMonitorLocation(enabled: Boolean) {
        dataStore.edit { it[MONITOR_LOCATION] = enabled }
    }

    suspend fun setAlertOnBackground(enabled: Boolean) {
        dataStore.edit { it[ALERT_ON_BACKGROUND] = enabled }
    }

    suspend fun setAlertOnScreenOff(enabled: Boolean) {
        dataStore.edit { it[ALERT_ON_SCREEN_OFF] = enabled }
    }

    suspend fun setAlertOnFrequent(enabled: Boolean) {
        dataStore.edit { it[ALERT_ON_FREQUENT] = enabled }
    }

    suspend fun setFrequentThreshold(threshold: Int) {
        dataStore.edit { it[FREQUENT_THRESHOLD] = threshold }
    }

    suspend fun setWhitelistedApps(apps: Set<String>) {
        dataStore.edit { it[WHITELISTED_APPS] = apps }
    }

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

    suspend fun setIncludeSystemApps(include: Boolean) {
        dataStore.edit { it[INCLUDE_SYSTEM_APPS] = include }
    }

    suspend fun setLastScanTime(time: Long) {
        dataStore.edit { it[LAST_SCAN_TIME] = time }
    }

    suspend fun setDarkTheme(dark: Boolean) {
        dataStore.edit { it[DARK_THEME] = dark }
    }

    suspend fun setFirstLaunch(first: Boolean) {
        dataStore.edit { it[FIRST_LAUNCH] = first }
    }
}
