package com.android.mcp.agent

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Manages the WebSocket connection from the Android Agent SDK to the MCP Server.
 *
 * The connection URL should point to `ws://127.0.0.1:<port>` where `<port>` matches
 * the `adb reverse tcp:<port> tcp:<port>` configuration (default: 8080).
 *
 * ### Features
 * - Automatic reconnection with exponential back-off (capped at [MAX_BACKOFF_MS]).
 * - All outbound messages are routed through [MessageMasker] before transmission
 *   to satisfy the spec §5.2 masking constraints.
 * - Exposes [send] for [NetworkInterceptor] and [ViewModelObserver] to enqueue
 *   JSON-RPC 2.0 telemetry events.
 */
class SdkBridgeClient(private val url: String) {

    private val tag = "SdkBridgeClient"

    private val httpClient = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)  // infinite read timeout for WebSocket
        .build()

    private val socketRef = AtomicReference<WebSocket?>(null)
    private val reconnectScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** True when the WebSocket handshake has completed successfully. */
    @Volatile
    var isConnected: Boolean = false
        private set

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    /**
     * Open the WebSocket connection and keep it alive.
     * Retries automatically on failure.  Call this once from [AgentService].
     */
    suspend fun connect() {
        var backoffMs = INITIAL_BACKOFF_MS
        while (reconnectScope.isActive) {
            Log.d(tag, "Connecting to $url …")
            openWebSocket()
            delay(backoffMs)
            backoffMs = minOf(backoffMs * 2, MAX_BACKOFF_MS)
        }
    }

    /**
     * Send a pre-built JSON-RPC 2.0 event to the MCP Server.
     * The [payload] is passed through [MessageMasker] before transmission.
     * Returns `false` if the socket is not connected.
     */
    fun send(payload: JSONObject): Boolean {
        val ws = socketRef.get() ?: return false
        val masked = MessageMasker.mask(payload.toString())
        return ws.send(masked)
    }

    /** Close the WebSocket and cancel the reconnect loop. */
    fun disconnect() {
        reconnectScope.cancel()
        socketRef.getAndSet(null)?.close(1000, "AgentService stopped")
        isConnected = false
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    private fun openWebSocket() {
        val request = Request.Builder().url(url).build()
        httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                socketRef.set(webSocket)
                isConnected = true
                Log.i(tag, "WebSocket connected to $url")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(tag, "Received: $text")
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                Log.d(tag, "Received bytes: ${bytes.size}")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                socketRef.compareAndSet(webSocket, null)
                isConnected = false
                Log.w(tag, "WebSocket failure: ${t.message}")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                socketRef.compareAndSet(webSocket, null)
                isConnected = false
                Log.i(tag, "WebSocket closed ($code): $reason")
            }
        })
    }

    companion object {
        private const val INITIAL_BACKOFF_MS = 1_000L
        private const val MAX_BACKOFF_MS = 30_000L
    }
}
