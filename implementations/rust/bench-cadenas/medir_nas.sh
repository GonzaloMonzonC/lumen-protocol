#!/bin/bash
# Mide las fases del banco en la NAS con reloj EXTERNO.
# El binario no puede medir: el kernel 3.2 hace panic en SystemTime/Instant.

cd /volume1/backup/lumen-test || exit 1

medir() {
  local fase=$1 n=$2 bl=$3
  local t0 t1
  t0=$(date +%s%N)
  ./bcadenas "$fase" "$n" "$bl" > /dev/null 2>&1
  t1=$(date +%s%N)
  echo $(( (t1 - t0) / 1000000 ))
}

for N in 1000 5000 21600; do
  echo "=== n=$N ==="
  TARA=$(medir nada "$N" 100)
  CAD=$(medir cadena "$N" 100)
  FIR=$(medir firmar "$N" 100)
  VER=$(medir ver "$N" 100)
  SEL=$(medir sellos "$N" 100)

  # Restar la tara del arranque
  CAD=$((CAD - TARA)); [ $CAD -lt 0 ] && CAD=0
  FIR=$((FIR - TARA)); [ $FIR -lt 0 ] && FIR=0
  VER=$((VER - TARA)); [ $VER -lt 0 ] && VER=0
  SEL=$((SEL - TARA)); [ $SEL -lt 0 ] && SEL=0

  echo "  tara arranque : ${TARA} ms"
  echo "  cadena        : ${CAD} ms"
  echo "  firmar        : ${FIR} ms"
  echo "  verificar     : ${VER} ms"
  echo "  sellos (f+ver): ${SEL} ms"

  # us por hecho con enteros (ms*1000/n)
  if [ "$N" -gt 0 ]; then
    echo "  --- us/hecho ---"
    echo "  cadena        : $(( CAD * 1000 / N ))"
    echo "  firmar        : $(( FIR * 1000 / N ))"
    echo "  verificar     : $(( VER * 1000 / N ))"
    echo "  sellos        : $(( SEL * 1000 / N ))"
  fi
  echo
done
