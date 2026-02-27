package com.vsecurity.scanner.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

// Color palette
val SecurityGreen = Color(0xFF00C853)
val SecurityBlue = Color(0xFF2962FF)
val WarningOrange = Color(0xFFFF6D00)
val DangerRed = Color(0xFFD50000)
val CriticalPurple = Color(0xFFAA00FF)

// Dark theme colors
private val DarkColorScheme = darkColorScheme(
    primary = SecurityBlue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF1A237E),
    secondary = SecurityGreen,
    onSecondary = Color.Black,
    secondaryContainer = Color(0xFF1B5E20),
    tertiary = CriticalPurple,
    background = Color(0xFF0D1117),
    surface = Color(0xFF161B22),
    surfaceVariant = Color(0xFF21262D),
    error = DangerRed,
    onBackground = Color.White,
    onSurface = Color.White,
    onSurfaceVariant = Color(0xFFB0B0B0)
)

// Light theme colors
private val LightColorScheme = lightColorScheme(
    primary = SecurityBlue,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE3F2FD),
    secondary = SecurityGreen,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8F5E9),
    tertiary = CriticalPurple,
    background = Color(0xFFF5F5F5),
    surface = Color.White,
    surfaceVariant = Color(0xFFE0E0E0),
    error = DangerRed,
    onBackground = Color.Black,
    onSurface = Color.Black,
    onSurfaceVariant = Color(0xFF606060)
)

@Composable
fun VScannerTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }
    
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.background.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}

val Typography = Typography()
