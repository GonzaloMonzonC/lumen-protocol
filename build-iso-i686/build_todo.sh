#!/usr/bin/env bash
# Compila TODO: ISOs i686 + x86-64, runtime ARM (NAS), LUMEN OS Windows.
# Cada paso en su propio log; si uno falla, los demas siguen. Al final, resumen.
set +e
FECHA=$(date +'%d-%m %H:%M')
LOG=/tmp/build_todo.log
: > "$LOG"
echo "=== BUILD TOTAL · $FECHA ===" | tee -a "$LOG"

# ---------- 0. DESCUBRIR los scripts que hay ----------
echo "" | tee -a "$LOG"
echo "--- 0. SCRIPTS DISPONIBLES ---" | tee -a "$LOG"
for d in /c/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686 \
         /c/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos \
         /c/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light; do
  if [ -d "$d" ]; then
    echo "  [$d]" | tee -a "$LOG"
    ls "$d" 2>/dev/null | grep -iE 'build|\.sh$|\.py$' | head -12 | sed 's/^/     /' | tee -a "$LOG"
  fi
done

# ---------- 1. ISO i686 ----------
echo "" | tee -a "$LOG"
echo "########## 1. ISO i686 ##########" | tee -a "$LOG"
cd /c/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686 || exit 1
rm -rf initramfs-i686                                     # LECCION DEL DIA: el arbol arrastra restos
python build_initramfs_i686.py > /tmp/b1.log 2>&1
grep -E 'initramfs-lumenos' /tmp/b1.log | tail -1 | sed 's/^/  /' | tee -a "$LOG"
python -c "
import glob
t=s=0
for f in glob.glob('initramfs-i686/opt/mvm/routines/*.m'):
    t+=1
    b=open(f,'rb').read()
    if sum(1 for c in b if c not in (10,13) and not (32<=c<127)): s+=1
print(f'  rutinas: {t}  sucias: {s}')" | tee -a "$LOG"
sed -i 's|/lumenos-i686.iso"|/lumenos-i686-FINAL.iso"|' build_iso_i686.py
python build_iso_i686.py 2>&1 | grep -E 'iso escrita' | sed 's/^/  /' | tee -a "$LOG"
sed -i 's|/lumenos-i686-FINAL.iso"|/lumenos-i686.iso"|' build_iso_i686.py
cp lumenos-i686-FINAL.iso /c/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/lumenos-i686-v0.1.25.iso 2>/dev/null
md5sum /c/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/lumenos-i686-v0.1.25.iso 2>/dev/null | sed 's/^/  /' | tee -a "$LOG"

# ---------- 2. ISO x86-64 (por Docker, Alpine) ----------
echo "" | tee -a "$LOG"
echo "########## 2. ISO x86-64 (Docker) ##########" | tee -a "$LOG"
cd /c/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos || exit 1
if ls _build*.sh >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    docker run --rm --platform linux/amd64 -v "/c/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos:/mvm" alpine:3.20 sh /mvm/_build_initramfs.sh > /tmp/b2a.log 2>&1
    echo "  initramfs x86-64: $(tail -2 /tmp/b2a.log | tr '\n' ' ')" | tee -a "$LOG"
    docker run --rm --platform linux/amd64 -v "/c/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos:/mvm" alpine:3.20 sh /mvm/_build_iso.sh > /tmp/b2b.log 2>&1
    echo "  iso x86-64: $(tail -2 /tmp/b2b.log | tr '\n' ' ')" | tee -a "$LOG"
  else
    echo "  SKIP: Docker no esta levantado (arrancarlo y reintentar)" | tee -a "$LOG"
  fi
else
  echo "  SKIP: no encuentro _build_initramfs.sh / _build_iso.sh en mvm-nas/lumenos" | tee -a "$LOG"
fi

# ---------- 3. Runtime ARM (NAS, armv7) ----------
echo "" | tee -a "$LOG"
echo "########## 3. ARM armv7 (NAS) ##########" | tee -a "$LOG"
cd /c/Users/gonzalo/Documents/GitHub/mvm-nas || exit 1
export RUSTFLAGS="-C link-self-contained=no"
export CARGO_TARGET_ARMV7_UNKNOWN_LINUX_MUSLEABI_LINKER="C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/zigcc-armv7-musleabi.exe"
export CC="C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/zigcc-armv7-musleabi.exe"
export AR="C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/zigar-armv7-musleabi.exe"
ls /c/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/ | grep -i 'armv7' | sed 's/^/  wrapper: /' | tee -a "$LOG"
cargo build --release --target armv7-unknown-linux-musleabi 2>&1 | grep -E '^error|error\[|Finished' | tail -3 | sed 's/^/  /' | tee -a "$LOG"
if [ -f target/armv7-unknown-linux-musleabi/release/mvm-nas ]; then
  cp target/armv7-unknown-linux-musleabi/release/mvm-nas deploy/bin/mvm-nas-armv7-musl 2>/dev/null
  ls -la deploy/bin/mvm-nas-armv7-musl 2>/dev/null | awk '{print "  ARM bin: "$5" bytes"}' | tee -a "$LOG"
fi

# ---------- 4. LUMEN OS para Windows ----------
echo "" | tee -a "$LOG"
echo "########## 4. Windows ##########" | tee -a "$LOG"
cd /c/Users/gonzalo/Documents/GitHub/mvm-nas || exit 1
unset CARGO_TARGET_ARMV7_UNKNOWN_LINUX_MUSLEABI_LINKER CC AR
unset RUSTFLAGS
cargo build --release 2>&1 | grep -E '^error|error\[|Finished' | tail -3 | sed 's/^/  /' | tee -a "$LOG"
ls -la target/release/mvm-nas.exe 2>/dev/null | awk '{print "  Windows bin: "$5" bytes"}' | tee -a "$LOG"

# ---------- RESUMEN ----------
echo "" | tee -a "$LOG"
echo "=== RESUMEN ($(date +'%H:%M')) ===" | tee -a "$LOG"
ls -la --time-style=+%d-%H:%M /c/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/*.iso 2>/dev/null | awk '{print "  ISO  "$5"  "$6"  "$7}' | tee -a "$LOG"
ls -la --time-style=+%d-%H:%M /c/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/bin/ 2>/dev/null | grep -E 'mvm-nas' | awk '{print "  BIN  "$5"  "$7}' | tee -a "$LOG"
echo "=== FIN ===" | tee -a "$LOG"
