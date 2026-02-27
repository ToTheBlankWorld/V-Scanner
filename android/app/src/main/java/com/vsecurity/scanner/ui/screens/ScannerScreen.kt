package com.vsecurity.scanner.ui.screens

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.navigation.NavController
import com.vsecurity.scanner.data.model.RiskLevel
import com.vsecurity.scanner.data.model.ScannedApp
import com.vsecurity.scanner.ui.theme.*
import com.vsecurity.scanner.ui.viewmodel.ScannerViewModel
import com.vsecurity.scanner.ui.viewmodel.ScanState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScannerScreen(
    navController: NavController,
    viewModel: ScannerViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    val scanState by viewModel.scanState.collectAsState()
    var selectedApp by remember { mutableStateOf<ScannedApp?>(null) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        // Header
        Text(
            text = "App Scanner",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = "Scan installed apps for security vulnerabilities",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        Spacer(modifier = Modifier.height(16.dp))

        // Scan Controls
        when (scanState) {
            is ScanState.Idle -> {
                ScanButton(
                    onScan = { viewModel.startScan() },
                    lastScanTime = uiState.lastScanTime
                )
            }
            is ScanState.Scanning -> {
                ScanProgressCard(
                    current = (scanState as ScanState.Scanning).current,
                    total = (scanState as ScanState.Scanning).total,
                    currentApp = (scanState as ScanState.Scanning).currentApp
                )
            }
            is ScanState.Completed -> {
                ScanCompletedCard(
                    totalApps = uiState.scannedApps.size,
                    highRiskCount = uiState.scannedApps.count { 
                        it.riskLevel in listOf(RiskLevel.CRITICAL, RiskLevel.HIGH) 
                    },
                    onRescan = { viewModel.startScan() }
                )
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
                selected = uiState.selectedFilter == RiskLevel.CRITICAL,
                onClick = { viewModel.setFilter(RiskLevel.CRITICAL) },
                label = { Text("Critical") },
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = DangerRed.copy(alpha = 0.2f)
                )
            )
            FilterChip(
                selected = uiState.selectedFilter == RiskLevel.HIGH,
                onClick = { viewModel.setFilter(RiskLevel.HIGH) },
                label = { Text("High") },
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = WarningOrange.copy(alpha = 0.2f)
                )
            )
            FilterChip(
                selected = uiState.selectedFilter == RiskLevel.MEDIUM,
                onClick = { viewModel.setFilter(RiskLevel.MEDIUM) },
                label = { Text("Medium") }
            )
        }

        Spacer(modifier = Modifier.height(16.dp))

        // App List
        LazyColumn(
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            val filteredApps = if (uiState.selectedFilter != null) {
                uiState.scannedApps.filter { it.riskLevel == uiState.selectedFilter }
            } else {
                uiState.scannedApps
            }

            items(filteredApps) { app ->
                ScannedAppCard(
                    app = app,
                    onClick = { selectedApp = app }
                )
            }

            if (filteredApps.isEmpty() && scanState !is ScanState.Scanning) {
                item {
                    EmptyState(
                        message = if (uiState.scannedApps.isEmpty()) {
                            "No apps scanned yet. Tap 'Scan Now' to begin."
                        } else {
                            "No apps match the selected filter."
                        }
                    )
                }
            }
        }
    }

    // App Detail Bottom Sheet
    selectedApp?.let { app ->
        AppDetailBottomSheet(
            app = app,
            onDismiss = { selectedApp = null }
        )
    }
}

@Composable
fun ScanButton(
    onScan: () -> Unit,
    lastScanTime: Long?
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Icon(
                imageVector = Icons.Default.Security,
                contentDescription = null,
                modifier = Modifier.size(48.dp),
                tint = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.height(12.dp))
            Button(
                onClick = onScan,
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(Icons.Default.PlayArrow, contentDescription = null)
                Spacer(modifier = Modifier.width(8.dp))
                Text("Scan Now")
            }
            if (lastScanTime != null && lastScanTime > 0) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Last scan: ${formatTimestamp(lastScanTime)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
fun ScanProgressCard(
    current: Int,
    total: Int,
    currentApp: String
) {
    val progress by animateFloatAsState(
        targetValue = current.toFloat() / total.coerceAtLeast(1),
        label = "scan_progress"
    )

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = "Scanning...",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = "$current / $total",
                    style = MaterialTheme.typography.titleMedium
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .clip(RoundedCornerShape(4.dp))
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = currentApp,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1
            )
        }
    }
}

@Composable
fun ScanCompletedCard(
    totalApps: Int,
    highRiskCount: Int,
    onRescan: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (highRiskCount > 0) 
                WarningOrange.copy(alpha = 0.1f) 
            else 
                SecurityGreen.copy(alpha = 0.1f)
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = "Scan Complete",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = "$totalApps apps scanned, $highRiskCount need attention",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            IconButton(onClick = onRescan) {
                Icon(Icons.Default.Refresh, contentDescription = "Rescan")
            }
        }
    }
}

