package cn.wenling.mahjong.host

import android.content.Context
import android.os.Build
import com.chaquo.python.Python
import org.json.JSONObject

object PythonBridge {
    private fun module() = Python.getInstance().getModule("wenling_lan_host.android_bridge")

    fun configure(context: Context, port: Int = 8765): JSONObject {
        val dataDir = context.filesDir.resolve("runtime").absolutePath
        val staticDir = context.filesDir.resolve("static-v1").absolutePath
        val exportDir = context.getExternalFilesDir("bug_reports")?.absolutePath ?: ""
        val runtimeContext = JSONObject()
            .put("host_platform", "android")
            .put("package_name", context.packageName)
            .put("sdk_int", Build.VERSION.SDK_INT)
            .put("manufacturer", Build.MANUFACTURER ?: "")
            .put("brand", Build.BRAND ?: "")
            .put("model", Build.MODEL ?: "")
            .put("device", Build.DEVICE ?: "")
            .put("product", Build.PRODUCT ?: "")
            .put("data_dir", dataDir)
            .put("static_dir", staticDir)
            .put("bug_report_export_dir", exportDir)
        return parse(
            module().callAttr(
                "configure",
                dataDir,
                staticDir,
                port,
                exportDir,
                runtimeContext.toString(),
            ).toString(),
        )
    }

    fun start(): JSONObject = parse(module().callAttr("start").toString())
    fun stop(): JSONObject = parse(module().callAttr("stop").toString())
    fun status(): JSONObject = parse(module().callAttr("status").toString())
    fun accounts(): JSONObject = parse(module().callAttr("accounts").toString())

    fun roomCommand(command: String, payload: JSONObject): JSONObject =
        parse(module().callAttr("room_command", command, payload.toString()).toString())

    fun accountCommand(command: String, payload: JSONObject): JSONObject =
        parse(module().callAttr("account_command", command, payload.toString()).toString())

    private fun parse(value: String): JSONObject {
        val result = JSONObject(value)
        if (!result.optBoolean("ok", false)) {
            throw IllegalStateException(result.optString("error", "未知错误"))
        }
        return result
    }
}
