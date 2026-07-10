package cn.wenling.mahjong.host

import android.annotation.SuppressLint
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.annotation.RequiresApi
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class HostService : Service() {
    private val executor = Executors.newSingleThreadExecutor()
    private val watchdogExecutor = Executors.newSingleThreadScheduledExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val stopping = AtomicBoolean(false)
    private val watchdogFailures = AtomicInteger(0)
    private var cpuWakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var watchdogTask: ScheduledFuture<*>? = null
    private var closeHotspotReservation: (() -> Unit)? = null
    private var connectionMode = ConnectionMode.LAN

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopHost()
            return START_NOT_STICKY
        }
        stopping.set(false)

        connectionMode = ConnectionMode.fromValue(
            intent?.getStringExtra(EXTRA_CONNECTION_MODE)
                ?: HostNetworkStateStore.selectedMode(this).value,
        )
        HostNetworkStateStore.selectMode(this, connectionMode)
        HostNetworkStateStore.markStarting(this, connectionMode)
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification(
                if (connectionMode == ConnectionMode.HOTSPOT) {
                    "正在创建麻将专用热点…"
                } else {
                    "正在启动局域网房间…"
                },
            ),
            foregroundServiceType(),
        )
        acquireRuntimeLocks()
        startWatchdog()
        val currentStatus = runCatching { PythonBridge.status() }.getOrNull()
        if (currentStatus?.optBoolean("running", false) == true) {
            val port = currentStatus.optInt("port", DEFAULT_PORT)
            HostNetworkStateStore.markRunning(this)
            notifyStatus("${connectionModeLabel()} · 房间后台运行中 · 端口 $port")
            return START_STICKY
        }
        if (connectionMode == ConnectionMode.HOTSPOT) {
            startLocalOnlyHotspot()
        } else {
            startPythonHost()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopping.set(true)
        stopWatchdog()
        closeHotspot()
        releaseRuntimeLocks()
        runCatching { executor.execute { runCatching { PythonBridge.stop() } } }
        executor.shutdown()
        watchdogExecutor.shutdownNow()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        if (!stopping.get()) {
            acquireRuntimeLocks()
            notifyStatus("${connectionModeLabel()} · 房间后台运行中")
            scheduleRestartFallback()
        }
        super.onTaskRemoved(rootIntent)
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        if (!stopping.get()) {
            acquireRuntimeLocks()
        }
    }

    private fun foregroundServiceType(): Int =
        if (Build.VERSION.SDK_INT >= 30) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE or
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }

    @SuppressLint("WakelockTimeout")
    @Suppress("DEPRECATION")
    private fun acquireRuntimeLocks() {
        if (cpuWakeLock?.isHeld != true) {
            cpuWakeLock = (getSystemService(POWER_SERVICE) as PowerManager)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$packageName:lan-room-cpu")
                .apply {
                    setReferenceCounted(false)
                    acquire()
                }
        }
        if (wifiLock?.isHeld != true) {
            wifiLock = (applicationContext.getSystemService(WIFI_SERVICE) as WifiManager)
                .createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "$packageName:lan-room-wifi")
                .apply {
                    setReferenceCounted(false)
                    acquire()
                }
        }
    }

    private fun releaseRuntimeLocks() {
        wifiLock?.let { lock ->
            if (lock.isHeld) runCatching { lock.release() }
        }
        wifiLock = null
        cpuWakeLock?.let { lock ->
            if (lock.isHeld) runCatching { lock.release() }
        }
        cpuWakeLock = null
    }

    private fun startWatchdog() {
        val existing = watchdogTask
        if (existing != null && !existing.isCancelled && !existing.isDone) return
        watchdogTask = watchdogExecutor.scheduleWithFixedDelay(
            { runWatchdogOnce() },
            WATCHDOG_INITIAL_DELAY_SECONDS,
            WATCHDOG_INTERVAL_SECONDS,
            TimeUnit.SECONDS,
        )
    }

    private fun stopWatchdog() {
        watchdogTask?.cancel(true)
        watchdogTask = null
        watchdogFailures.set(0)
    }

    private fun runWatchdogOnce() {
        if (stopping.get()) return
        acquireRuntimeLocks()
        val phase = HostNetworkStateStore.snapshot(this).phase
        if (phase == "starting" || phase == "hotspot_ready") return
        val status = runCatching { PythonBridge.status() }.getOrNull()
        val running = status?.optBoolean("running", false) == true
        val port = status?.optInt("port", DEFAULT_PORT) ?: DEFAULT_PORT
        val healthy = running && checkHttpHealth("http://127.0.0.1:$port/api/health")
        if (healthy) {
            watchdogFailures.set(0)
            return
        }
        if (watchdogFailures.incrementAndGet() >= WATCHDOG_FAILURE_THRESHOLD) {
            recoverPythonHost(port)
        }
    }

    private fun recoverPythonHost(port: Int) {
        if (stopping.get()) return
        notifyStatus("后台自检发现房间无响应，正在恢复…")
        runCatching { PythonBridge.stop() }
        try {
            installStaticAssets()
            PythonBridge.configure(this, port)
            val status = PythonBridge.start()
            HostNetworkStateStore.markRunning(this)
            watchdogFailures.set(0)
            val actualPort = status.optInt("port", port)
            val modeText =
                if (connectionMode == ConnectionMode.HOTSPOT) "专用热点" else "外部局域网"
            notifyStatus("$modeText · 房间运行中 · 端口 $actualPort")
        } catch (error: Exception) {
            mainHandler.post {
                failStart("后台自检恢复失败：${error.message ?: error.javaClass.simpleName}")
            }
        }
    }

    private fun checkHttpHealth(url: String): Boolean {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = WATCHDOG_HTTP_TIMEOUT_MS
                readTimeout = WATCHDOG_HTTP_TIMEOUT_MS
                requestMethod = "GET"
                useCaches = false
            }
            connection.responseCode in 200..299
        } catch (_: Exception) {
            false
        } finally {
            connection?.disconnect()
        }
    }

    @SuppressLint("MissingPermission")
    private fun startLocalOnlyHotspot() {
        if (Build.VERSION.SDK_INT < 26) {
            failStart("麻将专用热点需要 Android 8.0 或更高版本")
            return
        }
        startLocalOnlyHotspotApi26()
    }

    @RequiresApi(26)
    @SuppressLint("MissingPermission")
    private fun startLocalOnlyHotspotApi26() {
        val wifiManager = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        try {
            wifiManager.startLocalOnlyHotspot(
                object : WifiManager.LocalOnlyHotspotCallback() {
                    override fun onStarted(reservation: WifiManager.LocalOnlyHotspotReservation) {
                        if (stopping.get()) {
                            reservation.close()
                            return
                        }
                        closeHotspotReservation = { reservation.close() }
                        val (ssid, password) = hotspotCredentials(reservation)
                        HostNetworkStateStore.markHotspotReady(this@HostService, ssid, password)
                        notifyStatus("专用热点已开启，正在启动房间…")
                        startPythonHost()
                    }

                    override fun onStopped() {
                        closeHotspotReservation = null
                        if (!stopping.get()) {
                            HostNetworkStateStore.markStarting(this@HostService, ConnectionMode.HOTSPOT)
                            notifyStatus("麻将专用热点被系统暂停，正在重新打开…")
                            mainHandler.postDelayed(
                                { if (!stopping.get()) startLocalOnlyHotspot() },
                                HOTSPOT_RESTART_DELAY_MS,
                            )
                        }
                    }

                    override fun onFailed(reason: Int) {
                        failStart(hotspotFailureMessage(reason))
                    }
                },
                mainHandler,
            )
        } catch (_: SecurityException) {
            failStart("缺少附近 Wi‑Fi/位置信息权限，请授权后重试")
        } catch (error: Exception) {
            failStart("创建麻将专用热点失败：${error.message ?: error.javaClass.simpleName}")
        }
    }

    @Suppress("DEPRECATION")
    @RequiresApi(26)
    private fun hotspotCredentials(
        reservation: WifiManager.LocalOnlyHotspotReservation,
    ): Pair<String?, String?> =
        if (Build.VERSION.SDK_INT >= 30) {
            reservation.softApConfiguration.ssid to reservation.softApConfiguration.passphrase
        } else {
            reservation.wifiConfiguration?.SSID?.trim('"') to
                reservation.wifiConfiguration?.preSharedKey?.trim('"')
        }

    private fun hotspotFailureMessage(reason: Int): String {
        val detail = when (reason) {
            WifiManager.LocalOnlyHotspotCallback.ERROR_NO_CHANNEL -> "当前没有可用 Wi‑Fi 信道"
            WifiManager.LocalOnlyHotspotCallback.ERROR_INCOMPATIBLE_MODE -> "请先关闭系统网络共享热点"
            WifiManager.LocalOnlyHotspotCallback.ERROR_TETHERING_DISALLOWED -> "系统禁止应用创建热点"
            else -> "错误码 $reason"
        }
        return "创建麻将专用热点失败：$detail"
    }

    private fun startPythonHost() {
        executor.execute {
            try {
                val currentStatus = runCatching { PythonBridge.status() }.getOrNull()
                if (currentStatus?.optBoolean("running", false) == true) {
                    val port = currentStatus.optInt("port", DEFAULT_PORT)
                    HostNetworkStateStore.markRunning(this)
                    notifyStatus("${connectionModeLabel()} · 房间后台运行中 · 端口 $port")
                    return@execute
                }
                installStaticAssets()
                PythonBridge.configure(this)
                val status = PythonBridge.start()
                val port = status.optInt("port", 8765)
                HostNetworkStateStore.markRunning(this)
                val modeText =
                    if (connectionMode == ConnectionMode.HOTSPOT) "专用热点" else "外部局域网"
                notifyStatus("$modeText · 房间运行中 · 端口 $port")
            } catch (error: Exception) {
                mainHandler.post {
                    failStart("启动失败：${error.message ?: error.javaClass.simpleName}")
                }
            }
        }
    }

    private fun stopHost() {
        if (!stopping.compareAndSet(false, true)) return
        stopWatchdog()
        notifyStatus("正在关闭房间…")
        executor.execute {
            runCatching { PythonBridge.stop() }
            mainHandler.post {
                closeHotspot()
                HostNetworkStateStore.markStopped(this)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun failStart(message: String) {
        if (stopping.get()) return
        HostNetworkStateStore.markError(this, message)
        notifyStatus(message)
        scheduleRestartFallback(delayMs = FAILURE_RESTART_DELAY_MS)
        stopping.set(true)
        stopWatchdog()
        closeHotspot()
        releaseRuntimeLocks()
        stopForeground(STOP_FOREGROUND_DETACH)
        stopSelf()
    }

    private fun closeHotspot() {
        closeHotspotReservation?.let { close -> runCatching(close) }
        closeHotspotReservation = null
    }

    private fun installStaticAssets() {
        val destination = filesDir.resolve("static-v1")
        if (destination.exists()) {
            destination.deleteRecursively()
        }
        destination.mkdirs()
        for (assetPath in STATIC_ASSET_ROOTS) {
            copyAssetTree(assetPath, destination.resolve(assetPath))
        }
    }

    private fun copyAssetTree(path: String, destination: File) {
        val children = assets.list(path).orEmpty()
        if (children.isEmpty()) {
            if (path.isBlank()) return
            destination.parentFile?.mkdirs()
            assets.open(path).use { input ->
                destination.outputStream().use { output -> input.copyTo(output) }
            }
            return
        }
        destination.mkdirs()
        for (child in children) {
            val childPath = if (path.isBlank()) child else "$path/$child"
            copyAssetTree(childPath, destination.resolve(child))
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "局域网房间",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "保持温岭麻将局域网房间运行"
                    setSound(null, null)
                    enableVibration(false)
                    setShowBadge(false)
                },
            )
        }
    }

    private fun notification(text: String) = NotificationCompat.Builder(this, CHANNEL_ID)
        .setSmallIcon(android.R.drawable.stat_sys_upload)
        .setContentTitle("温岭麻将房主端")
        .setContentText(text)
        .setCategory(NotificationCompat.CATEGORY_SERVICE)
        .setPriority(NotificationCompat.PRIORITY_MAX)
        .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
        .setOnlyAlertOnce(true)
        .setLocalOnly(true)
        .setSilent(true)
        .setUsesChronometer(true)
        .setOngoing(true)
        .setContentIntent(
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            ),
        )
        .addAction(
            0,
            "关闭房间",
            PendingIntent.getService(
                this,
                1,
                Intent(this, HostService::class.java).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            ),
        )
        .build()

    private fun notifyStatus(text: String) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, notification(text))
    }

    private fun connectionModeLabel(): String =
        if (connectionMode == ConnectionMode.HOTSPOT) "手机专用热点" else "外部局域网"

    @SuppressLint("ScheduleExactAlarm")
    private fun scheduleRestartFallback(delayMs: Long = TASK_REMOVED_RESTART_DELAY_MS) {
        if (stopping.get()) return
        val alarmManager = getSystemService(ALARM_SERVICE) as AlarmManager
        val restartIntent = startIntent(applicationContext, connectionMode)
        val pendingIntent =
            if (Build.VERSION.SDK_INT >= 26) {
                PendingIntent.getForegroundService(
                    applicationContext,
                    RESTART_REQUEST_CODE,
                    restartIntent,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
            } else {
                PendingIntent.getService(
                    applicationContext,
                    RESTART_REQUEST_CODE,
                    restartIntent,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
            }
        val triggerAt = SystemClock.elapsedRealtime() + delayMs
        if (Build.VERSION.SDK_INT >= 23) {
            alarmManager.setAndAllowWhileIdle(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                triggerAt,
                pendingIntent,
            )
        } else {
            alarmManager.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pendingIntent)
        }
    }

    companion object {
        const val ACTION_STOP = "cn.wenling.mahjong.host.STOP"
        const val EXTRA_CONNECTION_MODE = "connection_mode"
        private const val DEFAULT_PORT = 8765
        private const val CHANNEL_ID = "wenling-room-v2"
        private const val NOTIFICATION_ID = 8765
        private const val RESTART_REQUEST_CODE = 8766
        private const val TASK_REMOVED_RESTART_DELAY_MS = 1_000L
        private const val FAILURE_RESTART_DELAY_MS = 5_000L
        private const val HOTSPOT_RESTART_DELAY_MS = 1_500L
        private const val WATCHDOG_INITIAL_DELAY_SECONDS = 20L
        private const val WATCHDOG_INTERVAL_SECONDS = 8L
        private const val WATCHDOG_FAILURE_THRESHOLD = 2
        private const val WATCHDOG_HTTP_TIMEOUT_MS = 1500
        private val STATIC_ASSET_ROOTS = listOf(
            "battle.html",
            "battle_login.html",
            "battle_accounts.html",
            "styles.css",
            "battle_layout.css",
            "battle_geometry_v7.css",
            "battle_app.js",
            "battle_lobby.js",
            "battle_lobby.html",
            "photon_scene.js",
            "photon_lobby.css",
            "vendor",
            "battle_accounts.js",
            "battle_table_model.js",
            "battle_table_renderer.js",
            "assets",
        )

        fun stopIntent(context: Context) =
            Intent(context, HostService::class.java).setAction(ACTION_STOP)

        fun startIntent(context: Context, mode: ConnectionMode) =
            Intent(context, HostService::class.java)
                .putExtra(EXTRA_CONNECTION_MODE, mode.value)
    }
}
