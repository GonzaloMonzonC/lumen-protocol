#!/bin/sh
# Mide la verificacion POR LOTES en la NAS, con reloj externo.
#
# La pregunta: verificar 21.600 hechos de golpe bloquea el nodo ~77 s (por firma).
# Trocear en lotes no reduce el total, pero reduce el bloqueo MAXIMO.
#
# Se mide: tiempo total, numero de lotes, y por tanto el bloqueo por lote.

cd /volume1/backup/lumen-test || exit 1

medir() {
  local fase=$1 n=$2 lote=$3
  local t0 t1
  t0=$(date +%s%N)
  LOTE="$lote" ./bcadenas "$fase" "$n" "$lote" > /dev/null 2>&1
  t1=$(date +%s%N)
  echo $(( (t1 - t0) / 1000000 ))
}

# Tara
TARA=$(medir nada 100 100)
echo "tara arranque: ${TARA} ms"
echo

N=21600
echo "=== Verificar $N hechos por lotes (firma individual) ==="
printf '%-8s %10s %10s %14s\n' "lote" "total_ms" "lotes" "bloqueo/lote_ms"

for L in 64 256 1024 4096 21600; do
  T=$(medir lotes "$N" "$L")
  T=$((T - TARA)); [ $T -lt 0 ] && T=0
  LOTES=$(( (N + L - 1) / L ))
  PORLOTE=$(( T / LOTES ))
  printf '%-8s %10s %10s %14s\n' "$L" "$T" "$LOTES" "$PORLOTE"
done

echo
echo "=== Lo mismo con sellos (bloque 100) ==="
T=$(medir sellos "$N" 100)
T=$((T - TARA)); [ $T -lt 0 ] && T=0
echo "sellos $N hechos -> ${T} ms total (216 sellos)"
