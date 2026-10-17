#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# proton-backup.sh — backup incremental de carpetas en Proton Drive
# Lo usa la TUI tools/backup_tui.py (Settings → Backup).
# Los mensajes que muestra la TUI (msg=, log, notificaciones) van en inglés.
#
#   proton-backup.sh start [id...]   lanza la subida en segundo plano
#   proton-backup.sh run [id...]     la corre en primer plano
#   proton-backup.sh cancel          corta la subida en curso
#   proton-backup.sh running         exit 0 si hay una subida en curso
#
# Sin ids sube todas las carpetas de ~/.config/dotfiles/proton-backup.conf. Por
# carpeta compara contra el manifiesto de la última subida (ruta, tamaño,
# mtime), copia solo lo nuevo/modificado a un stage (así se respetan las
# exclusiones, que el CLI no soporta) y lo sube con `-d merge`; lo que
# se borró en local va a la papelera de Proton (30 días). El avance se
# lee de la barra que dibuja el CLI (por eso corre bajo `script`, con TTY).
# Requiere proton-drive (proton-drive-cli-bin), gawk y util-linux.
# ──────────────────────────────────────────────────────────
set -uo pipefail

# shellcheck source=lib/env.sh
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"
CONF="${PROTON_BACKUP_CONF:-$DOTFILES_CONF_DIR/proton-backup.conf}"
STATE_DIR="${PROTON_BACKUP_STATE:-$DOTFILES_STATE_DIR/proton-backup}"
STAGE_ROOT="$STATE_DIR/stage"
PIDFILE="$STATE_DIR/runner.pid"
LOG="$STATE_DIR/runner.log"
SELF="$(readlink -f "$0")"
PD=proton-drive
TRASH_BATCH=100

mkdir -p "$STATE_DIR"

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

# Formato de folders.conf: id|ícono|nombre|ruta local|ruta remota|exclusiones
entries() { [[ -r "$CONF" ]] && grep -vE '^\s*(#|$)' "$CONF"; }
field() { entries | awk -F'|' -v id="$1" -v f="$2" '$1 == id {print $f; exit}'; }
all_ids() { entries | cut -d'|' -f1; }

# Estado de una carpeta: $STATE_DIR/<id>.status, líneas clave=valor.
# El avance de la subida va aparte (<id>.progress, lo escribe el parser).
st_set() {
    local id="$1" f="$STATE_DIR/$1.status" tmp; shift
    # La primera vez el archivo no existe: awk saldría con error sin escribir nada
    [[ -f "$f" ]] || : > "$f"
    tmp="$(mktemp "$STATE_DIR/.st.XXXXXX")"
    awk -F= -v kv="$(printf '%s\n' "$@")" '
        BEGIN { n = split(kv, a, "\n"); for (i = 1; i <= n; i++) if (a[i] != "") {
                    k = a[i]; sub(/=.*/, "", k); v = a[i]; sub(/^[^=]*=/, "", v); new[k] = v } }
        { k = $1; if (k in new) next; print }
        END { for (k in new) print k "=" new[k] }' "$f" 2>/dev/null > "$tmp"
    mv "$tmp" "$f"
}
st_get() { awk -F= -v k="$2" '$1 == k { sub(/^[^=]*=/, ""); print; exit }' "$STATE_DIR/$1.status" 2>/dev/null; }

running() {
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null)" || return 1
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null \
        && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'proton-backup.sh run'
}

