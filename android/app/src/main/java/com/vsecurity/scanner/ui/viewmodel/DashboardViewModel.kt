package com.vsecurity.scanner.ui.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vsecurity.scanner.data.model.*
import com.vsecurity.scanner.data.preferences.PreferencesManager
import com.vsecurity.scanner.data.repository.GuardianRepository
import com.vsecurity.scanner.data.repository.ScannerRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Dashboard ViewModel
 */
@HiltViewModel
class DashboardViewModel @Inject constructor(
    private val scannerRepository: ScannerRepository,
    private val guardianRepository: GuardianRepository,
    private val preferencesManager: PreferencesManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(DashboardUiState())
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    init {
        loadDashboardData()
    }

    private fun loadDashboardData() {
        viewModelScope.launch {
            // Load scanned apps
            val apps = scannerRepository.getAllApps()
            val highRiskApps = apps.filter { it.riskLevel in listOf(RiskLevel.CRITICAL, RiskLevel.HIGH) }
            
            // Load alerts
            val alerts = guardianRepository.getRecentAlerts(10)
            val todayStart = System.currentTimeMillis() - (System.currentTimeMillis() % 86400000)
            val alertsToday = alerts.count { it.timestamp >= todayStart }
            
            // Load sensor stats
            val dailySummaries = guardianRepository.getRecentDailySummaries(1)
            val todaySummary = dailySummaries.firstOrNull()
            
            // Calculate overall score
            val overallScore = if (apps.isEmpty()) {
                100
            } else {
                val avgRisk = apps.map { it.riskScore }.average().toInt()
                100 - avgRisk.coerceIn(0, 100)
            }
            
            val overallRiskLevel = when {
                highRiskApps.size >= 5 -> RiskLevel.CRITICAL
                highRiskApps.size >= 3 -> RiskLevel.HIGH
                highRiskApps.isNotEmpty() -> RiskLevel.MEDIUM
                apps.isNotEmpty() -> RiskLevel.LOW
                else -> RiskLevel.INFO
            }
            
            // Check guardian status
            val guardianActive = preferencesManager.guardianEnabled.first()

            _uiState.value = DashboardUiState(
                overallScore = overallScore,
                overallRiskLevel = overallRiskLevel,
                totalAppsScanned = apps.size,
                highRiskApps = highRiskApps.size,
                alertsToday = alertsToday,
                guardianActive = guardianActive,
                topRiskyApps = highRiskApps.take(5),
                recentAlerts = alerts,
                todayCameraAccesses = todaySummary?.totalCameraAccesses ?: 0,
                todayMicAccesses = todaySummary?.totalMicrophoneAccesses ?: 0,
                todayLocationAccesses = todaySummary?.totalLocationAccesses ?: 0,
                todayBackgroundAccesses = todaySummary?.totalBackgroundAccesses ?: 0
            )
        }
    }

    fun refresh() {
        loadDashboardData()
    }
}

data class DashboardUiState(
    val overallScore: Int = 100,
    val overallRiskLevel: RiskLevel = RiskLevel.INFO,
    val totalAppsScanned: Int = 0,
    val highRiskApps: Int = 0,
    val alertsToday: Int = 0,
    val guardianActive: Boolean = false,
    val topRiskyApps: List<ScannedApp> = emptyList(),
    val recentAlerts: List<PrivacyAlert> = emptyList(),
    val todayCameraAccesses: Int = 0,
    val todayMicAccesses: Int = 0,
    val todayLocationAccesses: Int = 0,
    val todayBackgroundAccesses: Int = 0
)
