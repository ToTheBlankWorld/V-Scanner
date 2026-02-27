# V Scanner ProGuard Rules

# Keep Hilt classes
-keep class dagger.hilt.** { *; }
-keep class javax.inject.** { *; }
-keep class * extends dagger.hilt.android.internal.managers.ComponentSupplier { *; }
-keep class * extends dagger.hilt.android.internal.managers.ViewComponentManager$FragmentContextWrapper { *; }

# Keep Room entities
-keep class com.vsecurity.scanner.data.model.** { *; }
-keep class * extends androidx.room.RoomDatabase { *; }

# Keep Kotlin serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

# Keep data classes for reflection
-keepclassmembers class com.vsecurity.scanner.data.model.* {
    <fields>;
    <init>(...);
}

# Keep ViewModels
-keep class com.vsecurity.scanner.ui.viewmodel.** { *; }

# Keep Compose
-keep class androidx.compose.** { *; }

# Keep Material Design
-keep class com.google.android.material.** { *; }

# Standard Android optimizations
-optimizationpasses 5
-dontusemixedcaseclassnames
-dontskipnonpubliclibraryclasses
-dontpreverify
-verbose

# Remove logging in release
-assumenosideeffects class android.util.Log {
    public static *** d(...);
    public static *** v(...);
    public static *** i(...);
}
