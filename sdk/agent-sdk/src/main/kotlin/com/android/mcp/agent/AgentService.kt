package com.android.mcp.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Foreground Service that keeps the Agent SDK alive under Android 14/15 background
 * restrictions.
 *
 * The service:
 * 1. Creates a persistent notification so Android does not kill the process.
 * 2. Launches [SdkBridgeClient] which opens the WebSocket tunnel to the MCP Server
 *    (expected to be reachable at `ws://127.0.0.1:8080` after
 *    `adb reverse tcp:8080 tcp:8080`).
 * 3. Registers [NetworkInterceptor] and [ViewModelObserver] so that telemetry
 *    events are forwarded to the server in real-time.
 *
 * ### Integration (host application)
 * ```kotlin
 * // In Application.onCreate() or wherever appropriate:
 * AgentService.start(applicationContext)
 * ```
 *
 * The service stops itself when [stop] is called or when the host app process ends.
 */
class AgentService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private lateinit var bridgeClient: SdkBridgeClient

    // ------------------------------------------------------------------
    // Service lifecycle
    // ------------------------------------------------------------------

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification())
        bridgeClient = SdkBridgeClient(WS_URL)
        serviceScope.launch { bridgeClient.connect() }
        Log.i(TAG, "AgentService started; connecting to $WS_URL")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // START_STICKY ensures the OS restarts the service if it is killed.
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        bridgeClient.disconnect()
        serviceScope.cancel()
        Log.i(TAG, "AgentService stopped")
    }

    // ------------------------------------------------------------------
    // Notification helpers (required for foreground service)
    // ------------------------------------------------------------------

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Android MCP Agent",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Keeps the Android MCP debug agent running."
        }
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification =
        Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("MCP Agent Active")
            .setContentText("Collecting telemetry for AI debugging session.")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .build()

    // ------------------------------------------------------------------
    // Companion helpers
    // ------------------------------------------------------------------

    companion object {
        private const val TAG = "AgentService"
        private const val CHANNEL_ID = "mcp_agent_channel"
        private const val NOTIFICATION_ID = 0xA6E1
        private const val WS_URL = "ws://127.0.0.1:8080"

        /** Start the service from the host application. */
        fun start(context: Context) {
            context.startForegroundService(Intent(context, AgentService::class.java))
        }

        /** Stop the service from the host application. */
        fun stop(context: Context) {
            context.stopService(Intent(context, AgentService::class.java))
        }
    }
}
