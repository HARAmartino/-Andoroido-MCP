package com.android.mcp.agent

import android.util.Log
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LiveData
import androidx.lifecycle.Observer
import androidx.lifecycle.ViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.lang.reflect.Field

/**
 * Observes [StateFlow] and [LiveData] fields on a [ViewModel] and forwards each state
 * change to the MCP Server as a `telemetry/state` JSON-RPC 2.0 event.
 *
 * ### Design
 * Reflection is used to discover observable fields without requiring the host app to
 * annotate anything.  Only `StateFlow` and `LiveData` fields are observed; plain fields
 * are snapshotted once when [attach] is called.
 *
 * ### Usage
 * ```kotlin
 * val observer = ViewModelObserver(bridgeClient)
 *
 * // Observe a ViewModel with StateFlows / LiveData fields:
 * observer.attach(lifecycleOwner, loginViewModel)
 *
 * // Detach when no longer needed:
 * observer.detach(loginViewModel)
 * ```
 */
class ViewModelObserver(private val bridge: SdkBridgeClient) {

    private val tag = "ViewModelObserver"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Active observation jobs keyed by ViewModel class name. */
    private val attached = mutableMapOf<String, () -> Unit>()

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    /**
     * Start observing all [StateFlow] and [LiveData] fields on [viewModel].
     * Each emission triggers a `telemetry/state` event to the MCP Server.
     *
     * @param owner  Lifecycle owner used to scope [LiveData] observation.
     * @param viewModel  Target ViewModel instance.
     */
    fun attach(owner: LifecycleOwner, viewModel: ViewModel) {
        val vmName = viewModel::class.simpleName ?: "UnknownViewModel"
        if (attached.containsKey(vmName)) return

        val cleanupActions = mutableListOf<() -> Unit>()

        for (field in collectFields(viewModel::class.java)) {
            field.isAccessible = true
            when (val value = field.get(viewModel)) {
                is StateFlow<*> -> {
                    val job = scope.launch {
                        value.collect { state ->
                            sendState(vmName, field.name, state)
                        }
                    }
                    cleanupActions.add { job.cancel() }
                }
                is LiveData<*> -> {
                    val observer = Observer<Any?> { state ->
                        sendState(vmName, field.name, state)
                    }
                    value.observe(owner, observer)
                    cleanupActions.add { value.removeObserver(observer) }
                }
                else -> {
                    // Snapshot non-observable fields once.
                    sendState(vmName, field.name, value)
                }
            }
        }

        attached[vmName] = { cleanupActions.forEach { it() } }
        Log.i(tag, "Attached observer to $vmName (${cleanupActions.size} fields)")
    }

    /**
     * Stop observing the given [viewModel] and clean up resources.
     */
    fun detach(viewModel: ViewModel) {
        val vmName = viewModel::class.simpleName ?: return
        attached.remove(vmName)?.invoke()
        Log.i(tag, "Detached observer from $vmName")
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    private fun sendState(vmName: String, fieldName: String, state: Any?) {
        val stateJson = JSONObject()
        when (state) {
            null -> stateJson.put(fieldName, JSONObject.NULL)
            is Boolean, is Int, is Long, is Double, is Float, is String ->
                stateJson.put(fieldName, state)
            else -> stateJson.put(fieldName, state.toString())
        }

        val event = JSONObject().apply {
            put("jsonrpc", "2.0")
            put("method", "telemetry/state")
            put("params", JSONObject().apply {
                put("viewmodel", vmName)
                put("state", stateJson)
            })
        }

        if (!bridge.send(event)) {
            Log.d(tag, "Bridge not connected – state event for $vmName dropped")
        }
    }

    private fun collectFields(clazz: Class<*>): List<Field> {
        val fields = mutableListOf<Field>()
        var current: Class<*>? = clazz
        while (current != null && current != ViewModel::class.java && current != Any::class.java) {
            fields.addAll(current.declaredFields)
            current = current.superclass
        }
        return fields
    }
}
