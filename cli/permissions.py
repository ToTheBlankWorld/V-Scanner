"""
Permission Analysis Module for Android App Security Scanner

Defines dangerous permissions, risk levels, and mitigation strategies.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Optional


class RiskLevel(Enum):
    """Risk level classification for permissions."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class PermissionInfo:
    """Information about an Android permission."""
    name: str
    risk_level: RiskLevel
    category: str
    description: str
    risks: List[str]
    mitigations: List[str]
    secure_alternatives: List[str]


# Comprehensive permission database
DANGEROUS_PERMISSIONS: Dict[str, PermissionInfo] = {
    # SMS Permissions - CRITICAL
    "android.permission.READ_SMS": PermissionInfo(
        name="READ_SMS",
        risk_level=RiskLevel.CRITICAL,
        category="SMS",
        description="Allows reading SMS messages",
        risks=[
            "Can read OTP/2FA codes",
            "Access to personal conversations",
            "Financial data exposure (bank SMS)",
            "Identity theft risk"
        ],
        mitigations=[
            "Revoke if not essential for app function",
            "Use SMS Retriever API instead",
            "Enable 2FA with authenticator apps"
        ],
        secure_alternatives=[
            "Google SMS Retriever API",
            "Push notifications for OTP"
        ]
    ),
    "android.permission.SEND_SMS": PermissionInfo(
        name="SEND_SMS",
        risk_level=RiskLevel.CRITICAL,
        category="SMS",
        description="Allows sending SMS messages",
        risks=[
            "Unauthorized SMS charges",
            "Spam distribution",
            "Premium SMS fraud",
            "Phishing attacks"
        ],
        mitigations=[
            "Deny unless messaging app",
            "Monitor phone bills regularly",
            "Use Intent-based SMS for occasional sends"
        ],
        secure_alternatives=[
            "Intent ACTION_SENDTO",
            "In-app messaging services"
        ]
    ),
    "android.permission.RECEIVE_SMS": PermissionInfo(
        name="RECEIVE_SMS",
        risk_level=RiskLevel.CRITICAL,
        category="SMS",
        description="Allows receiving SMS messages",
        risks=[
            "Intercept OTP codes",
            "Privacy violation",
            "SMS-based attacks"
        ],
        mitigations=[
            "Review which apps have this permission",
            "Use authenticator apps for 2FA"
        ],
        secure_alternatives=[
            "SMS Retriever API",
            "Firebase Auth phone verification"
        ]
    ),

    # Contact Permissions - HIGH
    "android.permission.READ_CONTACTS": PermissionInfo(
        name="READ_CONTACTS",
        risk_level=RiskLevel.HIGH,
        category="Contacts",
        description="Allows reading contact data",
        risks=[
            "Contact list harvesting",
            "Social engineering attacks",
            "Spam targeting contacts",
            "Privacy breach"
        ],
        mitigations=[
            "Grant only to trusted communication apps",
            "Review app reviews before granting",
            "Use contact picker for single selections"
        ],
        secure_alternatives=[
            "Contact Picker API",
            "Manual contact entry"
        ]
    ),
    "android.permission.WRITE_CONTACTS": PermissionInfo(
        name="WRITE_CONTACTS",
        risk_level=RiskLevel.HIGH,
        category="Contacts",
        description="Allows modifying contact data",
        risks=[
            "Contact manipulation",
            "Malicious contact injection",
            "Data corruption"
        ],
        mitigations=[
            "Deny to most apps",
            "Backup contacts regularly"
        ],
        secure_alternatives=[
            "Intent-based contact creation"
        ]
    ),

    # Camera Permissions - HIGH
    "android.permission.CAMERA": PermissionInfo(
        name="CAMERA",
        risk_level=RiskLevel.HIGH,
        category="Camera",
        description="Allows access to device camera",
        risks=[
            "Unauthorized photo/video capture",
            "Surveillance without consent",
            "Privacy invasion",
            "Facial recognition abuse"
        ],
        mitigations=[
            "Grant only when actively using camera features",
            "Revoke when not needed",
            "Use camera covers",
            "Check indicator lights"
        ],
        secure_alternatives=[
            "Intent ACTION_IMAGE_CAPTURE",
            "External camera apps"
        ]
    ),

    # Location Permissions - HIGH
    "android.permission.ACCESS_FINE_LOCATION": PermissionInfo(
        name="ACCESS_FINE_LOCATION",
        risk_level=RiskLevel.HIGH,
        category="Location",
        description="Allows precise GPS location access",
        risks=[
            "Real-time tracking",
            "Location history exposure",
            "Stalking enablement",
            "Home/work location inference"
        ],
        mitigations=[
            "Use 'While using app' option",
            "Deny background location",
            "Use coarse location when possible"
        ],
        secure_alternatives=[
            "Coarse location for general apps",
            "On-demand location requests"
        ]
    ),
    "android.permission.ACCESS_COARSE_LOCATION": PermissionInfo(
        name="ACCESS_COARSE_LOCATION",
        risk_level=RiskLevel.MEDIUM,
        category="Location",
        description="Allows approximate location access",
        risks=[
            "General area tracking",
            "Behavioral profiling"
        ],
        mitigations=[
            "Prefer over fine location",
            "Review necessity"
        ],
        secure_alternatives=[
            "IP-based geolocation",
            "Manual location entry"
        ]
    ),
    "android.permission.ACCESS_BACKGROUND_LOCATION": PermissionInfo(
        name="ACCESS_BACKGROUND_LOCATION",
        risk_level=RiskLevel.CRITICAL,
        category="Location",
        description="Allows location access in background",
        risks=[
            "Continuous tracking without awareness",
            "Battery drain",
            "Comprehensive movement history"
        ],
        mitigations=[
            "Deny to most apps",
            "Allow only for navigation/fitness apps",
            "Regular audit"
        ],
        secure_alternatives=[
            "Geofencing APIs",
            "User-triggered location updates"
        ]
    ),

    # Microphone Permissions - HIGH
    "android.permission.RECORD_AUDIO": PermissionInfo(
        name="RECORD_AUDIO",
        risk_level=RiskLevel.HIGH,
        category="Microphone",
        description="Allows audio recording",
        risks=[
            "Eavesdropping",
            "Conversation recording",
            "Voice data collection",
            "Background listening"
        ],
        mitigations=[
            "Grant only to call/voice apps",
            "Revoke when not needed",
            "Check mic indicator"
        ],
        secure_alternatives=[
            "Speech-to-text APIs",
            "Intent-based voice input"
        ]
    ),

    # Storage Permissions - MEDIUM to HIGH
    "android.permission.READ_EXTERNAL_STORAGE": PermissionInfo(
        name="READ_EXTERNAL_STORAGE",
        risk_level=RiskLevel.MEDIUM,
        category="Storage",
        description="Allows reading external storage",
        risks=[
            "Access to photos/documents",
            "Personal data exposure",
            "Downloaded file access"
        ],
        mitigations=[
            "Use scoped storage",
            "Grant selective media access"
        ],
        secure_alternatives=[
            "Storage Access Framework",
            "Media Store API"
        ]
    ),
    "android.permission.WRITE_EXTERNAL_STORAGE": PermissionInfo(
        name="WRITE_EXTERNAL_STORAGE",
        risk_level=RiskLevel.MEDIUM,
        category="Storage",
        description="Allows writing to external storage",
        risks=[
            "File manipulation",
            "Malware installation",
            "Data corruption"
        ],
        mitigations=[
            "Use app-specific directories",
            "Review file access patterns"
        ],
        secure_alternatives=[
            "App-specific storage",
            "Scoped storage (Android 10+)"
        ]
    ),
    "android.permission.MANAGE_EXTERNAL_STORAGE": PermissionInfo(
        name="MANAGE_EXTERNAL_STORAGE",
        risk_level=RiskLevel.CRITICAL,
        category="Storage",
        description="Allows full external storage management",
        risks=[
            "Complete file system access",
            "All app data accessible",
            "System file manipulation"
        ],
        mitigations=[
            "Only for file managers",
            "Deny to other apps"
        ],
        secure_alternatives=[
            "SAF for document access",
            "MediaStore for media"
        ]
    ),

    # Phone Permissions - HIGH
    "android.permission.READ_PHONE_STATE": PermissionInfo(
        name="READ_PHONE_STATE",
        risk_level=RiskLevel.MEDIUM,
        category="Phone",
        description="Allows reading phone state and identity",
        risks=[
            "Device fingerprinting",
            "IMEI/phone number exposure",
            "Call state monitoring"
        ],
        mitigations=[
            "Deny if not call-related",
            "Review data collection policies"
        ],
        secure_alternatives=[
            "Instance ID for app identification"
        ]
    ),
    "android.permission.CALL_PHONE": PermissionInfo(
        name="CALL_PHONE",
        risk_level=RiskLevel.HIGH,
        category="Phone",
        description="Allows initiating phone calls",
        risks=[
            "Premium number calls",
            "Unauthorized charges",
            "Harassment potential"
        ],
        mitigations=[
            "Use dial intent instead",
            "Review call logs"
        ],
        secure_alternatives=[
            "Intent ACTION_DIAL"
        ]
    ),
    "android.permission.READ_CALL_LOG": PermissionInfo(
        name="READ_CALL_LOG",
        risk_level=RiskLevel.HIGH,
        category="Phone",
        description="Allows reading call history",
        risks=[
            "Communication pattern exposure",
            "Contact relationship mapping",
            "Privacy violation"
        ],
        mitigations=[
            "Deny to most apps",
            "Clear call logs periodically"
        ],
        secure_alternatives=[
            "No direct alternative - limit access"
        ]
    ),

    # Calendar Permissions - MEDIUM
    "android.permission.READ_CALENDAR": PermissionInfo(
        name="READ_CALENDAR",
        risk_level=RiskLevel.MEDIUM,
        category="Calendar",
        description="Allows reading calendar events",
        risks=[
            "Schedule exposure",
            "Meeting attendee harvesting",
            "Location pattern inference"
        ],
        mitigations=[
            "Grant only to productivity apps",
            "Review synced accounts"
        ],
        secure_alternatives=[
            "CalendarContract.Events picker"
        ]
    ),
    "android.permission.WRITE_CALENDAR": PermissionInfo(
        name="WRITE_CALENDAR",
        risk_level=RiskLevel.MEDIUM,
        category="Calendar",
        description="Allows modifying calendar events",
        risks=[
            "Event manipulation",
            "Spam calendar entries",
            "Schedule disruption"
        ],
        mitigations=[
            "Limit to calendar apps",
            "Review calendar changes"
        ],
        secure_alternatives=[
            "Intent-based calendar entry"
        ]
    ),

    # Body Sensors - MEDIUM
    "android.permission.BODY_SENSORS": PermissionInfo(
        name="BODY_SENSORS",
        risk_level=RiskLevel.MEDIUM,
        category="Sensors",
        description="Allows access to body sensors (heart rate, etc.)",
        risks=[
            "Health data exposure",
            "Activity tracking",
            "Medical privacy breach"
        ],
        mitigations=[
            "Grant only to fitness apps",
            "Review data sharing policies"
        ],
        secure_alternatives=[
            "Health Connect API"
        ]
    ),

    # Network Permissions - LOW to MEDIUM
    "android.permission.INTERNET": PermissionInfo(
        name="INTERNET",
        risk_level=RiskLevel.LOW,
        category="Network",
        description="Allows internet access",
        risks=[
            "Data exfiltration possible",
            "Network attacks",
            "Privacy leaks"
        ],
        mitigations=[
            "Monitor data usage",
            "Use firewall apps"
        ],
        secure_alternatives=[
            "Offline modes when available"
        ]
    ),
    "android.permission.ACCESS_WIFI_STATE": PermissionInfo(
        name="ACCESS_WIFI_STATE",
        risk_level=RiskLevel.LOW,
        category="Network",
        description="Allows viewing Wi-Fi connection info",
        risks=[
            "Network fingerprinting",
            "Location inference via Wi-Fi"
        ],
        mitigations=[
            "Standard permission, low risk"
        ],
        secure_alternatives=[]
    ),

    # Special Permissions - CRITICAL
    "android.permission.SYSTEM_ALERT_WINDOW": PermissionInfo(
        name="SYSTEM_ALERT_WINDOW",
        risk_level=RiskLevel.CRITICAL,
        category="Special",
        description="Allows drawing over other apps",
        risks=[
            "Clickjacking attacks",
            "Credential theft overlays",
            "Screen recording",
            "Phishing overlays"
        ],
        mitigations=[
            "Deny to untrusted apps",
            "Review overlay permissions in settings"
        ],
        secure_alternatives=[
            "Bubbles API (Android 11+)",
            "Picture-in-picture"
        ]
    ),
    "android.permission.BIND_ACCESSIBILITY_SERVICE": PermissionInfo(
        name="BIND_ACCESSIBILITY_SERVICE",
        risk_level=RiskLevel.CRITICAL,
        category="Special",
        description="Allows accessibility service binding",
        risks=[
            "Full screen content access",
            "Keylogging potential",
            "Action automation abuse",
            "Complete device control"
        ],
        mitigations=[
            "Enable only for trusted accessibility apps",
            "Regular audit of accessibility services"
        ],
        secure_alternatives=[
            "Standard UI automation APIs"
        ]
    ),
    "android.permission.BIND_DEVICE_ADMIN": PermissionInfo(
        name="BIND_DEVICE_ADMIN",
        risk_level=RiskLevel.CRITICAL,
        category="Special",
        description="Allows device administration",
        risks=[
            "Device wipe capability",
            "Password policy control",
            "Device lock",
            "Data encryption control"
        ],
        mitigations=[
            "Only for MDM/enterprise apps",
            "Review device admin apps"
        ],
        secure_alternatives=[
            "Work profile for enterprise"
        ]
    ),
    "android.permission.REQUEST_INSTALL_PACKAGES": PermissionInfo(
        name="REQUEST_INSTALL_PACKAGES",
        risk_level=RiskLevel.HIGH,
        category="Special",
        description="Allows requesting package installation",
        risks=[
            "Sideloading malware",
            "Unauthorized app installation"
        ],
        mitigations=[
            "Deny to most apps",
            "Install only from trusted sources"
        ],
        secure_alternatives=[
            "Play Store installation"
        ]
    ),
}


