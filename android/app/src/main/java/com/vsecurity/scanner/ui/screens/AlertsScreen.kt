package com.vsecurity.scanner.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.vsecurity.scanner.data.model.AlertType
import com.vsecurity.scanner.data.model.PrivacyAlert
import com.vsecurity.scanner.data.model.SensorType
import com.vsecurity.scanner.ui.theme.*
import com.vsecurity.scanner.ui.viewmodel.AlertsViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertsScreen(
    navController: NavController,
    viewModel: AlertsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = "Privacy Alerts",
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = "${uiState.unacknowledgedCount} unread alerts",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (uiState.alerts.isNotEmpty()) {
                TextButton(onClick = { viewModel.acknowledgeAll() }) {
                    Text("Clear All")
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // Filter Chips
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            FilterChip(
                selected = uiState.selectedFilter == null,
                onClick = { viewModel.setFilter(null) },
                label = { Text("All") }
            )
            FilterChip(
                selected = uiState.selectedFilter == SensorType.CAMERA,
                onClick = { viewModel.setFilter(SensorType.CAMERA) },
                leadingIcon = { Icon(Icons.Default.CameraAlt, null, Modifier.size(16.dp)) },
                label = { Text("Camera") }
            )
            FilterChip(
                selected = uiState.selectedFilter == SensorType.MICROPHONE,
                onClick = { viewModel.setFilter(SensorType.MICROPHONE) },
                leadingIcon = { Icon(Icons.Default.Mic, null, Modifier.size(16.dp)) },
                label = { Text("Mic") }
            )
            FilterChip(
                selected = uiState.selectedFilter == SensorType.LOCATION,
                onClick = { viewModel.setFilter(SensorType.LOCATION) },
                leadingIcon = { Icon(Icons.Default.LocationOn, null, Modifier.size(16.dp)) },
                label = { Text("Location") }
            )
        }

        Spacer(modifier = Modifier.height(16.dp))

        // Alerts List
        LazyColumn(
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            val filteredAlerts = if (uiState.selectedFilter != null) {
                uiState.alerts.filter { it.sensorType == uiState.selectedFilter }
            } else {
                uiState.alerts
            }

            if (filteredAlerts.isEmpty()) {
                item {
                    EmptyAlertsState()
                }
            } else {
                items(filteredAlerts) { alert ->
                    AlertCard(
                        alert = alert,
                        onAcknowledge = { viewModel.acknowledgeAlert(alert.id) }
                    )
                }
            }
        }
    }
}

@Composable
fun AlertCard(
    alert: PrivacyAlert,
    onAcknowledge: () -> Unit
) {
    val (icon, color) = when (alert.sensorType) {
        SensorType.CAMERA -> Icons.Default.CameraAlt to Color(0xFF2196F3)
        SensorType.MICROPHONE -> Icons.Default.Mic to Color(0xFF4CAF50)
        SensorType.LOCATION -> Icons.Default.LocationOn to Color(0xFFFF9800)
        else -> Icons.Default.Warning to WarningOrange
    }

    val alertTypeIcon = when (alert.alertType) {
        AlertType.BACKGROUND_SENSOR_ACCESS -> Icons.Default.VisibilityOff
        AlertType.SCREEN_OFF_ACCESS -> Icons.Default.PhonelinkOff
        AlertType.FREQUENT_ACCESS -> Icons.Default.TrendingUp
        AlertType.FIRST_TIME_ACCESS -> Icons.Default.NewReleases
        AlertType.SUSPICIOUS_PATTERN -> Icons.Default.Warning
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (alert.wasAcknowledged) 
                MaterialTheme.colorScheme.surfaceVariant 
            else 
                color.copy(alpha = 0.1f)
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.Top
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(color.copy(alpha = 0.2f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = color,
                    modifier = Modifier.size(20.dp)
                )
            }

            Spacer(modifier = Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = alert.appName,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = formatAlertTime(alert.timestamp),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                Spacer(modifier = Modifier.height(4.dp))

                Text(
                    text = alert.message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )

                Spacer(modifier = Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = alertTypeIcon,
                            contentDescription = null,
                            modifier = Modifier.size(14.dp),
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text(
                            text = alert.alertType.name.replace("_", " "),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }

                    if (!alert.wasAcknowledged) {
                        TextButton(
                            onClick = onAcknowledge,
                            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp)
                        ) {
                            Text("Dismiss", style = MaterialTheme.typography.labelMedium)
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun EmptyAlertsState() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(48.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            imageVector = Icons.Default.CheckCircle,
            contentDescription = null,
            modifier = Modifier.size(64.dp),
            tint = SecurityGreen
        )
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = "No Alerts",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "Your privacy is being protected. No suspicious activity detected.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center
        )
    }
}

private fun formatAlertTime(timestamp: Long): String {
    val diff = System.currentTimeMillis() - timestamp
    return when {
        diff < 60_000 -> "Just now"
        diff < 3600_000 -> "${diff / 60_000}m ago"
        diff < 86400_000 -> "${diff / 3600_000}h ago"
        else -> {
            val sdf = java.text.SimpleDateFormat("MMM dd", java.util.Locale.getDefault())
            sdf.format(java.util.Date(timestamp))
        }
    }
}
