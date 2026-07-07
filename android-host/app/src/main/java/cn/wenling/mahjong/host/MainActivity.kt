package cn.wenling.mahjong.host

import android.Manifest
import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.speech.tts.TextToSpeech
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

private val MahjongGreen = Color(0xFF173F35)
private val MahjongGold = Color(0xFFD7A941)
private val MahjongCream = Color(0xFFF7F0DE)
private val Danger = Color(0xFF9B2C2C)

private class AndroidSpeechBridge(context: Context) : TextToSpeech.OnInitListener {
    private var tts: TextToSpeech? = null
    private var ready = false
    private var pendingText: String? = null

    init {
        tts = TextToSpeech(context.applicationContext, this)
    }

    override fun onInit(status: Int) {
        ready = status == TextToSpeech.SUCCESS
        if (ready) {
            tts?.language = Locale.CHINA
            pendingText?.let { speak(it) }
            pendingText = null
        }
    }

    @JavascriptInterface
    fun speak(text: String?) {
        val value = text?.trim().orEmpty()
        if (value.isEmpty()) return
        if (!ready) {
            pendingText = value
            return
        }
        tts?.speak(value, TextToSpeech.QUEUE_FLUSH, null, "battle-${System.nanoTime()}")
    }

    fun shutdown() {
        pendingText = null
        ready = false
        tts?.stop()
        tts?.shutdown()
        tts = null
    }
}

class MainActivity : ComponentActivity() {
    private val model: HostViewModel by viewModels()
    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private val hotspotPermissions =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { results ->
            if (results.values.all { it }) {
                model.startRoom()
            } else {
                model.reportError("手机专用热点需要附近 Wi‑Fi/位置信息权限")
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent {
            MaterialTheme {
                Surface(color = MahjongCream, modifier = Modifier.fillMaxSize()) {
                    var ownerBattlePort by remember { mutableStateOf<Int?>(null) }
                    val port = ownerBattlePort
                    if (port != null) {
                        OwnerBattleWebViewScreen(port = port, onClose = { ownerBattlePort = null })
                    } else {
                        HostScreen(
                            model,
                            ::startSelectedRoom,
                            { selectedPort -> ownerBattlePort = selectedPort },
                            ::requestBatteryUnrestricted,
                        )
                    }
                }
            }
        }
    }

    private fun startSelectedRoom() {
        requestBatteryUnrestricted()
        if (model.state.value.connectionMode != ConnectionMode.HOTSPOT) {
            model.startRoom()
            return
        }
        if (Build.VERSION.SDK_INT < 26) {
            model.reportError("手机专用热点需要 Android 8.0 或更高版本")
            return
        }
        val required = when {
            Build.VERSION.SDK_INT >= 33 -> listOf(Manifest.permission.NEARBY_WIFI_DEVICES)
            else -> listOf(
                Manifest.permission.ACCESS_FINE_LOCATION,
                Manifest.permission.ACCESS_COARSE_LOCATION,
            )
        }
        val missing = required.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) {
            model.startRoom()
        } else {
            hotspotPermissions.launch(missing.toTypedArray())
        }
    }

    private fun openOwnerBattle(port: Int) {
        val url = "http://127.0.0.1:$port/battle-login"
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        }.onFailure {
            model.reportError("未找到可打开对局页面的浏览器：${it.message ?: "未知错误"}")
        }
    }

    @SuppressLint("BatteryLife")
    private fun requestBatteryUnrestricted() {
        if (Build.VERSION.SDK_INT < 23) return
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        if (powerManager.isIgnoringBatteryOptimizations(packageName)) return
        val request = Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.parse("package:$packageName"),
        )
        runCatching {
            startActivity(request)
        }.onFailure {
            runCatching {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            }.onFailure { error ->
                model.reportError("无法打开后台运行设置：${error.message ?: "未知错误"}")
            }
        }
    }
}