# SDK version security thresholds
SDK_SECURITY_INFO = {
    "min_recommended": 28,  # Android 9.0 Pie
    "min_secure": 26,       # Android 8.0 Oreo
    "deprecated": 23,       # Android 6.0 Marshmallow
    "versions": {
        34: {"name": "Android 14", "status": "Current", "risk": RiskLevel.INFO},
        33: {"name": "Android 13", "status": "Supported", "risk": RiskLevel.INFO},
        32: {"name": "Android 12L", "status": "Supported", "risk": RiskLevel.INFO},
        31: {"name": "Android 12", "status": "Supported", "risk": RiskLevel.LOW},
        30: {"name": "Android 11", "status": "Limited Support", "risk": RiskLevel.LOW},
        29: {"name": "Android 10", "status": "Security Updates Only", "risk": RiskLevel.MEDIUM},
        28: {"name": "Android 9 Pie", "status": "EOL", "risk": RiskLevel.MEDIUM},
        27: {"name": "Android 8.1 Oreo", "status": "EOL", "risk": RiskLevel.HIGH},
        26: {"name": "Android 8.0 Oreo", "status": "EOL", "risk": RiskLevel.HIGH},
        25: {"name": "Android 7.1 Nougat", "status": "EOL", "risk": RiskLevel.HIGH},
        24: {"name": "Android 7.0 Nougat", "status": "EOL", "risk": RiskLevel.HIGH},
        23: {"name": "Android 6.0 Marshmallow", "status": "EOL", "risk": RiskLevel.CRITICAL},
    }
}


