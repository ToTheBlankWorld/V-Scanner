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
import com.vsecurity.scanner.data.model.SensorType
import com.vsecurity.scanner.ui.theme.*
import com.vsecurity.scanner.ui.viewmodel.GuardianViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GuardianScreen(
    navController: NavController,
    viewModel: GuardianViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Header
        item {
            Text(
                text = "Privacy Guardian",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "Monitor and protect your sensor access",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        // Guardian Status Card
        item {
            GuardianStatusCard(
                isActive = uiState.isGuardianActive,
                onToggle = { viewModel.toggleGuardian() }
            )
        }

        // Sensor Monitoring Toggles
        item {
            Text(
                text = "Sensor Monitoring",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
        }

        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                )
            ) {
                Column {
                    SensorToggleItem(
                        icon = Icons.Default.CameraAlt,
                        label = "Camera",
                        description = "Alert when apps access camera",
                        checked = uiState.monitorCamera,
                        onCheckedChange = { viewModel.setMonitorCamera(it) }
                    )
                    HorizontalDivider()
                    SensorToggleItem(
                        icon = Icons.Default.Mic,
                        label = "Microphone",
                        description = "Alert when apps record audio",
                        checked = uiState.monitorMicrophone,
                        onCheckedChange = { viewModel.setMonitorMicrophone(it) }
                    )
                    HorizontalDivider()
                    SensorToggleItem(
                        icon = Icons.Default.LocationOn,
                        label = "Location",
                        description = "Alert when apps access location",
                        checked = uiState.monitorLocation,
                        onCheckedChange = { viewModel.setMonitorLocation(it) }
                    )
                }
            }
        }

        // Alert Settings
        item {
            Text(
                text = "Alert Settings",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
        }

        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                )
            ) {
                Column {
                    SensorToggleItem(
                        icon = Icons.Default.VisibilityOff,
                        label = "Background Access",
                        description = "Alert when apps use sensors in background",
                        checked = uiState.alertOnBackground,
                        onCheckedChange = { viewModel.setAlertOnBackground(it) }
                    )
                    HorizontalDivider()
                    SensorToggleItem(
                        icon = Icons.Default.PhonelinkOff,
                        label = "Screen Off Access",
                        description = "Alert when sensors used with screen off",
                        checked = uiState.alertOnScreenOff,
                        onCheckedChange = { viewModel.setAlertOnScreenOff(it) }
                    )
                    HorizontalDivider()
                    SensorToggleItem(
                        icon = Icons.Default.TrendingUp,
                        label = "Frequent Access",
                        description = "Alert on excessive sensor usage",
                        checked = uiState.alertOnFrequent,
                        onCheckedChange = { viewModel.setAlertOnFrequent(it) }
                    )
                }
            }
        }

        // Recently Active Apps
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "Recently Active Apps",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
                TextButton(onClick = { /* View all */ }) {
                    Text("View All")
                }
            }
        }

        items(uiState.recentlyActiveApps.take(5)) { appStats ->
            RecentActivityCard(
                appName = appStats.appName,
                packageName = appStats.packageName,
                cameraCount = appStats.cameraAccessCount,
                micCount = appStats.microphoneAccessCount,
                locationCount = appStats.locationAccessCount,
                backgroundCount = appStats.totalBackgroundAccesses
            )
        }

        // Usage Trends (Chart Placeholder)
        item {
            Text(
                text = "7-Day Usage Trends",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
        }

        item {
            UsageTrendsCard(dailySummaries = uiState.dailySummaries)
        }

        // Bottom spacing
        item { Spacer(modifier = Modifier.height(16.dp)) }
    }
}

