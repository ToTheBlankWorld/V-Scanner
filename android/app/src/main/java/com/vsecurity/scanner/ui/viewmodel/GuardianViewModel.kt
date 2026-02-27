package com.vsecurity.scanner.ui.viewmodel

import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vsecurity.scanner.data.model.GuardianSettings
import com.vsecurity.scanner.data.model.SensorAccessLog
import com.vsecurity.scanner.data.model.SensorType
import com.vsecurity.scanner.data.preferences.PreferencesManager
import com.vsecurity.scanner.data.repository.GuardianRepository
import com.vsecurity.scanner.guardian.PrivacyGuardianService
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import java.util.Date
import javax.inject.Inject

/**
 * Guardian ViewModel
 */
@HiltViewModel
class GuardianViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val guardianRepository: GuardianRepository,
    private val preferencesManager: PreferencesManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(GuardianUiState())
    val uiState: StateFlow<GuardianUiState> = _uiState.asStateFlow()

    init {
        loadState()
        observeSensorLogs()
    }

    private fun loadState() {
        viewModelScope.launch {
            combine(
                preferencesManager.guardianEnabled,
                preferencesManager.guardianSettings
            ) { enabled, settings ->
                _uiState.update {
                    it.copy(
                        isEnabled = enabled,
                        settings = settings
                    )
                }
            }.collect()
        }
    }

    private fun observeSensorLogs() {
        viewModelScope.launch {
            guardianRepository.getRecentSensorLogs(100).collect { logs ->
                _uiState.update { it.copy(recentLogs = logs) }
            }
        }
    }

    fun toggleGuardian(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setGuardianEnabled(enabled)
            
            if (enabled) {
                startGuardianService()
            } else {
                stopGuardianService()
            }
            
            _uiState.update { it.copy(isEnabled = enabled) }
        }
    }

    private fun startGuardianService() {
        val intent = Intent(context, PrivacyGuardianService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent)
        } else {
            context.startService(intent)
        }
    }

    private fun stopGuardianService() {
        val intent = Intent(context, PrivacyGuardianService::class.java)
        context.stopService(intent)
    }

    fun updateSettings(settings: GuardianSettings) {
        viewModelScope.launch {
            preferencesManager.setGuardianSettings(settings)
            _uiState.update { it.copy(settings = settings) }
        }
    }

    fun toggleSensorMonitoring(sensorType: SensorType, enabled: Boolean) {
        val currentSettings = _uiState.value.settings
        val newSettings = when (sensorType) {
            SensorType.CAMERA -> currentSettings.copy(monitorCamera = enabled)
            SensorType.MICROPHONE -> currentSettings.copy(monitorMicrophone = enabled)
            SensorType.LOCATION -> currentSettings.copy(monitorLocation = enabled)
        }
        updateSettings(newSettings)
    }

    fun getSensorUsageByType(): Map<SensorType, List<SensorAccessLog>> {
        return _uiState.value.recentLogs.groupBy { it.sensorType }
    }

    fun getTodaySensorUsage(): List<SensorAccessLog> {
        val today = Date()
        val startOfDay = java.util.Calendar.getInstance().apply {
            time = today
            set(java.util.Calendar.HOUR_OF_DAY, 0)
            set(java.util.Calendar.MINUTE, 0)
            set(java.util.Calendar.SECOND, 0)
            set(java.util.Calendar.MILLISECOND, 0)
        }.time
        
        return _uiState.value.recentLogs.filter { it.timestamp >= startOfDay }
    }

    fun clearLogs() {
        viewModelScope.launch {
            guardianRepository.clearAllData()
            _uiState.update { it.copy(recentLogs = emptyList()) }
        }
    }
}

data class GuardianUiState(
    val isEnabled: Boolean = false,
    val settings: GuardianSettings = GuardianSettings(),
    val recentLogs: List<SensorAccessLog> = emptyList()
)