# Insecure URL patterns
INSECURE_URL_PATTERNS = [
    r'http://(?!localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)',  # Non-HTTPS external URLs
    r'https?://[^/]*\.(example|test|localhost)\.',  # Test domains
    r'api[_-]?key\s*[=:]\s*["\'][^"\']+["\']',  # Hardcoded API keys
    r'password\s*[=:]\s*["\'][^"\']+["\']',  # Hardcoded passwords
    r'secret\s*[=:]\s*["\'][^"\']+["\']',  # Hardcoded secrets
    r'token\s*[=:]\s*["\'][^"\']+["\']',  # Hardcoded tokens
    r'aws[_-]?(?:access|secret)[_-]?key',  # AWS credentials
    r'firebase[_-]?(?:api[_-]?key|url)',  # Firebase config
]


def get_permission_info(permission: str) -> Optional[PermissionInfo]:
    """Get detailed information about a permission."""
    return DANGEROUS_PERMISSIONS.get(permission)


def analyze_permissions(permissions: List[str]) -> Dict:
    """
    Analyze a list of permissions and return security assessment.
    
    Returns dict with:
    - risk_score: Overall risk score (0-100)
    - risk_level: Overall risk level
    - dangerous_permissions: List of dangerous permissions found
    - recommendations: List of security recommendations
    """
    dangerous_found = []
    categories = {}
    risk_score = 0
    
    for perm in permissions:
        info = get_permission_info(perm)
        if info:
            dangerous_found.append(info)
            
            # Track categories
            if info.category not in categories:
                categories[info.category] = []
            categories[info.category].append(info)
            
            # Calculate risk contribution
            risk_weights = {
                RiskLevel.CRITICAL: 25,
                RiskLevel.HIGH: 15,
                RiskLevel.MEDIUM: 8,
                RiskLevel.LOW: 3,
                RiskLevel.INFO: 1
            }
            risk_score += risk_weights.get(info.risk_level, 0)
    
    # Cap risk score at 100
    risk_score = min(100, risk_score)
    
    # Determine overall risk level
    if risk_score >= 70:
        overall_risk = RiskLevel.CRITICAL
    elif risk_score >= 50:
        overall_risk = RiskLevel.HIGH
    elif risk_score >= 30:
        overall_risk = RiskLevel.MEDIUM
    elif risk_score >= 10:
        overall_risk = RiskLevel.LOW
    else:
        overall_risk = RiskLevel.INFO
    
    # Generate recommendations
    recommendations = []
    for info in dangerous_found:
        for mitigation in info.mitigations[:2]:  # Top 2 mitigations
            recommendations.append(f"[{info.name}] {mitigation}")
    
    return {
        "risk_score": risk_score,
        "risk_level": overall_risk,
        "dangerous_permissions": dangerous_found,
        "categories": categories,
        "recommendations": recommendations,
        "total_permissions": len(permissions),
        "dangerous_count": len(dangerous_found)
    }