@Composable
private fun HostScreen(
    model: HostViewModel,
    onStartRoom: () -> Unit,
    onOpenOwnerBattle: (Int) -> Unit,
    onRequestBatteryUnrestricted: () -> Unit,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val state by model.state.collectAsStateWithLifecycle()
    var confirmStop by remember { mutableStateOf(false) }
    val needsBatteryExemption =
        Build.VERSION.SDK_INT >= 23 &&
            !(context.getSystemService(Context.POWER_SERVICE) as PowerManager)
                .isIgnoringBatteryOptimizations(context.packageName)
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MahjongGreen, RoundedCornerShape(18.dp))
                    .padding(20.dp),
            ) {
                Text("温岭麻将房主端", color = Color.White, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text(
                    when {
                        state.running -> "房间正在运行 · ${connectionModeName(state.connectionMode)}"
                        state.starting -> "正在准备${connectionModeName(state.connectionMode)}…"
                        else -> "房间已关闭，可选择连接方式"
                    },
                    color = Color.White.copy(alpha = 0.82f),
                )
                Spacer(Modifier.height(14.dp))
                Button(
                    onClick = { if (state.running) confirmStop = true else onStartRoom() },
                    enabled = !state.loading && !state.starting,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (state.running) Danger else MahjongGold,
                        contentColor = Color.White,
                    ),
                ) {
                    Text(
                        when {
                            state.running -> "关闭房间"
                            state.starting -> "启动中…"
                            else -> "启动房间"
                        },
                    )
                }
                state.error?.let { Text(it, color = Color(0xFFFFC8C8), modifier = Modifier.padding(top = 8.dp)) }
            }
        }

        if (needsBatteryExemption) {
            item { BackgroundKeepAliveCard(onRequestBatteryUnrestricted) }
        }

        if (state.running) {
            item { ConnectionCard(state, onOpenOwnerBattle) }
            item { RoomCard(state, model) }
        } else if (state.starting) {
            item {
                HostCard("正在启动") {
                    Text(
                        if (state.connectionMode == ConnectionMode.HOTSPOT) {
                            "系统正在创建专用热点并启动牌局服务，通常需要几秒钟。"
                        } else {
                            "正在启动牌局服务并检测局域网地址。"
                        },
                    )
                }
            }
        } else {
            item { ConnectionModeCard(state, model) }
            item { OfflineAccountsCard(state, model) }
        }
    }

    if (confirmStop) {
        AlertDialog(
            onDismissRequest = { confirmStop = false },
            title = { Text("关闭当前房间？") },
            text = { Text("所有玩家会话会立即失效，进行中的小局不会恢复。已落库的统计会保留。") },
            confirmButton = {
                TextButton(onClick = {
                    confirmStop = false
                    model.stopRoom()
                }) { Text("确认关闭", color = Danger) }
            },
            dismissButton = { TextButton(onClick = { confirmStop = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun BackgroundKeepAliveCard(onRequestBatteryUnrestricted: () -> Unit) {
    HostCard("后台保活") {
        Text("如果锁屏或切到后台后玩家端不刷新，请允许本应用忽略电池优化。房间运行时仍会显示前台通知。")
        Button(
            onClick = onRequestBatteryUnrestricted,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = MahjongGold),
        ) {
            Text("允许后台运行")
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun OwnerBattleWebViewScreen(port: Int, onClose: () -> Unit) {
    val context = LocalContext.current
    val url = remember(port) { "http://127.0.0.1:$port/battle-login" }
    val speechBridge = remember { AndroidSpeechBridge(context) }
    var webView by remember { mutableStateOf<WebView?>(null) }

    BackHandler { onClose() }
    DisposableEffect(Unit) {
        val activity = context as? ComponentActivity
        activity?.window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose {
            webView?.destroy()
            webView = null
            speechBridge.shutdown()
            activity?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MahjongGreen),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF0B241E))
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "房主 App 内对局",
                color = MahjongCream,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f),
            )
            OutlinedButton(onClick = { webView?.reload() }) { Text("刷新") }
            Button(
                onClick = onClose,
                colors = ButtonDefaults.buttonColors(containerColor = Danger),
            ) { Text("关闭") }
        }
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { viewContext ->
                WebView(viewContext).apply {
                    layoutParams = ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT,
                    )
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.cacheMode = WebSettings.LOAD_DEFAULT
                    settings.useWideViewPort = true
                    settings.loadWithOverviewMode = true
                    settings.mediaPlaybackRequiresUserGesture = false
                    webChromeClient = WebChromeClient()
                    webViewClient = WebViewClient()
                    addJavascriptInterface(speechBridge, "AndroidSpeech")
                    loadUrl(url)
                    webView = this
                }
            },
            update = { view ->
                if (view.url.isNullOrBlank()) {
                    view.loadUrl(url)
                }
            },
        )
    }
}

