package cn.wenling.mahjong.host

import java.net.Inet4Address
import java.net.NetworkInterface

object LocalNetworkAddresses {
    fun roomUrls(port: Int, mode: ConnectionMode): List<String> {
        val candidates = NetworkInterface.getNetworkInterfaces()
            ?.asSequence()
            ?.filter { runCatching { it.isUp && !it.isLoopback }.getOrDefault(false) }
            ?.flatMap { network ->
                network.inetAddresses.asSequence()
                    .filterIsInstance<Inet4Address>()
                    .filter { it.isSiteLocalAddress && !it.isLoopbackAddress }
                    .map { address -> Candidate(network.name.orEmpty(), address.hostAddress.orEmpty()) }
            }
            ?.filter { it.address.isNotBlank() }
            ?.toList()
            .orEmpty()

        val filtered = candidates.filter { candidate ->
            val name = candidate.interfaceName.lowercase()
            !EXCLUDED_INTERFACE_PREFIXES.any(name::startsWith) &&
                (mode != ConnectionMode.HOTSPOT || HOTSPOT_INTERFACE_HINTS.any(name::contains))
        }.ifEmpty {
            if (mode == ConnectionMode.HOTSPOT) {
                candidates.filterNot { candidate ->
                    EXCLUDED_INTERFACE_PREFIXES.any(candidate.interfaceName.lowercase()::startsWith)
                }
            } else {
                candidates
            }
        }

        return filtered
            .sortedWith(compareBy<Candidate> { priority(it.interfaceName, mode) }.thenBy { it.address })
            .map { "http://${it.address}:$port/battle-login" }
            .distinct()
    }

    private fun priority(interfaceName: String, mode: ConnectionMode): Int {
        val name = interfaceName.lowercase()
        return when {
            mode == ConnectionMode.HOTSPOT && HOTSPOT_INTERFACE_HINTS.any(name::contains) -> 0
            name.startsWith("wlan") || name.startsWith("wifi") -> 1
            name.startsWith("eth") || name.startsWith("en") -> 2
            name.startsWith("usb") || name.startsWith("rndis") -> 3
            else -> 4
        }
    }

    private data class Candidate(val interfaceName: String, val address: String)

    private val HOTSPOT_INTERFACE_HINTS = listOf("wlan", "wifi", "ap", "softap", "swlan")
    private val EXCLUDED_INTERFACE_PREFIXES =
        listOf("rmnet", "ccmni", "pdp", "tun", "tap", "dummy", "v4-", "clat", "lo")
}
