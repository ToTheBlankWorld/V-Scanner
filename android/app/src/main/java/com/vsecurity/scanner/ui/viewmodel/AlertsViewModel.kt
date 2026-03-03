package com.vsecurity.scanner.ui.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vsecurity.scanner.data.model.PrivacyAlert
import com.vsecurity.scanner.data.model.SensorType
import com.vsecurity.scanner.data.repository.GuardianRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class AlertsViewModel @Inject constructor(
    private val guardianRepository: GuardianRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(AlertsUiState())
    val uiState: StateFlow<AlertsUiState> = _uiState.asStateFlow()

    init {
        loadAlerts()
    }

    fun loadAlerts() {
        viewModelScope.launch {
            try {
                val alerts = guardianRepository.getRecentAlerts(100)
                val unacknowledgedCount = guardianRepository.getUnacknowledgedAlertCount()

                _uiState.update { state ->
                    state.copy(
                        alerts = alerts,
                        unacknowledgedCount = unacknowledgedCount
                    )
                }
            } catch (_: Exception) { }
        }
    }

    fun setFilter(filter: SensorType?) {
        _uiState.update { it.copy(selectedFilter = filter) }
    }

    fun acknowledgeAlert(alertId: Long) {
        viewModelScope.launch {
            guardianRepository.acknowledgeAlert(alertId)
            loadAlerts()
        }
    }

    fun acknowledgeAll() {
        viewModelScope.launch {
            guardianRepository.acknowledgeAllAlerts()
            loadAlerts()
        }
    }

    fun deleteAlert(alertId: Long) {
        viewModelScope.launch {
            guardianRepository.deleteAlert(alertId)
            loadAlerts()
        }
    }

    fun clearAllAlerts() {
        viewModelScope.launch {
            guardianRepository.clearAllAlerts()
            _uiState.update {
                it.copy(alerts = emptyList(), unacknowledgedCount = 0)
            }
        }
    }
}

data class AlertsUiState(
    val alerts: List<PrivacyAlert> = emptyList(),
    val selectedFilter: SensorType? = null,
    val unacknowledgedCount: Int = 0
)
