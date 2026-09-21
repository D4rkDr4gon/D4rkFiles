# ====== FUNCIONES ======

hex-encode() { echo "$@" | xxd -p; }
hex-decode() { echo "$@" | xxd -p -r; }
rot13()      { echo "$@" | tr 'A-Za-z' 'N-ZA-Mn-za-m'; }

# ====== OLLAMA (IA local; solo si está instalado) ======
if command -v ollama >/dev/null; then
  ollama-up() {
    if pgrep -f "ollama serve" >/dev/null; then
      echo "Ollama ya está corriendo"
    else
      echo "Levantando Ollama..."
      ollama serve &>/dev/null &
      disown
      sleep 2
      echo "Ollama iniciado"
    fi
  }

  ollama-down() {
    if pgrep -f "ollama serve" >/dev/null; then
      pkill -f "ollama serve" && echo "Ollama detenido"
    else
      echo "Ollama no está corriendo"
    fi
  }

  # ollama-test [modelo] [prompt] — corre un prompt corto y mide el tiempo
  ollama-test() {
    local model="${1:-qwen3:1.7b}"
    local prompt="${2:-Decime hola en 5 palabras}"
    echo "Test: $model"
    echo "Prompt: \"$prompt\""
    echo "---"
    time curl -s -X POST http://localhost:11434/api/generate \
      -H 'Content-Type: application/json' \
      -d "{\"model\": \"$model\", \"prompt\": \"$prompt\", \"stream\": false, \"options\": {\"temperature\": 0.3, \"num_predict\": 100}}" \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('response',''))" 2>/dev/null
  }
fi