@Composable
fun ScannedAppCard(
    app: ScannedApp,
    onClick: () -> Unit
) {
    val riskColor = when (app.riskLevel) {
        RiskLevel.CRITICAL -> DangerRed
        RiskLevel.HIGH -> WarningOrange
        RiskLevel.MEDIUM -> Color(0xFFFFEB3B)
        RiskLevel.LOW -> SecurityGreen
        RiskLevel.INFO -> SecurityBlue
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        ),
        onClick = onClick
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            // Risk indicator
            Box(
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(riskColor.copy(alpha = 0.2f)),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = app.riskScore.toString(),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = riskColor
                )
            }

            Spacer(modifier = Modifier.width(12.dp))

            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = app.appName,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = app.packageName,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1
                )
                Row(
                    modifier = Modifier.padding(top = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    if (app.dangerousPermissions.isNotEmpty()) {
                        AssistChip(
                            onClick = {},
                            label = { 
                                Text(
                                    "${app.dangerousPermissions.size} risky perms",
                                    style = MaterialTheme.typography.labelSmall
                                ) 
                            },
                            colors = AssistChipDefaults.assistChipColors(
                                containerColor = DangerRed.copy(alpha = 0.1f)
                            )
                        )
                    }
                    if (app.targetSdk < 28) {
                        AssistChip(
                            onClick = {},
                            label = { 
                                Text(
                                    "SDK ${app.targetSdk}",
                                    style = MaterialTheme.typography.labelSmall
                                ) 
                            },
                            colors = AssistChipDefaults.assistChipColors(
                                containerColor = WarningOrange.copy(alpha = 0.1f)
                            )
                        )
                    }
                }
            }

            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppDetailBottomSheet(
    app: ScannedApp,
    onDismiss: () -> Unit
) {
    val sheetState = rememberModalBottomSheetState()

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState
    ) {
        LazyColumn(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 32.dp)
        ) {
            // Header
            item {
                Text(
                    text = app.appName,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = app.packageName,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = "Version ${app.versionName}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(16.dp))
            }

            // Risk Score
            item {
                RiskScoreSection(app.riskScore, app.riskLevel)
                Spacer(modifier = Modifier.height(16.dp))
            }

            // SDK Info
            item {
                Text(
                    text = "SDK Information",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    InfoChip("Target SDK", app.targetSdk.toString())
                    InfoChip("Min SDK", app.minSdk.toString())
                }
                Spacer(modifier = Modifier.height(16.dp))
            }

            // Dangerous Permissions
            if (app.dangerousPermissions.isNotEmpty()) {
                item {
                    Text(
                        text = "Dangerous Permissions (${app.dangerousPermissions.size})",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                }

                items(app.dangerousPermissions) { perm ->
                    PermissionCard(
                        name = perm.name,
                        category = perm.category.name,
                        riskLevel = perm.riskLevel,
                        description = perm.description,
                        mitigations = perm.mitigations
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                }
            }
        }
    }
}

@Composable
fun RiskScoreSection(score: Int, level: RiskLevel) {
    val color = when (level) {
        RiskLevel.CRITICAL -> DangerRed
        RiskLevel.HIGH -> WarningOrange
        RiskLevel.MEDIUM -> Color(0xFFFFEB3B)
        RiskLevel.LOW -> SecurityGreen
        RiskLevel.INFO -> SecurityBlue
    }

    Card(
        colors = CardDefaults.cardColors(
            containerColor = color.copy(alpha = 0.1f)
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = "Risk Level: ${level.name}",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = color
                )
                Text(
                    text = "Score: $score / 100",
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            CircularProgressIndicator(
                progress = { score / 100f },
                modifier = Modifier.size(48.dp),
                color = color,
                strokeWidth = 6.dp,
                trackColor = color.copy(alpha = 0.2f)
            )
        }
    }
}

@Composable
fun InfoChip(label: String, value: String) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = value,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
        }
    }
}

@Composable
fun PermissionCard(
    name: String,
    category: String,
    riskLevel: RiskLevel,
    description: String,
    mitigations: List<String>
) {
    val color = when (riskLevel) {
        RiskLevel.CRITICAL -> DangerRed
        RiskLevel.HIGH -> WarningOrange
        RiskLevel.MEDIUM -> Color(0xFFFFEB3B)
        else -> MaterialTheme.colorScheme.primary
    }

    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = name,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = category,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Text(
                    text = riskLevel.name,
                    style = MaterialTheme.typography.labelMedium,
                    color = color,
                    fontWeight = FontWeight.Bold
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (mitigations.isNotEmpty()) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Recommendation:",
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.SemiBold
                )
                Text(
                    text = mitigations.first(),
                    style = MaterialTheme.typography.bodySmall,
                    color = SecurityBlue
                )
            }
        }
    }
}

@Composable
fun EmptyState(message: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            imageVector = Icons.Default.SearchOff,
            contentDescription = null,
            modifier = Modifier.size(48.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

private fun formatTimestamp(timestamp: Long): String {
    val sdf = java.text.SimpleDateFormat("MMM dd, HH:mm", java.util.Locale.getDefault())
    return sdf.format(java.util.Date(timestamp))
}