@Composable
private fun ConnectionModeCard(state: HostUiState, model: HostViewModel) {
    HostCard("连接方式") {
        Text("启动前选择一种方式；关闭房间后可以随时切换。")
        Button(
            onClick = { model.selectConnectionMode(ConnectionMode.HOTSPOT) },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (state.connectionMode == ConnectionMode.HOTSPOT) MahjongGreen else Color.White,
                contentColor = if (state.connectionMode == ConnectionMode.HOTSPOT) Color.White else MahjongGreen,
            ),
        ) {
            Column(Modifier.fillMaxWidth()) {
                Text("手机专用热点", fontWeight = FontWeight.Bold)
                Text("不需要路由器；玩家连接本机热点后扫码加入")
            }
        }
        Button(
            onClick = { model.selectConnectionMode(ConnectionMode.LAN) },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (state.connectionMode == ConnectionMode.LAN) MahjongGreen else Color.White,
                contentColor = if (state.connectionMode == ConnectionMode.LAN) Color.White else MahjongGreen,
            ),
        ) {
            Column(Modifier.fillMaxWidth()) {
                Text("外部局域网路由器", fontWeight = FontWeight.Bold)
                Text("房主和玩家连接同一个 Wi‑Fi，延迟通常最低")
            }
        }
        if (state.connectionMode == ConnectionMode.HOTSPOT) {
            Text("专用热点支持 Android 8.0 及以上；它不共享房主的互联网流量。")
        }
    }
}

@Composable
private fun ConnectionCard(state: HostUiState, onOpenOwnerBattle: (Int) -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    HostCard("玩家加入") {
        Text("当前方式：${connectionModeName(state.connectionMode)}", fontWeight = FontWeight.Bold)
        Button(
            onClick = { onOpenOwnerBattle(state.port) },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = MahjongGold),
        ) {
            Text("房主在 App 内参战")
        }
        Text("房主会作为普通玩家登录、注册、入座和对局；管理权限仍只在本应用中。")
        if (state.connectionMode == ConnectionMode.HOTSPOT) {
            val ssid = state.hotspotSsid
            val password = state.hotspotPassword
            Text("先让玩家连接下面的麻将专用 Wi‑Fi，再扫描房间二维码。")
            Text("Wi‑Fi：${ssid ?: "正在读取…"}")
            Text("密码：${password ?: "正在读取…"}")
            if (!ssid.isNullOrBlank() && !password.isNullOrBlank()) {
                val wifiQr = remember(ssid, password) { wifiQrPayload(ssid, password) }
                Row(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Image(
                        bitmap = remember(wifiQr) { qrBitmap(wifiQr).asImageBitmap() },
                        contentDescription = "专用 Wi‑Fi 二维码",
                        modifier = Modifier.size(140.dp),
                    )
                    OutlinedButton(onClick = {
                        val clipboard =
                            context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipboard.setPrimaryClip(ClipData.newPlainText("麻将专用热点密码", password))
                    }) { Text("复制密码") }
                }
            }
        }
        if (state.addresses.isEmpty()) {
            Text(
                if (state.connectionMode == ConnectionMode.HOTSPOT) {
                    "热点地址尚未就绪，请稍候。"
                } else {
                    "未检测到局域网 IPv4，请确认房主手机已连接 Wi‑Fi。"
                },
            )
        } else {
            state.addresses.forEachIndexed { index, url ->
                Text(url, fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Image(
                        bitmap = remember(url) { qrBitmap(url).asImageBitmap() },
                        contentDescription = "房间地址二维码",
                        modifier = Modifier.size(if (index == 0) 160.dp else 96.dp),
                    )
                    OutlinedButton(onClick = {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clipboard.setPrimaryClip(ClipData.newPlainText("温岭麻将房间", url))
                    }) { Text("复制链接") }
                }
            }
        }
    }
}

@Composable
private fun RoomCard(state: HostUiState, model: HostViewModel) {
    val mutable = !state.gameStarted || state.phase == "round_over"
    val humanAccounts = state.accounts.filter { !it.isAi && it.enabled }
    HostCard("房间座位") {
        Text(if (mutable) "玩家可自由入座；房主也可在此强制调整。" else "小局进行中，座位已锁定。")
        state.seats.forEach { seat ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    listOf("下位", "右位", "上位", "左位").getOrElse(seat.seat) { "${seat.seat}" },
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(0.7f),
                )
                Text(
                    seat.account ?: "空位（${seat.effectiveAccount ?: "AI"}）",
                    modifier = Modifier.weight(1.4f),
                )
                AccountPicker(
                    accounts = humanAccounts,
                    enabled = mutable,
                    onSelect = { account ->
                        model.roomCommand(
                            "set_seat",
                            JSONObject().put("account", account).put("seat", seat.seat),
                        )
                    },
                )
                OutlinedButton(
                    enabled = mutable && seat.account != null,
                    onClick = {
                        model.roomCommand("kick", JSONObject().put("seat", seat.seat))
                    },
                ) { Text("踢出") }
            }
        }
        OutlinedButton(
            enabled = mutable,
            onClick = { model.roomCommand("reset_room", JSONObject()) },
        ) { Text("重新换座") }
    }
}

