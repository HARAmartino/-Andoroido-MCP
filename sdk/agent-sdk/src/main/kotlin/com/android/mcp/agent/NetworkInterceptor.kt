package com.android.mcp.agent

import android.util.Log
import okhttp3.Interceptor
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException

/**
 * OkHttp [Interceptor] that records every HTTP request/response pair and forwards
 * it to the MCP Server as a `telemetry/network` JSON-RPC 2.0 event.
 *
 * ### Masking
 * Sensitive fields (Authorization header, `password`, `token`, `credit_card` in the
 * body) are redacted by [MessageMasker] before the payload is sent over the WebSocket.
 * This ensures that raw credentials never leave the device in plain text.
 *
 * ### Integration
 * Add this interceptor to the host app's [OkHttpClient]:
 * ```kotlin
 * val client = OkHttpClient.Builder()
 *     .addInterceptor(NetworkInterceptor(bridgeClient))
 *     .build()
 * ```
 */
class NetworkInterceptor(private val bridge: SdkBridgeClient) : Interceptor {

    private val tag = "NetworkInterceptor"

    @Throws(IOException::class)
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val startMs = System.currentTimeMillis()

        // Buffer the request body BEFORE proceeding – OkHttp bodies are one-shot
        // and would be empty after chain.proceed() consumes them.
        val reqBodyString = try {
            val buffer = okio.Buffer()
            request.body?.writeTo(buffer)
            buffer.readUtf8()
        } catch (_: Exception) {
            ""
        }

        // Rebuild the request so the original body is still sent downstream.
        val forwardRequest = if (request.body != null && reqBodyString.isNotEmpty()) {
            request.newBuilder()
                .method(request.method, okhttp3.RequestBody.create(request.body!!.contentType(), reqBodyString))
                .build()
        } else {
            request
        }

        val response = chain.proceed(forwardRequest)

        val latencyMs = System.currentTimeMillis() - startMs

        try {
            // Snapshot the response body without consuming it (peek).
            val responseBodyString = response.peekBody(MAX_BODY_BYTES).string()

            val event = buildEvent(request, reqBodyString, response, responseBodyString, latencyMs)
            if (!bridge.send(event)) {
                Log.d(tag, "Bridge not connected – network trace dropped")
            }
        } catch (e: Exception) {
            Log.w(tag, "Failed to record network trace: ${e.message}")
        }

        return response
    }

    // ------------------------------------------------------------------
    // Event building
    // ------------------------------------------------------------------

    private fun buildEvent(
        request: okhttp3.Request,
        requestBody: String,
        response: Response,
        responseBody: String,
        latencyMs: Long,
    ): JSONObject {
        val reqHeaders = JSONObject()
        for (name in request.headers.names()) {
            reqHeaders.put(name, request.headers[name] ?: "")
        }

        val reqObj = JSONObject().apply {
            put("method", request.method)
            put("url", request.url.toString())
            put("headers", reqHeaders)
            put("body", tryParseJson(requestBody))
        }

        val resObj = JSONObject().apply {
            put("status", response.code)
            put("body", tryParseJson(responseBody))
        }

        return JSONObject().apply {
            put("jsonrpc", "2.0")
            put("method", "telemetry/network")
            put("params", JSONObject().apply {
                put("timestamp", System.currentTimeMillis())
                put("request", reqObj)
                put("response", resObj)
                put("latency_ms", latencyMs)
            })
        }
    }

    /**
     * Attempt to parse [text] as a JSON object or array; fall back to the raw string.
     * Handles both `{}` (object) and `[]` (array) root values.
     */
    private fun tryParseJson(text: String): Any {
        if (text.isBlank()) return text
        val trimmed = text.trimStart()
        return when {
            trimmed.startsWith('{') -> try { JSONObject(text) } catch (_: Exception) { text }
            trimmed.startsWith('[') -> try { org.json.JSONArray(text) } catch (_: Exception) { text }
            else -> text
        }
    }

    companion object {
        /** Maximum response body bytes to snapshot (avoids OOM on large downloads). */
        private const val MAX_BODY_BYTES = 64 * 1024L  // 64 KiB
    }
}
