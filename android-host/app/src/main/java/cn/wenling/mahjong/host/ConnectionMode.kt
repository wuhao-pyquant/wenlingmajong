package cn.wenling.mahjong.host

import android.content.Context

enum class ConnectionMode(val value: String) {
    HOTSPOT("hotspot"),
    LAN("lan");

    companion object {
        fun fromValue(value: String?): ConnectionMode =
            entries.firstOrNull { it.value == value } ?: LAN
    }
}

data class HostNetworkState(
    val mode: ConnectionMode,
    val phase: String,
    val hotspotSsid: String?,
    val hotspotPassword: String?,
    val error: String?,
)

object HostNetworkStateStore {
    private const val PREFERENCES = "host_network"
    private const val KEY_SELECTED_MODE = "selected_mode"
    private const val KEY_RUNTIME_MODE = "runtime_mode"
    private const val KEY_PHASE = "phase"
    private const val KEY_HOTSPOT_SSID = "hotspot_ssid"
    private const val KEY_HOTSPOT_PASSWORD = "hotspot_password"
    private const val KEY_ERROR = "error"

    fun selectedMode(context: Context): ConnectionMode =
        ConnectionMode.fromValue(preferences(context).getString(KEY_SELECTED_MODE, ConnectionMode.LAN.value))

    fun selectMode(context: Context, mode: ConnectionMode) {
        preferences(context).edit().putString(KEY_SELECTED_MODE, mode.value).apply()
    }

    fun markStarting(context: Context, mode: ConnectionMode) {
        preferences(context).edit()
            .putString(KEY_RUNTIME_MODE, mode.value)
            .putString(KEY_PHASE, "starting")
            .remove(KEY_HOTSPOT_SSID)
            .remove(KEY_HOTSPOT_PASSWORD)
            .remove(KEY_ERROR)
            .apply()
    }

    fun markHotspotReady(context: Context, ssid: String?, password: String?) {
        preferences(context).edit()
            .putString(KEY_PHASE, "hotspot_ready")
            .putNullableString(KEY_HOTSPOT_SSID, ssid)
            .putNullableString(KEY_HOTSPOT_PASSWORD, password)
            .remove(KEY_ERROR)
            .apply()
    }

    fun markRunning(context: Context) {
        preferences(context).edit()
            .putString(KEY_PHASE, "running")
            .remove(KEY_ERROR)
            .apply()
    }

    fun markError(context: Context, message: String) {
        preferences(context).edit()
            .putString(KEY_PHASE, "error")
            .putString(KEY_ERROR, message)
            .apply()
    }

    fun markStopped(context: Context) {
        preferences(context).edit()
            .putString(KEY_PHASE, "stopped")
            .remove(KEY_HOTSPOT_SSID)
            .remove(KEY_HOTSPOT_PASSWORD)
            .remove(KEY_ERROR)
            .apply()
    }

    fun snapshot(context: Context): HostNetworkState {
        val values = preferences(context)
        return HostNetworkState(
            mode = ConnectionMode.fromValue(
                values.getString(KEY_RUNTIME_MODE, selectedMode(context).value),
            ),
            phase = values.getString(KEY_PHASE, "stopped") ?: "stopped",
            hotspotSsid = values.getString(KEY_HOTSPOT_SSID, null),
            hotspotPassword = values.getString(KEY_HOTSPOT_PASSWORD, null),
            error = values.getString(KEY_ERROR, null),
        )
    }

    private fun preferences(context: Context) =
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
}

private fun android.content.SharedPreferences.Editor.putNullableString(
    key: String,
    value: String?,
): android.content.SharedPreferences.Editor =
    if (value == null) remove(key) else putString(key, value)
