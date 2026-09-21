{
  "$schema": "https://opencode.ai/config.json",
@opencode_theme_line@
  "agent": {
    "build": { "color": "@primary@" },
    "plan": { "color": "@secondary@" },
    "general": { "color": "@foreground@" },
    "explore": { "color": "@primary@" }
  },

  // Este archivo se genera desde opencode.jsonc.tpl (scripts/theme-switch.sh).
  // Para cambiar algo de forma permanente, editá el .tpl.

  // ── Modelo principal ─────────────────────────────────────
  // "model": "ollama/qwen2.5:7b",
  // "small_model": "ollama/qwen3:1.7b",

  // ── Ollama como provider (modelos locales) ──────────────
  // Requiere Ollama corriendo (`ollama serve`). Los modelos deben declararse
  // explícitamente en "models" (ejemplos; cambialos por los que uses).
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": {
        "baseURL": "http://localhost:11434/v1"
      },
      "models": {
        "qwen2.5:7b": {
          "name": "Qwen 2.5 7B (local)",
          "limit": { "context": 32768, "output": 8192 }
        },
        "qwen3:1.7b": {
          "name": "Qwen 3 1.7B (local)",
          "limit": { "context": 32768, "output": 4096 }
        }
      }
    }
  }

  // ── MCP servers ──────────────────────────────────────────
  // Agregá los tuyos en un bloque "mcp". Las credenciales van SIEMPRE por
  // variable de entorno ("{env:MI_API_KEY}"), nunca escritas acá.
}
