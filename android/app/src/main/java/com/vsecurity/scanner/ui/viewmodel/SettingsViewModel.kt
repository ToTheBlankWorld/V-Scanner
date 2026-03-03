package com.vsecurity.scanner.ui.viewmodel

import android.app.AppOpsManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Process
import android.provider.Settings
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vsecurity.scanner.data.preferences.PreferencesManager
import com.vsecurity.scanner.data.repository.GuardianRepository
import com.vsecurity.scanner.data.repository.ScannerRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

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
        checkPermissions()
    }

    /**
     * Re-check permission status. Call this when the screen resumes
     * (e.g. after the user returns from system settings).
     */
    fun refreshPermissions() {
        checkPermissions()
    }

    private fun checkPermissions() {
        val hasUsageStats = try {
            val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
            val mode = appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                context.packageName
            )
            mode == AppOpsManager.MODE_ALLOWED
        } catch (_: Exception) { false }

        val hasNotification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(
                context,
                android.Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true
        }

        _uiState.update {
            it.copy(
                hasUsageStatsPermission = hasUsageStats,
                hasNotificationPermission = hasNotification
            )
        }
    }

    private fun loadSettings() {
        viewModelScope.launch {
            combine(
                preferencesManager.includeSystemApps,
                preferencesManager.guardianEnabled,
                preferencesManager.startOnBoot,
                preferencesManager.frequentThreshold,
                preferencesManager.darkTheme
            ) { includeSystem, guardian, boot, threshold, dark ->
                _uiState.update {
                    it.copy(
                        includeSystemApps = includeSystem,
                        guardianEnabled = guardian,
                        startOnBoot = boot,
                        frequentThreshold = threshold,
                        darkTheme = dark
                    )
                }
            }.collect()
        }
    }

    fun setIncludeSystemApps(enabled: Boolean) {
        viewModelScope.launch { preferencesManager.setIncludeSystemApps(enabled) }
    }

    fun setGuardianEnabled(enabled: Boolean) {
        viewModelScope.launch { preferencesManager.setGuardianEnabled(enabled) }
    }

    fun setStartOnBoot(enabled: Boolean) {
        viewModelScope.launch { preferencesManager.setStartOnBoot(enabled) }
    }

    fun setFrequentThreshold(threshold: Int) {
        viewModelScope.launch { preferencesManager.setFrequentThreshold(threshold) }
    }

    fun setDarkTheme(dark: Boolean) {
        viewModelScope.launch { preferencesManager.setDarkTheme(dark) }
    }

    fun clearScanHistory() {
        viewModelScope.launch { scannerRepository.clearAllData() }
    }

    fun clearSensorLogs() {
        viewModelScope.launch { guardianRepository.clearSensorLogs() }
    }

    fun clearAllAlerts() {
        viewModelScope.launch { guardianRepository.clearAllAlerts() }
    }

    fun clearAllData() {
        viewModelScope.launch {
            scannerRepository.clearAllData()
            guardianRepository.clearAllData()
        }
    }
}

data class SettingsUiState(
    val hasUsageStatsPermission: Boolean = false,
    val hasNotificationPermission: Boolean = true,
    val includeSystemApps: Boolean = false,
    val guardianEnabled: Boolean = false,
    val startOnBoot: Boolean = false,
    val frequentThreshold: Int = 10,
    val darkTheme: Boolean = true
)
