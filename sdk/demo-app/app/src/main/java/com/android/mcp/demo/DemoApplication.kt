package com.android.mcp.demo

import android.app.Application
import com.android.mcp.agent.AgentService
import com.android.mcp.agent.SdkBridgeClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class DemoApplication : Application() {

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    val bridgeClient: SdkBridgeClient by lazy { SdkBridgeClient(WS_URL) }

    override fun onCreate() {
        super.onCreate()
        AgentService.start(this)
        appScope.launch { bridgeClient.connect() }
    }

    override fun onTerminate() {
        bridgeClient.disconnect()
        appScope.cancel()
        AgentService.stop(this)
        super.onTerminate()
    }

    companion object {
        private const val WS_URL = "ws://127.0.0.1:8080"
    }
}
