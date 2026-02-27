package com.vsecurity.scanner.ui.viewmodel

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vsecurity.scanner.data.model.GuardianSettings
import com.vsecurity.scanner.data.preferences.PreferencesManager
import com.vsecurity.scanner.data.repository.GuardianRepository
import com.vsecurity.scanner.data.repository.ScannerRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Settings ViewModel
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val preferencesManager: PreferencesManager,
    private val scannerRepository: ScannerRepository,
    private val guardianRepository: GuardianRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(SettingsUiState())
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        loadSettings()
    }

    private fun loadSettings() {
        viewModelScope.launch {
            combine(
                preferencesManager.includeSystemApps,
                preferencesManager.autoScanEnabled,
                preferencesManager.guardianEnabled,
                preferencesManager.notificationsEnabled,
                preferencesManager.guardianSettings
            ) { includeSystem, autoScan, guardian, notifications, guardianSettings ->
                SettingsUiState(
                    includeSystemApps = includeSystem,
                    autoScanEnabled = autoScan,
                    guardianEnabled = guardian,
                    notificationsEnabled = notifications,
                    guardianSettings = guardianSettings
                )
            }.collect { state ->
                _uiState.value = state
            }
        }
    }

    fun setIncludeSystemApps(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setIncludeSystemApps(enabled)
        }
    }

    fun setAutoScanEnabled(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setAutoScanEnabled(enabled)
        }
    }

    fun setNotificationsEnabled(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setNotificationsEnabled(enabled)
        }
    }

    fun setGuardianEnabled(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setGuardianEnabled(enabled)
        }
    }

    fun updateGuardianSettings(settings: GuardianSettings) {
        viewModelScope.launch {
            preferencesManager.setGuardianSettings(settings)
        }
    }

    fun clearScanHistory() {
        viewModelScope.launch {
            scannerRepository.clearAllData()
            _uiState.update { it.copy(showMessage = "Scan history cleared") }
        }
    }

    fun clearSensorLogs() {
        viewModelScope.launch {
            guardianRepository.clearSensorLogs()
            _uiState.update { it.copy(showMessage = "Sensor logs cleared") }
        }
    }

    fun clearAllAlerts() {
        viewModelScope.launch {
            guardianRepository.clearAllAlerts()
            _uiState.update { it.copy(showMessage = "All alerts cleared") }
        }
    }

    fun clearAllData() {
        viewModelScope.launch {
            scannerRepository.clearAllData()
            guardianRepository.clearAllData()
            _uiState.update { it.copy(showMessage = "All data cleared") }
        }
    }

    fun openAppSettings() {
        val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
            data = Uri.fromParts("package", context.packageName, null)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        context.startActivity(intent)
    }

    fun openUsageAccessSettings() {
        val intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        context.startActivity(intent)
    }

    fun dismissMessage() {
        _uiState.update { it.copy(showMessage = null) }
    }

    fun exportData(): String {
        // Returns a summary for now - could be expanded to export actual JSON
        return """
            V Scanner Data Export
            ---------------------
            Scanned Apps: ${_uiState.value.appCount}
            Sensor Logs: ${_uiState.value.sensorLogCount}
            Alerts: ${_uiState.value.alertCount}
        """.trimIndent()
    }
}

data class SettingsUiState(
    val includeSystemApps: Boolean = false,
    val autoScanEnabled: Boolean = true,
    val guardianEnabled: Boolean = false,
    val notificationsEnabled: Boolean = true,
    val guardianSettings: GuardianSettings = GuardianSettings(),
    val showMessage: String? = null,
    val appCount: Int = 0,
    val sensorLogCount: Int = 0,
    val alertCount: Int = 0
)
