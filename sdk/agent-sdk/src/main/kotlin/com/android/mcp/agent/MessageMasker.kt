package com.android.mcp.agent

import java.util.regex.Pattern

/**
 * Client-side message masker applied to every outbound WebSocket message.
 *
 * This enforces the auto-masking rules specified in SPEC §5.2 *before* any
 * telemetry data leaves the Android device.  The MCP Server applies the same
 * rules again on receipt as a defence-in-depth measure.
 *
 * ### Masking rules
 * | Pattern | Replacement |
 * |---------|-------------|
 * | `Authorization: ****** | `Authorization: ***MASKED***` |
 * | `"password": "<value>"` | `"password": "***MASKED***"` |
 * | `"token": "<value>"` | `"token": "***MASKED***"` |
 * | `"credit_card": "<value>"` | `"credit_card": "***MASKED***"` |
 *
 * The input is treated as raw JSON text (a String) so that the masking is
 * applied before the message is parsed, preventing unmasked values from
 * appearing in logs or error messages.
 */
object MessageMasker {

    private const val MASK = "***MASKED***"

    private val RULES: List<Pair<Pattern, String>> = listOf(
        // Preserve "Authorization: Bearer " prefix; mask only the token value.
        Pattern.compile(
            """(Authorization:\s*Bearer\s+)\S+""",
            Pattern.CASE_INSENSITIVE,
        ) to "\$1$MASK",

        Pattern.compile(
            """"password"\s*:\s*"[^"]*"""",
        ) to """"password": "$MASK"""",

        Pattern.compile(
            """"token"\s*:\s*"[^"]*"""",
        ) to """"token": "$MASK"""",

        Pattern.compile(
            """"credit_card"\s*:\s*"[^"]*"""",
        ) to """"credit_card": "$MASK"""",
    )

    /**
     * Apply all masking rules to [message] and return the sanitised result.
     * The operation is purely string-based and does not parse JSON.
     */
    fun mask(message: String): String {
        var result = message
        for ((pattern, replacement) in RULES) {
            result = pattern.matcher(result).replaceAll(replacement)
        }
        return result
    }
}