@Composable
private fun AccountPicker(
    accounts: List<AccountInfo>,
    enabled: Boolean,
    onSelect: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(enabled = enabled, onClick = { expanded = true }) { Text("安排") }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            accounts.forEach { account ->
                DropdownMenuItem(
                    text = { Text(account.name) },
                    onClick = {
                        expanded = false
                        onSelect(account.name)
                    },
                )
            }
        }
    }
}

@Composable
private fun OfflineAccountsCard(state: HostUiState, model: HostViewModel) {
    var newAccount by remember { mutableStateOf("") }
    var mergeSources by remember { mutableStateOf("") }
    var mergeTarget by remember { mutableStateOf("") }
    var pending by remember { mutableStateOf<Pair<String, JSONObject>?>(null) }

    HostCard("账号与统计后台") {
        Text("仅在房间关闭时可操作。删除、清零和合并前会自动备份数据库。")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = newAccount,
                onValueChange = { newAccount = it },
                label = { Text("新账号") },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            Button(
                onClick = {
                    model.accountCommand("create", JSONObject().put("account", newAccount.trim()))
                    newAccount = ""
                },
                enabled = newAccount.isNotBlank(),
            ) { Text("创建") }
        }

        state.accounts.filter { !it.isAi }.forEach { account ->
            Card(colors = CardDefaults.cardColors(containerColor = Color.White.copy(alpha = 0.75f))) {
                Column(Modifier.fillMaxWidth().padding(12.dp)) {
                    Text(account.name, fontWeight = FontWeight.Bold)
                    Text(
                        "${if (account.enabled) "启用" else "已停用"} · ${account.rounds} 局 · ${account.wins} 胜 · " +
                            "历史平均运气度 ${account.historicalLuckScore?.let { "%.1f".format(it) } ?: "-"}",
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedButton(onClick = {
                            model.accountCommand(
                                if (account.enabled) "disable" else "enable",
                                JSONObject().put("account", account.name),
                            )
                        }) { Text(if (account.enabled) "停用" else "恢复") }
                        OutlinedButton(onClick = {
                            pending = "clear_stats" to JSONObject().put("account", account.name)
                        }) { Text("清零统计") }
                        OutlinedButton(onClick = {
                            pending = "delete" to JSONObject().put("account", account.name)
                        }) { Text("彻底删除", color = Danger) }
                    }
                }
            }
        }

        Text("合并账号统计", fontWeight = FontWeight.Bold)
        OutlinedTextField(
            value = mergeSources,
            onValueChange = { mergeSources = it },
            label = { Text("来源账号，用逗号分隔") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = mergeTarget,
            onValueChange = { mergeTarget = it },
            label = { Text("目标账号") },
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            enabled = mergeSources.isNotBlank() && mergeTarget.isNotBlank(),
            onClick = {
                val sources = mergeSources.split(',', '，').map { it.trim() }.filter { it.isNotBlank() }
                pending = "merge" to JSONObject()
                    .put("sources", JSONArray(sources))
                    .put("target", mergeTarget.trim())
            },
            colors = ButtonDefaults.buttonColors(containerColor = MahjongGold),
        ) { Text("合并并删除来源账号") }
    }

    pending?.let { (command, payload) ->
        AlertDialog(
            onDismissRequest = { pending = null },
            title = { Text("确认不可逆操作") },
            text = { Text("执行前会自动备份数据库。确认继续？") },
            confirmButton = {
                TextButton(onClick = {
                    pending = null
                    model.accountCommand(command, payload)
                    if (command == "merge") {
                        mergeSources = ""
                        mergeTarget = ""
                    }
                }) { Text("确认", color = Danger) }
            },
            dismissButton = { TextButton(onClick = { pending = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun HostCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color.White),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = MahjongGreen)
            content()
        }
    }
}

private fun qrBitmap(value: String): Bitmap {
    val matrix = QRCodeWriter().encode(value, BarcodeFormat.QR_CODE, 512, 512)
    val bitmap = Bitmap.createBitmap(matrix.width, matrix.height, Bitmap.Config.RGB_565)
    for (x in 0 until matrix.width) {
        for (y in 0 until matrix.height) {
            bitmap.setPixel(x, y, if (matrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
        }
    }
    return bitmap
}

private fun connectionModeName(mode: ConnectionMode): String =
    if (mode == ConnectionMode.HOTSPOT) "手机专用热点" else "外部局域网路由器"

private fun wifiQrPayload(ssid: String, password: String): String {
    fun escape(value: String) =
        value.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace(":", "\\:")
    return "WIFI:T:WPA;S:${escape(ssid)};P:${escape(password)};;"
}
