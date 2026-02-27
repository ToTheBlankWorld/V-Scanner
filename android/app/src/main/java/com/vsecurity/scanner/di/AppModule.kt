package com.vsecurity.scanner.di

import android.content.Context
import androidx.room.Room
import com.vsecurity.scanner.data.local.*
import com.vsecurity.scanner.data.preferences.PreferencesManager
import com.vsecurity.scanner.data.repository.GuardianRepository
import com.vsecurity.scanner.data.repository.ScannerRepository
import com.vsecurity.scanner.scanner.AppScanner
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): VScannerDatabase {
        return Room.databaseBuilder(
            context,
            VScannerDatabase::class.java,
            "vscanner_database"
        )
            .fallbackToDestructiveMigration()
            .build()
    }

    @Provides
    fun provideScannedAppDao(database: VScannerDatabase): ScannedAppDao {
        return database.scannedAppDao()
    }

    @Provides
    fun provideSensorAccessLogDao(database: VScannerDatabase): SensorAccessLogDao {
        return database.sensorAccessLogDao()
    }

    @Provides
    fun providePrivacyAlertDao(database: VScannerDatabase): PrivacyAlertDao {
        return database.privacyAlertDao()
    }

    @Provides
    fun provideAppSensorStatsDao(database: VScannerDatabase): AppSensorStatsDao {
        return database.appSensorStatsDao()
    }

    @Provides
    fun provideDailySummaryDao(database: VScannerDatabase): DailySummaryDao {
        return database.dailySummaryDao()
    }

    @Provides
    @Singleton
    fun provideGuardianRepository(
        sensorAccessLogDao: SensorAccessLogDao,
        privacyAlertDao: PrivacyAlertDao,
        appSensorStatsDao: AppSensorStatsDao,
        dailySummaryDao: DailySummaryDao
    ): GuardianRepository {
        return GuardianRepository(
            sensorAccessLogDao,
            privacyAlertDao,
            appSensorStatsDao,
            dailySummaryDao
        )
    }

    @Provides
    @Singleton
    fun provideScannerRepository(scannedAppDao: ScannedAppDao): ScannerRepository {
        return ScannerRepository(scannedAppDao)
    }

    @Provides
    @Singleton
    fun providePreferencesManager(@ApplicationContext context: Context): PreferencesManager {
        return PreferencesManager(context)
    }

    @Provides
    @Singleton
    fun provideAppScanner(@ApplicationContext context: Context): AppScanner {
        return AppScanner(context)
    }
}
