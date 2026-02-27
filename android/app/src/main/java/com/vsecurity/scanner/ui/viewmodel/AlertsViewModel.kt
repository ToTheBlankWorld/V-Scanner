package com.vsecurity.scanner.ui.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vsecurity.scanner.data.model.AlertType
import com.vsecurity.scanner.data.model.PrivacyAlert
import com.vsecurity.scanner.data.repository.GuardianRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Alerts ViewModel
 */
@HiltViewModel
class AlertsViewModel @Inject constructor(
    private val guardianRepository: GuardianRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(AlertsUiState())
    val uiState: StateFlow<AlertsUiState> = _uiState.asStateFlow()

    init {
        observeAlerts()
    }

    private fun observeAlerts() {
        viewModelScope.launch {
            guardianRepository.getUnacknowledgedAlerts().collect { alerts ->
                val allAlerts = alerts.sortedByDescending { it.timestamp }
                _uiState.update { state ->
                    state.copy(
                        alerts = applyFilter(allAlerts, state.selectedFilter),
                        allAlerts = allAlerts,
                        unreadCount = alerts.count { !it.isAcknowledged }
                    )
                }
            }
        }
    }

    private fun applyFilter(alerts: List<PrivacyAlert>, filter: AlertType?): List<PrivacyAlert> {
        return if (filter == null) {
            alerts
        } else {
            alerts.filter { it.alertType == filter }
        }
    }

    fun setFilter(filter: AlertType?) {
        _uiState.update { state ->
            state.copy(
                selectedFilter = filter,
                alerts = applyFilter(state.allAlerts, filter)
            )
        }
    }

    fun acknowledgeAlert(alertId: Long) {
        viewModelScope.launch {
            guardianRepository.acknowledgeAlert(alertId)
        }
    }

    fun acknowledgeAll() {
        viewModelScope.launch {
            _uiState.value.alerts.forEach { alert ->
                guardianRepository.acknowledgeAlert(alert.id)
            }
        }
    }

    fun deleteAlert(alertId: Long) {
        viewModelScope.launch {
            guardianRepository.deleteAlert(alertId)
        }
    }

    fun clearAllAlerts() {
        viewModelScope.launch {
            guardianRepository.clearAllAlerts()
            _uiState.update { it.copy(alerts = emptyList(), allAlerts = emptyList(), unreadCount = 0) }
        }
    }

    fun getAlertsByApp(): Map<String, List<PrivacyAlert>> {
        return _uiState.value.allAlerts.groupBy { it.appPackageName }
    }

    fun getAlertCountByType(): Map<AlertType, Int> {
        return _uiState.value.allAlerts.groupBy { it.alertType }.mapValues { it.value.size }
    }
}

data class AlertsUiState(
    val alerts: List<PrivacyAlert> = emptyList(),
    val allAlerts: List<PrivacyAlert> = emptyList(),
    val selectedFilter: AlertType? = null,
    val unreadCount: Int = 0
)
