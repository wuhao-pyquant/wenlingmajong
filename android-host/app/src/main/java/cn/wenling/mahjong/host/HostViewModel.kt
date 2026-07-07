package cn.wenling.mahjong.host

import android.app.Application
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

data class SeatInfo(
    val seat: Int,
    val account: String?,
    val effectiveAccount: String?,
    val online: Boolean,
    val ready: Boolean,
)

data class AccountInfo(
    val name: String,
    val enabled: Boolean,
    val isAi: Boolean,
    val rounds: Int,
    val wins: Int,
    val historicalLuckScore: Double?,
)

data class HostUiState(
    val loading: Boolean = true,
    val running: Boolean = false,
    val starting: Boolean = false,
    val connectionMode: ConnectionMode = ConnectionMode.LAN,
    val networkPhase: String = "stopped",
    val hotspotSsid: String? = null,
    val hotspotPassword: String? = null,
    val port: Int = 8765,
    val generation: Int = 1,
    val phase: String? = null,
    val gameStarted: Boolean = false,
    val seats: List<SeatInfo> = emptyList(),
    val accounts: List<AccountInfo> = emptyList(),
    val addresses: List<String> = emptyList(),
    val error: String? = null,
)

class HostViewModel(application: Application) : AndroidViewModel(application) {
    private val _state = MutableStateFlow(HostUiState())
    val state: StateFlow<HostUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { PythonBridge.configure(getApplication()) }
            refresh()
            while (isActive) {
                delay(if (_state.value.starting) 500 else 1500)
                refresh()
            }
        }
    }

    fun startRoom() {
        val mode = _state.value.connectionMode
        ContextCompat.startForegroundService(
            getApplication(),
            HostService.startIntent(getApplication(), mode),
        )
        _state.value = _state.value.copy(loading = true, starting = true, error = null)
    }

    fun stopRoom() {
        getApplication<Application>().startService(HostService.stopIntent(getApplication()))
        _state.value = _state.value.copy(loading = true, error = null)
    }

    fun selectConnectionMode(mode: ConnectionMode) {
        if (_state.value.running || _state.value.starting) return
        HostNetworkStateStore.selectMode(getApplication(), mode)
        _state.value = _state.value.copy(connectionMode = mode, error = null)
    }

    fun reportError(message: String) {
        _state.value = _state.value.copy(loading = false, starting = false, error = message)
    }

    fun accountCommand(command: String, payload: JSONObject) = execute {
        PythonBridge.accountCommand(command, payload)
    }

    fun roomCommand(command: String, payload: JSONObject) = execute {
        val current = _state.value
        payload.put("room_generation", current.generation)
        PythonBridge.roomCommand(command, payload)
    }

    private fun execute(block: () -> JSONObject) {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            runCatching { withContext(Dispatchers.IO) { block() } }
                .onFailure { _state.value = _state.value.copy(error = it.message) }
            refresh()
        }
    }

    private suspend fun refresh() {
        runCatching {
            withContext(Dispatchers.IO) {
                val status = PythonBridge.status()
                val running = status.optBoolean("running")
                val network = HostNetworkStateStore.snapshot(getApplication())
                val starting = !running && network.phase in setOf("starting", "hotspot_ready")
                val selectedMode = if (running || starting) {
                    network.mode
                } else {
                    HostNetworkStateStore.selectedMode(getApplication())
                }
                val accountPayload = if (running || starting) null else PythonBridge.accounts()
                val activeNames = status.optJSONArray("available_accounts").toStrings()
                val previousByName = _state.value.accounts.associateBy { it.name }
                val accounts = accountPayload?.optJSONArray("accounts")?.let(::parseAccounts)
                    ?: activeNames.map { previousByName[it] ?: AccountInfo(it, true, false, 0, 0, null) }
                HostUiState(
                    loading = false,
                    running = running,
                    starting = starting,
                    connectionMode = selectedMode,
                    networkPhase = network.phase,
                    hotspotSsid = network.hotspotSsid,
                    hotspotPassword = network.hotspotPassword,
                    port = status.optInt("port", 8765),
                    generation = status.optInt("room_generation", 1),
                    phase = status.optString("phase").ifBlank { null },
                    gameStarted = status.optBoolean("game_started"),
                    seats = parseSeats(status.optJSONArray("seats")),
                    accounts = accounts,
                    addresses = if (running) {
                        LocalNetworkAddresses.roomUrls(
                            status.optInt("port", 8765),
                            selectedMode,
                        )
                    } else {
                        emptyList()
                    },
                    error = network.error,
                )
            }
        }.onSuccess {
            _state.value = it
        }.onFailure {
            _state.value = _state.value.copy(loading = false, error = it.message)
        }
    }

    private fun parseSeats(array: JSONArray?): List<SeatInfo> =
        (0 until (array?.length() ?: 0)).map { index ->
            val row = array!!.getJSONObject(index)
            SeatInfo(
                seat = row.optInt("absolute_seat", row.optInt("seat", index)),
                account = row.optString("account").ifBlank { null },
                effectiveAccount = row.optString("effective_account").ifBlank { null },
                online = row.optBoolean("online"),
                ready = row.optBoolean("ready"),
            )
        }.sortedBy { it.seat }

    private fun parseAccounts(array: JSONArray): List<AccountInfo> =
        (0 until array.length()).map { index ->
            val row = array.getJSONObject(index)
            val all = row.optJSONObject("stats")?.optJSONObject("all")
            AccountInfo(
                name = row.getString("account"),
                enabled = row.optBoolean("enabled", true),
                isAi = row.optBoolean("is_ai"),
                rounds = all?.optInt("rounds") ?: 0,
                wins = all?.optInt("wins") ?: 0,
                historicalLuckScore = all?.optDouble("luck_score", Double.NaN)?.takeIf { it.isFinite() },
            )
        }

    private fun JSONArray?.toStrings(): List<String> =
        (0 until (this?.length() ?: 0)).map { this!!.getString(it) }
}
