package com.vsecurity.scanner.scanner

import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import com.vsecurity.scanner.data.model.*
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Scans installed applications for security vulnerabilities
 */
@Singleton
class AppScanner @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private val packageManager: PackageManager = context.packageManager

    /**
     * Scan all installed apps and emit progress
     */
    fun scanAllApps(
        includeSystem: Boolean = false
    ): Flow<ScanProgress> = flow {
        val packages = getInstalledPackages(includeSystem)
        val totalCount = packages.size
        val scannedApps = mutableListOf<ScannedApp>()

        emit(ScanProgress.Started(totalCount))

        packages.forEachIndexed { index, packageInfo ->
            try {
                val scannedApp = scanApp(packageInfo)
                scannedApps.add(scannedApp)
                emit(ScanProgress.Progress(index + 1, totalCount, scannedApp))
            } catch (e: Exception) {
                emit(ScanProgress.Error(packageInfo.packageName, e.message ?: "Unknown error"))
            }
        }

        val report = createReport(scannedApps)
        emit(ScanProgress.Completed(report))
    }.flowOn(Dispatchers.IO)

    /**
     * Scan a single app by package name
     */
    suspend fun scanSingleApp(packageName: String): ScannedApp? {
        return try {
            val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                packageManager.getPackageInfo(
                    packageName,
                    PackageManager.PackageInfoFlags.of(PackageManager.GET_PERMISSIONS.toLong())
                )
            } else {
                @Suppress("DEPRECATION")
                packageManager.getPackageInfo(packageName, PackageManager.GET_PERMISSIONS)
            }
            scanApp(packageInfo)
        } catch (e: PackageManager.NameNotFoundException) {
            null
        }
    }

    /**
     * Get list of installed packages
     */
    private fun getInstalledPackages(includeSystem: Boolean): List<PackageInfo> {
        val flags = PackageManager.GET_PERMISSIONS

        val packages = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.getInstalledPackages(PackageManager.PackageInfoFlags.of(flags.toLong()))
        } else {
            @Suppress("DEPRECATION")
            packageManager.getInstalledPackages(flags)
        }

        return if (includeSystem) {
            packages
        } else {
            packages.filter { !isSystemApp(it) }
        }
    }

    /**
     * Check if an app is a system app
     */
    private fun isSystemApp(packageInfo: PackageInfo): Boolean {
        return packageInfo.applicationInfo?.let { appInfo ->
            (appInfo.flags and ApplicationInfo.FLAG_SYSTEM) != 0
        } ?: false
    }

    /**
     * Scan a single package and return security assessment
     */
    private fun scanApp(packageInfo: PackageInfo): ScannedApp {
        val appInfo = packageInfo.applicationInfo
        val appName = appInfo?.let { packageManager.getApplicationLabel(it).toString() }
            ?: packageInfo.packageName.substringAfterLast('.')

        // Get all permissions
        val requestedPermissions = packageInfo.requestedPermissions?.toList() ?: emptyList()

        // Analyze permissions
        val permissionAnalysis = analyzePermissions(requestedPermissions)

        // Calculate risk score
        val (riskScore, riskLevel) = calculateRisk(permissionAnalysis, packageInfo)

        // Get SDK info
        val targetSdk = appInfo?.targetSdkVersion ?: 0
        val minSdk = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            appInfo?.minSdkVersion ?: 0
        } else {
            0
        }

        // Get timestamps
        val installTime = packageInfo.firstInstallTime
        val updateTime = packageInfo.lastUpdateTime

        return ScannedApp(
            packageName = packageInfo.packageName,
            appName = appName,
            versionName = packageInfo.versionName ?: "Unknown",
            versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                packageInfo.longVersionCode
            } else {
                @Suppress("DEPRECATION")
                packageInfo.versionCode.toLong()
            },
            targetSdk = targetSdk,
            minSdk = minSdk,
            permissions = requestedPermissions,
            dangerousPermissions = permissionAnalysis,
            riskScore = riskScore,
            riskLevel = riskLevel,
            installTime = installTime,
            lastUpdateTime = updateTime,
            isSystemApp = isSystemApp(packageInfo)
        )
    }

    /**
     * Analyze permissions and find dangerous ones
     */
    private fun analyzePermissions(permissions: List<String>): List<DangerousPermission> {
        return permissions.mapNotNull { permission ->
            PermissionDatabase.getPermissionInfo(permission)?.let { info ->
                DangerousPermission(
                    name = info.name,
                    riskLevel = info.riskLevel,
                    category = info.category,
                    description = info.description,
                    risks = info.risks,
                    mitigations = info.mitigations
                )
            }
        }
    }

    /**
     * Calculate overall risk score and level
     */
    private fun calculateRisk(
        dangerousPermissions: List<DangerousPermission>,
        packageInfo: PackageInfo
    ): Pair<Int, RiskLevel> {
        var score = 0

        // Permission-based risk
        dangerousPermissions.forEach { perm ->
            score += PermissionDatabase.getRiskWeight(perm.riskLevel)
        }

        // SDK-based risk
        val targetSdk = packageInfo.applicationInfo?.targetSdkVersion ?: 0
        when {
            targetSdk < 23 -> score += 20  // Pre-Marshmallow (no runtime permissions)
            targetSdk < 26 -> score += 10  // Below Oreo
            targetSdk < 28 -> score += 5   // Below Pie
        }

        // Cap at 100
        score = score.coerceAtMost(100)

        val level = when {
            score >= 70 -> RiskLevel.CRITICAL
            score >= 50 -> RiskLevel.HIGH
            score >= 30 -> RiskLevel.MEDIUM
            score >= 10 -> RiskLevel.LOW
            else -> RiskLevel.INFO
        }

        return Pair(score, level)
    }

    /**
     * Create a complete scan report
     */
    private fun createReport(apps: List<ScannedApp>): ScanReport {
        val criticalCount = apps.count { it.riskLevel == RiskLevel.CRITICAL }
        val highCount = apps.count { it.riskLevel == RiskLevel.HIGH }
        val mediumCount = apps.count { it.riskLevel == RiskLevel.MEDIUM }
        val lowCount = apps.count { it.riskLevel == RiskLevel.LOW || it.riskLevel == RiskLevel.INFO }

        // Count permission occurrences
        val permissionCounts = mutableMapOf<String, Int>()
        apps.forEach { app ->
            app.dangerousPermissions.forEach { perm ->
                permissionCounts[perm.name] = (permissionCounts[perm.name] ?: 0) + 1
            }
        }

        val sortedPermissions = permissionCounts.entries
            .sortedByDescending { it.value }
            .take(10)
            .map { it.key to it.value }

        return ScanReport(
            scanTime = System.currentTimeMillis(),
            totalApps = apps.size,
            criticalRiskApps = criticalCount,
            highRiskApps = highCount,
            mediumRiskApps = mediumCount,
            lowRiskApps = lowCount,
            totalDangerousPermissions = apps.sumOf { it.dangerousPermissions.size },
            mostCommonPermissions = sortedPermissions,
            apps = apps.sortedByDescending { it.riskScore }
        )
    }
}

/**
 * Sealed class representing scan progress states
 */
sealed class ScanProgress {
    data class Started(val totalApps: Int) : ScanProgress()
    data class Progress(val current: Int, val total: Int, val app: ScannedApp) : ScanProgress()
    data class Error(val packageName: String, val error: String) : ScanProgress()
    data class Completed(val report: ScanReport) : ScanProgress()
}
