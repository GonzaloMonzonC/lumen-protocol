#!/usr/bin/env python3
"""FIX en el INIT BASE: configurar DDP en el arranque.

CAUSA RAIZ (medida en el Asus real, oct-2026):
  · wget del ISO -> SEGFAULT en cualquier HTTP  => el sondeo del hub falla SIEMPRE
  · $DEVICE("http:get") -> SSRF bloqueado para IP privada
  => HUB="" siempre => ^CONFIG("ddp_peer") NUNCA se ponia => los nodos NUNCA
     hablaron DDP (por eso "el hub DDP sigue sin configurar").
Arreglo: hub.conf manda (HUB=<ip> + DDP_KEY) y el init escribe la config del nodo.
"""
P = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/init"
s = open(P, encoding="utf-8", newline="").read()

old = '''HUB=""
GW=$(ip route 2>/dev/null | awk '/default/{print $3; exit}')
for h in 192.168.1.10 192.168.1.14 "$GW"; do
    [ -z "$h" ] && continue
    if wget -q -O /dev/null -T 3 "http://$h:8081/health" 2>/dev/null; then HUB="$h"; break; fi
done
CONKEY="no"
if [ -n "$HUB" ]; then
    echo "[ddp] hub en $HUB:8081"
    if [ -f /etc/hub.conf ]; then
        . /etc/hub.conf
        [ -n "$DDP_KEY" ] && CONKEY="si" && echo "[ddp] credenciales cargadas"
    fi
fi'''

new = '''# --- DDP: el hub. CONFIGURADO manda; el sondeo es solo respaldo. ---
# OJO (medido en el Asus, oct-2026): el wget de este ISO casca con SEGFAULT en
# cualquier HTTP, y $DEVICE("http:get") bloquea IPs privadas por SSRF: el sondeo
# NO es fiable. Por eso hub.conf lleva HUB=<ip> y aqui se configura el nodo.
HUB=""
DDP_KEY=""
if [ -f /etc/hub.conf ]; then
    . /etc/hub.conf
    [ -n "$HUB" ] && echo "[ddp] hub configurado: $HUB"
fi
if [ -z "$HUB" ]; then
    GW=$(ip route 2>/dev/null | awk '/default/{print $3; exit}')
    for h in 192.168.1.10 192.168.1.14 "$GW"; do
        [ -z "$h" ] && continue
        if wget -q -O /dev/null -T 3 "http://$h:8081/health" 2>/dev/null; then HUB="$h"; break; fi
    done
fi
CONKEY="no"
if [ -n "$HUB" ] && [ -n "$DDP_KEY" ]; then
    CONKEY="si"
    echo "[ddp] hub $HUB:8081 - credenciales cargadas"
    # Sin esto el nodo NO habla con el hub: ddp_peer vacio = DDP inerte.
    /opt/mvm/mvm-nas -p "$PDB" -r /opt/mvm/routines -e \\
"S ^CONFIG(\\"ddp_peer\\")=\\"http://$HUB:8081\\" S ^CONFIG(\\"ddp_hmac_key\\")=\\"$DDP_KEY\\"" \\
        >/dev/null 2>&1
    echo "[ddp] nodo configurado para hablar DDP (peer + clave)"
fi'''

assert old in s, "no encontre el bloque del hub en el init base"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("init base OK: DDP se configura en el arranque")