def get_sdk_risk(target_sdk: int, min_sdk: int) -> Dict:
    """Analyze SDK version risks."""
    sdk_info = SDK_SECURITY_INFO["versions"]
    
    target_info = sdk_info.get(target_sdk, {
        "name": f"API {target_sdk}",
        "status": "Unknown",
        "risk": RiskLevel.MEDIUM
    })
    
    min_info = sdk_info.get(min_sdk, {
        "name": f"API {min_sdk}",
        "status": "Unknown",
        "risk": RiskLevel.HIGH if min_sdk < 26 else RiskLevel.MEDIUM
    })
    
    recommendations = []
    
    if target_sdk < SDK_SECURITY_INFO["min_recommended"]:
        recommendations.append(
            f"Target SDK {target_sdk} is below recommended minimum ({SDK_SECURITY_INFO['min_recommended']})"
        )
    
    if min_sdk < SDK_SECURITY_INFO["min_secure"]:
        recommendations.append(
            f"Min SDK {min_sdk} allows installation on insecure Android versions"
        )
    
    if min_sdk < SDK_SECURITY_INFO["deprecated"]:
        recommendations.append(
            f"Min SDK {min_sdk} is deprecated and has known vulnerabilities"
        )
    
    return {
        "target_sdk": target_sdk,
        "target_info": target_info,
        "min_sdk": min_sdk,
        "min_info": min_info,
        "recommendations": recommendations
    }