# Lista "ruta<TAB>tamaño<TAB>mtime" (o solo directorios con -d) de una
# carpeta, sin las exclusiones: un patrón con / se toma relativo a la
# raíz, si no se compara contra el nombre (ej. .git, node_modules).
scan() {
    local src="$1" excl="$2" kind="$3" pat prune=()
    for pat in $excl; do
        if [[ "$pat" == */* ]]; then prune+=(-path "$src/$pat" -o); else prune+=(-name "$pat" -o); fi
    done
    if [[ "$kind" == d ]]; then
        find "$src" -mindepth 1 \( "${prune[@]}" -false \) -prune -o -type d -printf '%P\n'
    else
        find "$src" -mindepth 1 \( "${prune[@]}" -false \) -prune -o -type f -printf '%P\t%s\t%T@\n'
    fi | LC_ALL=C sort
}

# Crea la ruta remota si no existe (equivalente a mkdir -p)
ensure_remote() {
    local path="$1" parent cur="" seg
    $PD fs info "$path" >/dev/null 2>&1 && return 0
    IFS=/ read -ra segs <<<"${path#/}"
    parent="/${segs[0]}"
    for seg in "${segs[@]:1}"; do
        cur="$parent/$seg"
        if ! $PD fs info "$cur" >/dev/null 2>&1; then
            $PD fs create-folder "$parent" "$seg" >/dev/null 2>&1 || return 1
        fi
        parent="$cur"
    done
}

# Manda a la papelera las rutas remotas de la entrada estándar, en tandas.
# `fs trash` corta en la primera ruta que no existe (y sale con 0), así
# que esa se descarta y se reintenta el resto de la tanda.
trash_paths() {
    local id="$1" batch=() p out missing n=0
    flush() {
        while ((${#batch[@]})); do
            out="$($PD fs trash "${batch[@]}" 2>&1)"
            missing="$(sed -n 's/^Node not found: //p' <<<"$out" | head -1)"
            [[ -z "$missing" ]] && break
            local keep=() b
            for b in "${batch[@]}"; do [[ "$b" == */"$missing" ]] || keep+=("$b"); done
            # No se pudo identificar cuál falló: no insistir
            ((${#keep[@]} == ${#batch[@]})) && { log "[$id] trash: $out"; break; }
            batch=("${keep[@]}")
        done
        batch=()
    }
    while IFS= read -r p; do
        batch+=("$p"); n=$((n + 1))
        ((${#batch[@]} >= TRASH_BATCH)) && flush
    done
    flush
    echo "$n"
}

# Parser de la salida del CLI (con TTY): cada cuadro empieza con
# "Uploaded N | ... | Queued M" y sigue con "NN.NN% nombre (tamaño)" por
# archivo en curso; un archivo que deja de aparecer ya terminó. Escribe
# el avance en $PROGRESS una vez por segundo y el resumen final en $RUNLOG.
PARSER='
BEGIN {
    RS = "\r\n|\r|\n"
    mult["B"] = 1; mult["KiB"] = 1024; mult["MiB"] = 1048576; mult["GiB"] = 1073741824; mult["TiB"] = 1099511627776
    t0 = systime(); last = 0
}
function write(final,   k, d, now, el, speed, eta, tmp) {
    d = 0
    for (k in seen) d += (k in fin) ? seen[k] : seen[k] * pct[k] / 100
    if (final) d = total
    if (d > total) d = total
    now = systime(); el = now - t0
    speed = (el > 0) ? int(d / el) : 0
    eta = (speed > 0) ? int((total - d) / speed) : -1
    tmp = PROGRESS ".tmp"
    printf "done=%d\ntotal=%d\npct=%d\nspeed=%d\neta=%d\nfiles_done=%d\nfiles_failed=%d\ncurrent=%s\n", \
        d, total, (total > 0 ? int(d * 100 / total) : 100), speed, eta, up, failed, cur_name > tmp
    close(tmp)
    system("mv -f \"" tmp "\" \"" PROGRESS "\"")
    last = now
}
{ gsub(/\033\[[0-9;?]*[A-Za-z]/, ""); line = $0 }
line ~ /^Transfer summary:/ { summary = 1 }
summary {
    print line >> RUNLOG
    if (line ~ /^  Failed: /) infail = 1
    else if (line ~ /^  [A-Z]/) infail = 0
    else if (infail && line ~ /^  - /) { n = line; sub(/^  - /, "", n); sub(/ \([^)]*\)$/, "", n); print n >> FAILED }
    next
}
match(line, /(Uploaded|Downloaded) ([0-9]+)/, m) && line ~ /Queued [0-9]+/ {
    for (k in seen) if (!(k in now_)) fin[k] = 1
    delete now_
    up = m[2]
    failed = match(line, /Failed ([0-9]+)/, f) ? f[1] : 0
}
match(line, /([0-9.]+)% (.*) \(([0-9.]+) (B|KiB|MiB|GiB|TiB)\)$/, m) {
    k = m[2] SUBSEP m[3] m[4]
    seen[k] = m[3] * mult[m[4]]; pct[k] = m[1]; now_[k] = 1; cur_name = m[2]
}
line !~ /%/ && line ~ /[Ee]rror|[Ff]ailed|login|not found/ { print line >> RUNLOG }
systime() != last { write(0) }
END { write(ok) }
'

backup_one() {
    local id="$1" name src remote excl stage new_files new_dirs changed deleted
    name="$(field "$id" 3)"; src="$(field "$id" 4)"; remote="$(field "$id" 5)"; excl="$(field "$id" 6)"
    local manifest="$STATE_DIR/$id.files" dirs="$STATE_DIR/$id.dirs"
    local runlog="$STATE_DIR/$id.last.log" progress="$STATE_DIR/$id.progress" failed="$STATE_DIR/$id.failed"
    : > "$runlog"; rm -f "$progress" "$failed"
    CUR_ID="$id"

    if [[ ! -d "$src" ]]; then
        st_set "$id" state=error "msg=Local folder not found: $src" finished="$(date +%s)"
        log "[$id] not found: $src"; return 1
    fi

    st_set "$id" state=scanning "msg=Looking for changes" started="$(date +%s)" finished=
    log "[$id] scanning $src"
    new_files="$(mktemp "$STATE_DIR/.files.XXXXXX")"; new_dirs="$(mktemp "$STATE_DIR/.dirs.XXXXXX")"
    changed="$(mktemp "$STATE_DIR/.changed.XXXXXX")"; deleted="$(mktemp "$STATE_DIR/.deleted.XXXXXX")"
    scan "$src" "$excl" f > "$new_files"
    scan "$src" "$excl" d > "$new_dirs"

    # Nuevos o modificados (por tamaño/mtime)
    if [[ -f "$manifest" ]]; then
        awk -F'\t' 'NR == FNR { old[$1] = $2 FS $3; next } old[$1] != $2 FS $3 { print $1 }' \
            "$manifest" "$new_files" > "$changed"
    else
        cut -f1 "$new_files" > "$changed"
    fi

    # Borrados: directorios que ya no están (solo el de más arriba) y
    # archivos sueltos que no quedan debajo de uno de ellos
    [[ -f "$manifest" ]] && awk -F'\t' -v R="$remote" '
        function under(p,   d) { d = p; while (sub(/\/[^\/]*$/, "", d)) if (d in gone) return 1; return 0 }
        FILENAME == ARGV[1] { curd[$1] = 1; next }
        FILENAME == ARGV[2] { if (!($1 in curd)) gone[$1] = 1; next }
        FILENAME == ARGV[3] { curf[$1] = 1; next }
        !($1 in curf) { oldf[$1] = 1 }
        END {
            for (d in gone) if (!under(d)) print R "/" d
            for (f in oldf) if (!under(f)) print R "/" f
        }' "$new_dirs" "$dirs" "$new_files" "$manifest" > "$deleted"

    local n_changed n_deleted total
    n_changed=$(wc -l < "$changed"); n_deleted=$(wc -l < "$deleted")
    total=$(awk -F'\t' 'NR == FNR { c[$1] = 1; next } $1 in c { s += $2 } END { printf "%d", s }' "$changed" "$new_files")
    log "[$id] $n_changed to upload ($total bytes), $n_deleted to delete"

    local status=0 n_failed=0
    if ((n_changed > 0)); then
        st_set "$id" state=staging "msg=Preparing $n_changed files"
        stage="$STAGE_ROOT/$id"
        rm -rf "$stage"; mkdir -p "$stage"
        # Un archivo que se borró entre el escaneo y la copia no es un error
        tar -C "$src" --verbatim-files-from -T "$changed" -cf - 2>>"$LOG" | tar -C "$stage" -xf - 2>>"$LOG"

        st_set "$id" state=uploading "msg=Connecting to Proton Drive"
        if ! ensure_remote "$remote"; then
            st_set "$id" state=error "msg=Could not create $remote (session expired?)" finished="$(date +%s)"
            log "[$id] ensure_remote failed"; rm -rf "$stage"; rm -f "$new_files" "$new_dirs" "$changed" "$deleted"
            return 1
        fi
        printf 'done=0\ntotal=%d\npct=0\nspeed=0\neta=-1\nfiles_done=0\nfiles_failed=0\ncurrent=\n' "$total" > "$progress"
        st_set "$id" "msg=Uploading $n_changed files"

        local items=() cmd
        shopt -s dotglob nullglob; items=("$stage"/*); shopt -u dotglob nullglob
        # Columnas anchas para que el CLI no recorte los nombres de la barra
        printf -v cmd '%q ' "$PD" fs upload -f create-new-revision -d merge "${items[@]}" "$remote"
        cmd="stty cols 400 rows 60; exec $cmd"
        script -qfec "$cmd" /dev/null < /dev/null \
            | gawk -v total="$total" -v PROGRESS="$progress" -v RUNLOG="$runlog" -v FAILED="$failed" -v ok=1 "$PARSER"
        status=${PIPESTATUS[0]}
        rm -rf "$stage"
        n_failed=$(wc -l 2>/dev/null < "$failed" || echo 0)

        if ((status != 0)) && ! grep -q '^Transfer summary:' "$runlog"; then
            local why
            why="$(grep -vE '^\s*$' "$runlog" | tail -1)"
            grep -qi 'login' "$runlog" && why="Proton session expired: press L to sign in"
            st_set "$id" state=error "msg=${why:-The Proton CLI exited with error $status}" finished="$(date +%s)"
            log "[$id] upload failed ($status): $why"
            rm -f "$new_files" "$new_dirs" "$changed" "$deleted"
            return 1
        fi
    fi

    if ((n_deleted > 0)); then
        st_set "$id" state=cleaning "msg=Moving $n_deleted deleted items to the trash"
        trash_paths "$id" < "$deleted" >/dev/null
    fi

    # Manifiesto nuevo; los que fallaron se sacan para reintentarlos la próxima
    if [[ -s "$failed" ]]; then
        awk -F'\t' 'NR == FNR { bad[$0] = 1; next } { n = $1; sub(/.*\//, "", n) } !(n in bad)' \
            "$failed" "$new_files" > "$manifest"
    else
        mv "$new_files" "$manifest"
    fi
    mv "$new_dirs" "$dirs"
    rm -f "$new_files" "$changed" "$deleted"

    local files bytes now msg
    files=$(wc -l < "$manifest"); bytes=$(awk -F'\t' '{ s += $2 } END { printf "%d", s }' "$manifest")
    now=$(date +%s)
    msg="$n_changed uploaded, $n_deleted moved to trash"
    ((n_changed == 0 && n_deleted == 0)) && msg="No changes"
    if ((n_failed > 0)); then
        st_set "$id" state=error "msg=$n_failed files failed (see the log with l)" finished="$now" \
            last_files="$files" last_bytes="$bytes"
        log "[$id] finished with $n_failed failed"
        return 1
    fi
    st_set "$id" state=ok "msg=$msg" finished="$now" last_ok="$now" last_files="$files" last_bytes="$bytes" \
        last_up="$n_changed" last_del="$n_deleted"
    log "[$id] ok: $msg"
}

cmd_run() {
    local ids=("$@") id ok=0 bad=0 names=()
    ((${#ids[@]})) || mapfile -t ids < <(all_ids)
    exec 9>"$STATE_DIR/lock"
    flock -n 9 || { echo "An upload is already in progress" >&2; exit 1; }
    echo $$ > "$PIDFILE"
    CUR_ID=""
    trap 'trap - TERM INT; [[ -n "$CUR_ID" ]] && st_set "$CUR_ID" state=cancelled "msg=Cancelled" finished="$(date +%s)";
          for i in "${ids[@]}"; do [[ "$(st_get "$i" state)" == queued ]] && st_set "$i" state=idle msg=; done;
          rm -rf "$STAGE_ROOT"; rm -f "$PIDFILE"; log "cancelled"; exit 130' TERM INT
    log "start: ${ids[*]}"
    for id in "${ids[@]}"; do
        if backup_one "$id"; then ok=$((ok + 1)); else bad=$((bad + 1)); names+=("$(field "$id" 3)"); fi
    done
    rm -f "$PIDFILE"
    if ((bad)); then
        notify-send -u critical -a "Proton Backup" "Backup finished with errors" "Failed: ${names[*]}" 2>/dev/null
    else
        notify-send -a "Proton Backup" "Backup complete" "$ok folder(s) updated in Proton Drive" 2>/dev/null
    fi
}

cmd_start() {
    running && { echo "An upload is already in progress" >&2; exit 1; }
    local ids=("$@") id
    ((${#ids[@]})) || mapfile -t ids < <(all_ids)
    for id in "${ids[@]}"; do st_set "$id" state=queued "msg=Queued"; rm -f "$STATE_DIR/$id.progress"; done
    setsid -f bash "$SELF" run "${ids[@]}" >>"$LOG" 2>&1 < /dev/null
}

cmd_cancel() {
    local pid
    running || return 0
    pid="$(cat "$PIDFILE")"
    # El runner es líder de su grupo (setsid): se corta junto con script y el CLI
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
}

case "${1:-}" in
    run)     shift; cmd_run "$@" ;;
    start)   shift; cmd_start "$@" ;;
    cancel)  cmd_cancel ;;
    running) running ;;
    *) echo "Usage: $(basename "$0") start|run [id...] | cancel | running" >&2; exit 2 ;;
esac
