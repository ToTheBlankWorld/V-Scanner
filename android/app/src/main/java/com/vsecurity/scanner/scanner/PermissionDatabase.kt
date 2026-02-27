package com.vsecurity.scanner.scanner

import com.vsecurity.scanner.data.model.PermissionCategory
import com.vsecurity.scanner.data.model.PermissionDefinition
import com.vsecurity.scanner.data.model.RiskLevel

/**
 * Database of dangerous Android permissions with security assessments
 */
object PermissionDatabase {

    val dangerousPermissions: Map<String, PermissionDefinition> = mapOf(
        // SMS Permissions - CRITICAL
        "android.permission.READ_SMS" to PermissionDefinition(
            permission = "android.permission.READ_SMS",
            name = "Read SMS",
            riskLevel = RiskLevel.CRITICAL,
            category = PermissionCategory.SMS,
            description = "Allows reading SMS messages",
            risks = listOf(
                "Can read OTP/2FA codes",
                "Access to personal conversations",
                "Financial data exposure",
                "Identity theft risk"
            ),
            mitigations = listOf(
                "Revoke if not essential",
                "Use SMS Retriever API",
                "Enable authenticator apps for 2FA"
            ),
            secureAlternatives = listOf(
                "Google SMS Retriever API",
                "Push notifications for OTP"
            )
        ),
        "android.permission.SEND_SMS" to PermissionDefinition(
            permission = "android.permission.SEND_SMS",
            name = "Send SMS",
            riskLevel = RiskLevel.CRITICAL,
            category = PermissionCategory.SMS,
            description = "Allows sending SMS messages",
            risks = listOf(
                "Unauthorized SMS charges",
                "Spam distribution",
                "Premium SMS fraud"
            ),
            mitigations = listOf(
                "Deny unless messaging app",
                "Monitor phone bills"
            ),
            secureAlternatives = listOf(
                "Intent ACTION_SENDTO"
            )
        ),
        "android.permission.RECEIVE_SMS" to PermissionDefinition(
            permission = "android.permission.RECEIVE_SMS",
            name = "Receive SMS",
            riskLevel = RiskLevel.CRITICAL,
            category = PermissionCategory.SMS,
            description = "Allows receiving SMS messages",
            risks = listOf(
                "Intercept OTP codes",
                "Privacy violation"
            ),
            mitigations = listOf(
                "Review permissions",
                "Use authenticator apps"
            ),
            secureAlternatives = listOf(
                "SMS Retriever API"
            )
        ),

        // Contacts Permissions - HIGH
        "android.permission.READ_CONTACTS" to PermissionDefinition(
            permission = "android.permission.READ_CONTACTS",
            name = "Read Contacts",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.CONTACTS,
            description = "Allows reading contact data",
            risks = listOf(
                "Contact list harvesting",
                "Social engineering attacks",
                "Spam targeting"
            ),
            mitigations = listOf(
                "Grant only to trusted apps",
                "Use contact picker"
            ),
            secureAlternatives = listOf(
                "Contact Picker API"
            )
        ),
        "android.permission.WRITE_CONTACTS" to PermissionDefinition(
            permission = "android.permission.WRITE_CONTACTS",
            name = "Write Contacts",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.CONTACTS,
            description = "Allows modifying contacts",
            risks = listOf(
                "Contact manipulation",
                "Malicious contact injection"
            ),
            mitigations = listOf(
                "Deny to most apps",
                "Backup contacts"
            ),
            secureAlternatives = listOf(
                "Intent-based contact creation"
            )
        ),
        "android.permission.GET_ACCOUNTS" to PermissionDefinition(
            permission = "android.permission.GET_ACCOUNTS",
            name = "Get Accounts",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.CONTACTS,
            description = "Allows access to accounts list",
            risks = listOf(
                "Account enumeration",
                "Identity discovery"
            ),
            mitigations = listOf(
                "Review necessity"
            ),
            secureAlternatives = listOf(
                "AccountManager with specific account type"
            )
        ),

        // Camera Permissions - HIGH
        "android.permission.CAMERA" to PermissionDefinition(
            permission = "android.permission.CAMERA",
            name = "Camera",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.CAMERA,
            description = "Allows access to device camera",
            risks = listOf(
                "Unauthorized photo/video capture",
                "Surveillance without consent",
                "Privacy invasion"
            ),
            mitigations = listOf(
                "Grant only when needed",
                "Use camera covers",
                "Check indicator lights"
            ),
            secureAlternatives = listOf(
                "Intent ACTION_IMAGE_CAPTURE"
            )
        ),

        // Location Permissions - HIGH
        "android.permission.ACCESS_FINE_LOCATION" to PermissionDefinition(
            permission = "android.permission.ACCESS_FINE_LOCATION",
            name = "Fine Location",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.LOCATION,
            description = "Allows precise GPS location",
            risks = listOf(
                "Real-time tracking",
                "Location history exposure",
                "Stalking enablement"
            ),
            mitigations = listOf(
                "Use 'While using app'",
                "Deny background location"
            ),
            secureAlternatives = listOf(
                "Coarse location",
                "On-demand requests"
            )
        ),
        "android.permission.ACCESS_COARSE_LOCATION" to PermissionDefinition(
            permission = "android.permission.ACCESS_COARSE_LOCATION",
            name = "Coarse Location",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.LOCATION,
            description = "Allows approximate location",
            risks = listOf(
                "General area tracking",
                "Behavioral profiling"
            ),
            mitigations = listOf(
                "Prefer over fine location"
            ),
            secureAlternatives = listOf(
                "IP-based geolocation"
            )
        ),
        "android.permission.ACCESS_BACKGROUND_LOCATION" to PermissionDefinition(
            permission = "android.permission.ACCESS_BACKGROUND_LOCATION",
            name = "Background Location",
            riskLevel = RiskLevel.CRITICAL,
            category = PermissionCategory.LOCATION,
            description = "Allows background location access",
            risks = listOf(
                "Continuous tracking",
                "Battery drain",
                "Movement history"
            ),
            mitigations = listOf(
                "Deny to most apps",
                "Regular audit"
            ),
            secureAlternatives = listOf(
                "Geofencing APIs"
            )
        ),

        // Microphone Permissions - HIGH
        "android.permission.RECORD_AUDIO" to PermissionDefinition(
            permission = "android.permission.RECORD_AUDIO",
            name = "Record Audio",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.MICROPHONE,
            description = "Allows audio recording",
            risks = listOf(
                "Eavesdropping",
                "Conversation recording",
                "Background listening"
            ),
            mitigations = listOf(
                "Grant only to voice apps",
                "Check mic indicator"
            ),
            secureAlternatives = listOf(
                "Speech-to-text APIs"
            )
        ),

        // Storage Permissions - MEDIUM
        "android.permission.READ_EXTERNAL_STORAGE" to PermissionDefinition(
            permission = "android.permission.READ_EXTERNAL_STORAGE",
            name = "Read Storage",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.STORAGE,
            description = "Allows reading external storage",
            risks = listOf(
                "Access to photos/documents",
                "Personal data exposure"
            ),
            mitigations = listOf(
                "Use scoped storage",
                "Grant selective access"
            ),
            secureAlternatives = listOf(
                "Storage Access Framework"
            )
        ),
        "android.permission.WRITE_EXTERNAL_STORAGE" to PermissionDefinition(
            permission = "android.permission.WRITE_EXTERNAL_STORAGE",
            name = "Write Storage",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.STORAGE,
            description = "Allows writing to storage",
            risks = listOf(
                "File manipulation",
                "Malware potential"
            ),
            mitigations = listOf(
                "Use app-specific dirs"
            ),
            secureAlternatives = listOf(
                "App-specific storage"
            )
        ),
        "android.permission.MANAGE_EXTERNAL_STORAGE" to PermissionDefinition(
            permission = "android.permission.MANAGE_EXTERNAL_STORAGE",
            name = "Manage All Files",
            riskLevel = RiskLevel.CRITICAL,
            category = PermissionCategory.STORAGE,
            description = "Full storage management",
            risks = listOf(
                "Complete file access",
                "System manipulation"
            ),
            mitigations = listOf(
                "Only for file managers"
            ),
            secureAlternatives = listOf(
                "MediaStore API"
            )
        ),

        // Phone Permissions - MEDIUM to HIGH
        "android.permission.READ_PHONE_STATE" to PermissionDefinition(
            permission = "android.permission.READ_PHONE_STATE",
            name = "Read Phone State",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.PHONE,
            description = "Allows reading phone identity",
            risks = listOf(
                "Device fingerprinting",
                "IMEI exposure"
            ),
            mitigations = listOf(
                "Deny if not call-related"
            ),
            secureAlternatives = listOf(
                "Instance ID"
            )
        ),
        "android.permission.CALL_PHONE" to PermissionDefinition(
            permission = "android.permission.CALL_PHONE",
            name = "Make Calls",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.PHONE,
            description = "Allows initiating calls",
            risks = listOf(
                "Premium number calls",
                "Unauthorized charges"
            ),
            mitigations = listOf(
                "Use dial intent"
            ),
            secureAlternatives = listOf(
                "Intent ACTION_DIAL"
            )
        ),
        "android.permission.READ_CALL_LOG" to PermissionDefinition(
            permission = "android.permission.READ_CALL_LOG",
            name = "Read Call Log",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.PHONE,
            description = "Allows reading call history",
            risks = listOf(
                "Communication exposure",
                "Privacy violation"
            ),
            mitigations = listOf(
                "Deny to most apps"
            ),
            secureAlternatives = emptyList()
        ),
        "android.permission.WRITE_CALL_LOG" to PermissionDefinition(
            permission = "android.permission.WRITE_CALL_LOG",
            name = "Write Call Log",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.PHONE,
            description = "Allows modifying call history",
            risks = listOf(
                "Evidence tampering"
            ),
            mitigations = listOf(
                "Deny unless dialer app"
            ),
            secureAlternatives = emptyList()
        ),
        "android.permission.PROCESS_OUTGOING_CALLS" to PermissionDefinition(
            permission = "android.permission.PROCESS_OUTGOING_CALLS",
            name = "Process Outgoing Calls",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.PHONE,
            description = "Allows processing outgoing calls",
            risks = listOf(
                "Call interception",
                "Call redirection"
            ),
            mitigations = listOf(
                "Review necessity"
            ),
            secureAlternatives = emptyList()
        ),

        // Calendar Permissions - MEDIUM
        "android.permission.READ_CALENDAR" to PermissionDefinition(
            permission = "android.permission.READ_CALENDAR",
            name = "Read Calendar",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.CALENDAR,
            description = "Allows reading calendar events",
            risks = listOf(
                "Schedule exposure",
                "Meeting harvesting"
            ),
            mitigations = listOf(
                "Grant to productivity apps only"
            ),
            secureAlternatives = listOf(
                "Calendar picker"
            )
        ),
        "android.permission.WRITE_CALENDAR" to PermissionDefinition(
            permission = "android.permission.WRITE_CALENDAR",
            name = "Write Calendar",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.CALENDAR,
            description = "Allows modifying calendar",
            risks = listOf(
                "Event manipulation",
                "Spam entries"
            ),
            mitigations = listOf(
                "Limit to calendar apps"
            ),
            secureAlternatives = listOf(
                "Intent-based calendar entry"
            )
        ),

        // Body Sensors - MEDIUM
        "android.permission.BODY_SENSORS" to PermissionDefinition(
            permission = "android.permission.BODY_SENSORS",
            name = "Body Sensors",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.SENSORS,
            description = "Allows body sensor access",
            risks = listOf(
                "Health data exposure",
                "Activity tracking"
            ),
            mitigations = listOf(
                "Grant only to fitness apps"
            ),
            secureAlternatives = listOf(
                "Health Connect API"
            )
        ),
        "android.permission.ACTIVITY_RECOGNITION" to PermissionDefinition(
            permission = "android.permission.ACTIVITY_RECOGNITION",
            name = "Activity Recognition",
            riskLevel = RiskLevel.MEDIUM,
            category = PermissionCategory.SENSORS,
            description = "Detects physical activity",
            risks = listOf(
                "Movement profiling",
                "Behavioral analysis"
            ),
            mitigations = listOf(
                "Review app purpose"
            ),
            secureAlternatives = emptyList()
        ),

        // Special Permissions - CRITICAL
        "android.permission.SYSTEM_ALERT_WINDOW" to PermissionDefinition(
            permission = "android.permission.SYSTEM_ALERT_WINDOW",
            name = "Draw Over Apps",
            riskLevel = RiskLevel.CRITICAL,
            category = PermissionCategory.SPECIAL,
            description = "Allows drawing over apps",
            risks = listOf(
                "Clickjacking attacks",
                "Credential theft",
                "Phishing overlays"
            ),
            mitigations = listOf(
                "Deny to untrusted apps"
            ),
            secureAlternatives = listOf(
                "Bubbles API",
                "Picture-in-picture"
            )
        ),
        "android.permission.REQUEST_INSTALL_PACKAGES" to PermissionDefinition(
            permission = "android.permission.REQUEST_INSTALL_PACKAGES",
            name = "Install Apps",
            riskLevel = RiskLevel.HIGH,
            category = PermissionCategory.SPECIAL,
            description = "Allows app installation",
            risks = listOf(
                "Sideloading malware"
            ),
            mitigations = listOf(
                "Deny to most apps"
            ),
            secureAlternatives = listOf(
                "Play Store installation"
            )
        )
    )

    /**
     * Get permission info if it exists
     */
    fun getPermissionInfo(permission: String): PermissionDefinition? {
        return dangerousPermissions[permission]
    }

    /**
     * Check if a permission is considered dangerous
     */
    fun isDangerous(permission: String): Boolean {
        return dangerousPermissions.containsKey(permission)
    }

    /**
     * Get all permissions in a category
     */
    fun getByCategory(category: PermissionCategory): List<PermissionDefinition> {
        return dangerousPermissions.values.filter { it.category == category }
    }

    /**
     * Get all permissions by risk level
     */
    fun getByRiskLevel(level: RiskLevel): List<PermissionDefinition> {
        return dangerousPermissions.values.filter { it.riskLevel == level }
    }

    /**
     * Calculate risk score weights for a risk level
     */
    fun getRiskWeight(level: RiskLevel): Int = when (level) {
        RiskLevel.CRITICAL -> 25
        RiskLevel.HIGH -> 15
        RiskLevel.MEDIUM -> 8
        RiskLevel.LOW -> 3
        RiskLevel.INFO -> 1
    }
}
