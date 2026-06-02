package com.android.mcp.demo

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import com.android.mcp.agent.NetworkInterceptor
import com.android.mcp.demo.databinding.ActivityMainBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val uiScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    private val httpClient: OkHttpClient by lazy {
        val app = application as DemoApplication
        OkHttpClient.Builder()
            .addInterceptor(NetworkInterceptor(app.bridgeClient))
            .build()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnCrash.setOnClickListener {
            val trigger: String? = null
            trigger!!.length
        }

        binding.btnNetwork.setOnClickListener {
            binding.statusText.text = getString(R.string.network_running)
            runMockNetworkCall()
        }
    }

    override fun onDestroy() {
        uiScope.cancel()
        super.onDestroy()
    }

    private fun runMockNetworkCall() {
        uiScope.launch(Dispatchers.IO) {
            val requestBody = """
                {
                  "email": "demo@example.com",
                  "password": "test-password",
                  "token": "plain-token"
                }
            """.trimIndent().toRequestBody("application/json".toMediaType())

            val request = Request.Builder()
                .url(MOCK_API_URL)
                .post(requestBody)
                .build()

            val message = runCatching {
                httpClient.newCall(request).execute().use { response ->
                    "HTTP ${response.code}"
                }
            }.getOrElse { error ->
                "Failed: ${error.message ?: "unknown error"}"
            }

            launch(Dispatchers.Main) {
                binding.statusText.text = message
            }
        }
    }

    companion object {
        private const val MOCK_API_URL = "https://httpbin.org/post"
    }
}
