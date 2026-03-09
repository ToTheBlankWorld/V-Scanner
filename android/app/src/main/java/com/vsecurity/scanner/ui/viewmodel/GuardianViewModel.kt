package com.vsecurity.scanner.ui.viewmodel

import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vsecurity.scanner.data.model.AppSensorStats
import com.vsecurity.scanner.data.model.DailySensorSummary
import com.vsecurity.scanner.data.model.SensorAccessLog
import com.vsecurity.scanner.data.preferences.PreferencesManager
import com.vsecurity.scanner.data.repository.GuardianRepository
import com.vsecurity.scanner.guardian.PrivacyGuardianService
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

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
        loadActivityData()
        // Periodically refresh activity data while guardian is active
        startPeriodicRefresh()
    }

    private fun startPeriodicRefresh() {
        viewModelScope.launch {
            while (true) {
                delay(15_000) // Refresh every 15 seconds
                if (_uiState.value.isGuardianActive) {
                    loadActivityData()
                }
            }
        }
    }

    private fun loadState() {
        viewModelScope.launch {
            combine(
                preferencesManager.guardianEnabled,
                preferencesManager.monitorCamera,
                preferencesManager.monitorMicrophone,
                preferencesManager.monitorLocation,
                preferencesManager.alertOnBackground
            ) { enabled, camera, mic, location, background ->
                _uiState.update {
                    it.copy(
                        isGuardianActive = enabled,
                        monitorCamera = camera,
                        monitorMicrophone = mic,
                        monitorLocation = location,
                        alertOnBackground = background
                    )
                }
            }.collect()
        }
        viewModelScope.launch {
            combine(
                preferencesManager.alertOnScreenOff,
                preferencesManager.alertOnFrequent
            ) { screenOff, frequent ->
                _uiState.update {
                    it.copy(
                        alertOnScreenOff = screenOff,
                        alertOnFrequent = frequent
                    )
                }
            }.collect()
        }
    }

    private fun loadActivityData() {
        viewModelScope.launch {
            try {
                val appStats = guardianRepository.getAllAppStats()
                val dailySummaries = guardianRepository.getRecentDailySummaries(7)
                _uiState.update {
                    it.copy(
                        recentlyActiveApps = appStats,
                        dailySummaries = dailySummaries
                    )
                }
            } catch (_: Exception) { }
        }
    }

    fun toggleGuardian() {
        val newState = !_uiState.value.isGuardianActive
        viewModelScope.launch {
            preferencesManager.setGuardianEnabled(newState)
            if (newState) {
                val intent = Intent(context, PrivacyGuardianService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            } else {
                context.stopService(Intent(context, PrivacyGuardianService::class.java))
            }
            _uiState.update { it.copy(isGuardianActive = newState) }
        }
    }

    fun setMonitorCamera(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setMonitorCamera(enabled)
            _uiState.update { it.copy(monitorCamera = enabled) }
        }
    }

    fun setMonitorMicrophone(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setMonitorMicrophone(enabled)
            _uiState.update { it.copy(monitorMicrophone = enabled) }
        }
    }

    fun setMonitorLocation(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setMonitorLocation(enabled)
            _uiState.update { it.copy(monitorLocation = enabled) }
        }
    }

    fun setAlertOnBackground(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setAlertOnBackground(enabled)
            _uiState.update { it.copy(alertOnBackground = enabled) }
        }
    }

    fun setAlertOnScreenOff(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setAlertOnScreenOff(enabled)
            _uiState.update { it.copy(alertOnScreenOff = enabled) }
        }
    }

    fun setAlertOnFrequent(enabled: Boolean) {
        viewModelScope.launch {
            preferencesManager.setAlertOnFrequent(enabled)
            _uiState.update { it.copy(alertOnFrequent = enabled) }
        }
    }

    fun refresh() {
        loadActivityData()
    }
}

data class GuardianUiState(
    val isGuardianActive: Boolean = false,
    val monitorCamera: Boolean = true,
    val monitorMicrophone: Boolean = true,
    val monitorLocation: Boolean = true,
    val alertOnBackground: Boolean = true,
    val alertOnScreenOff: Boolean = true,
    val alertOnFrequent: Boolean = true,
    val recentlyActiveApps: List<AppSensorStats> = emptyList(),
    val dailySummaries: List<DailySensorSummary> = emptyList()
)
