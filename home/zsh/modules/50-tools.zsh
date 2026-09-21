# ====== FUNCIONES ======

# extractPorts <archivo.gnmap>: IP y puertos abiertos de un escaneo de nmap; copia los
# puertos al portapapeles (wl-copy en Wayland, xclip en X11).
extractPorts() {
  local ports ip
  ports="$(grep -oP '\d{1,5}/open' "$1" | awk '{print $1}' FS='/' | xargs | tr ' ' ',')"
  ip="$(grep -oP '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}' "$1" | sort -u | head -n 1)"
  printf '\n[*] Extracting information...\n\n\t[*] IP Address: %s\n\t[*] Open ports: %s\n\n' "$ip" "$ports"
  if [[ -n "$WAYLAND_DISPLAY" ]] && command -v wl-copy >/dev/null; then
    printf '%s' "$ports" | wl-copy
  elif command -v xclip >/dev/null; then
    printf '%s' "$ports" | xclip -sel clip
  else
    return 0
  fi
  echo "[*] Ports copied to clipboard"
}

# autopsy-fix: lanza Autopsy con JDK 21 (su launcher se rompe con otros JDK), desligado de la shell.
autopsy-fix() {
  local jdk=/usr/lib/jvm/java-21-openjdk
  [[ -d "$jdk" ]] || { echo "Falta $jdk (paquete jdk21-openjdk)"; return 1; }
  command -v autopsy >/dev/null || { echo "autopsy no está instalado"; return 1; }
  unset CLASSPATH JAVACMD
  JAVA_HOME="$jdk" PATH="$jdk/bin:$PATH" nohup autopsy --jdkhome "$jdk" >/dev/null 2>&1 &
  disown
}

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
