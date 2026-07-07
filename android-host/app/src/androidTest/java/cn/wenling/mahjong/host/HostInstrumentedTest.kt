package cn.wenling.mahjong.host

import android.content.Context
import androidx.core.content.ContextCompat
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class HostInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()

    @After
    fun stopHost() {
        context.startService(HostService.stopIntent(context))
        waitUntil(10_000) { !runCatching { PythonBridge.status().optBoolean("running") }.getOrDefault(false) }
    }

    @Test
    fun foregroundServiceStartsEmbeddedRoomAndStopsCleanly() {
        ContextCompat.startForegroundService(context, HostService.startIntent(context, ConnectionMode.LAN))
        assertTrue(waitUntil(20_000) { PythonBridge.status().optBoolean("running") })
        context.startService(HostService.stopIntent(context))
        assertTrue(waitUntil(10_000) { !PythonBridge.status().optBoolean("running") })
    }

    @Test
    fun accountAdministrationIsBlockedWhileRoomRuns() {
        PythonBridge.configure(context)
        val account = "instrumented-${System.currentTimeMillis()}"
        PythonBridge.accountCommand("create", JSONObject().put("account", account))
        ContextCompat.startForegroundService(context, HostService.startIntent(context, ConnectionMode.LAN))
        assertTrue(waitUntil(20_000) { PythonBridge.status().optBoolean("running") })
        val blocked = runCatching {
            PythonBridge.accountCommand("delete", JSONObject().put("account", account))
        }.exceptionOrNull()
        assertTrue(blocked?.message?.contains("房间运行中") == true)
    }

    @Test
    fun connectionModeSelectionPersists() {
        HostNetworkStateStore.selectMode(context, ConnectionMode.HOTSPOT)
        assertEquals(ConnectionMode.HOTSPOT, HostNetworkStateStore.selectedMode(context))
        HostNetworkStateStore.selectMode(context, ConnectionMode.LAN)
        assertEquals(ConnectionMode.LAN, HostNetworkStateStore.selectedMode(context))
    }

    private fun waitUntil(timeoutMs: Long, condition: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (runCatching(condition).getOrDefault(false)) return true
            Thread.sleep(200)
        }
        return false
    }
}