@Composable
fun GuardianStatusCard(
    isActive: Boolean,
    onToggle: () -> Unit
) {
    val backgroundColor = if (isActive) SecurityGreen.copy(alpha = 0.1f) else Color.Gray.copy(alpha = 0.1f)
    val statusColor = if (isActive) SecurityGreen else Color.Gray

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = backgroundColor)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(48.dp)
                        .clip(CircleShape)
                        .background(statusColor.copy(alpha = 0.2f)),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        imageVector = Icons.Default.Shield,
                        contentDescription = null,
                        tint = statusColor,
                        modifier = Modifier.size(28.dp)
                    )
                }
                Spacer(modifier = Modifier.width(16.dp))
                Column {
                    Text(
                        text = if (isActive) "Guardian Active" else "Guardian Disabled",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = statusColor
                    )
                    Text(
                        text = if (isActive) "Monitoring sensor access" else "Tap to enable protection",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            Switch(
                checked = isActive,
                onCheckedChange = { onToggle() },
                colors = SwitchDefaults.colors(
                    checkedThumbColor = SecurityGreen,
                    checkedTrackColor = SecurityGreen.copy(alpha = 0.5f)
                )
            )
        }
    }
}

@Composable
fun SensorToggleItem(
    icon: ImageVector,
    label: String,
    description: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = if (checked) SecurityBlue else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(24.dp)
            )
            Spacer(modifier = Modifier.width(16.dp))
            Column {
                Text(
                    text = label,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange
        )
    }
}

@Composable
fun RecentActivityCard(
    appName: String,
    packageName: String,
    cameraCount: Int,
    micCount: Int,
    locationCount: Int,
    backgroundCount: Int
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = appName,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = packageName,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1
                    )
                }
                if (backgroundCount > 0) {
                    AssistChip(
                        onClick = {},
                        label = { Text("$backgroundCount bg") },
                        colors = AssistChipDefaults.assistChipColors(
                            containerColor = WarningOrange.copy(alpha = 0.1f)
                        )
                    )
                }
            }
            Spacer(modifier = Modifier.height(12.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                SensorAccessBadge(Icons.Default.CameraAlt, "Camera", cameraCount)
                SensorAccessBadge(Icons.Default.Mic, "Mic", micCount)
                SensorAccessBadge(Icons.Default.LocationOn, "Location", locationCount)
            }
        }
    }
}

@Composable
fun SensorAccessBadge(icon: ImageVector, label: String, count: Int) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                modifier = Modifier.size(16.dp),
                tint = if (count > 0) SecurityBlue else MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = count.toString(),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                color = if (count > 0) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
fun UsageTrendsCard(dailySummaries: List<com.vsecurity.scanner.data.model.DailySensorSummary>) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .height(200.dp),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        if (dailySummaries.isEmpty()) {
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "No data yet. Enable Guardian to start tracking.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(16.dp)
            ) {
                // Simple bar chart representation
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    horizontalArrangement = Arrangement.SpaceEvenly,
                    verticalAlignment = Alignment.Bottom
                ) {
                    dailySummaries.takeLast(7).forEach { summary ->
                        val maxValue = maxOf(
                            summary.totalCameraAccesses,
                            summary.totalMicrophoneAccesses,
                            summary.totalLocationAccesses,
                            1
                        )
                        val height = (maxValue.coerceAtMost(50) / 50f * 100).dp
                        
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Box(
                                modifier = Modifier
                                    .width(24.dp)
                                    .height(height.coerceAtLeast(4.dp))
                                    .clip(RoundedCornerShape(topStart = 4.dp, topEnd = 4.dp))
                                    .background(SecurityBlue)
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = summary.date.takeLast(2),
                                style = MaterialTheme.typography.labelSmall
                            )
                        }
                    }
                }
                
                Spacer(modifier = Modifier.height(8.dp))
                
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly
                ) {
                    LegendItem(SecurityBlue, "Camera")
                    LegendItem(SecurityGreen, "Mic")
                    LegendItem(WarningOrange, "Location")
                }
            }
        }
    }
}

@Composable
fun LegendItem(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(color)
        )
        Spacer(modifier = Modifier.width(4.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall
        )
    }
}
