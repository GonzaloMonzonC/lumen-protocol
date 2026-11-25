# Nodo de pruebas en la NAS — montado y medido

> 2026-11-24. Nodo **aislado** en la NAS, sin tocar el `mvm-nas` de neferu.

---

## 1 · Qué se ha montado

| | |
|---|---|
| Ruta | `/volume1/backup/lumen-test/` |
| Binario | `mvm-nas-test` (5,85 MB, ELF 32-bit ARM, estático) |
| PDB | `test-pdb.lmdb` |
| Producción de neferu | `/volume1/backup/neferu/` — **intacta** |

Verificado que neferu sigue con su binario del 7 de octubre, mismo tamaño, misma
fecha. El nodo de pruebas no comparte ni binario ni base de datos.

## 2 · Cómo se compiló

El cross-build necesitaba un compilador C para ARM y no había toolchain. Se
resolvió con **zig** (ya instalado en `~/tools/zig-x86_64-windows-0.16.0`):

```bash
export PATH="/c/Users/gonzalo/tools/zig-x86_64-windows-0.16.0:$PATH"
cargo zigbuild --release --target armv7-unknown-linux-musleabi
```

Resultado: `ELF 32-bit LSB executable, ARM, EABI5, statically linked`.

**El SCP está deshabilitado en la NAS.** Para subir ficheros:
```bash
cat binario | ssh nasdedavid@192.168.1.14 'cat > destino && chmod +x destino'
```

## 3 · Qué funciona

```
· store LMDB directo (sin precarga): test-pdb.lmdb
escrito: lumen-test-armv7
[completed · 89.0 ms]
```

Y persiste entre ejecuciones (relanzar y releer da el valor, en 0,6 ms).

## 4 · EL HALLAZGO: 74 ms por escritura en ARMv7

| Escrituras | Tiempo | Por escritura |
|---|---:|---:|
| 10 | 689 ms | 69 ms |
| 100 | 4.799 ms | 48 ms |
| 1.000 | **74.073 ms** | **74 ms** |

En el PC, 1.000 escrituras son microsegundos. En la NAS, **74 segundos**.

### La causa

`lmdb_store.rs` línea 311: **una transacción con `commit()` por cada `set`**.
Cada commit hace `fsync`, y en el disco de la NAS cada `fsync` cuesta 50-70 ms.

### El arreglo ya existe

```bash
LUMEN_LMDB_NOSYNC=1
```

| | 1.000 escrituras |
|---|---:|
| Con fsync (por defecto) | 74.073 ms |
| Con `NOSYNC=1` | **207 ms** |

**357× más rápido.** El precio: sin fsync se puede perder lo último ante un
corte de luz, pero el motor sigue siendo coherente (LMDB no corrompe).

## 5 · Lo que esto significa para el diseño de replicación

Esto **cambia una decisión** que dimos por buena:

Un barco escribe a 1 Hz. Con fsync por escritura, **una muestra por segundo es
sostenible** (74 ms < 1.000 ms), pero:

- **Replicar 21.600 muestras con fsync por hecho = 26 minutos.** Inaceptable.
- **Con NOSYNC, 21.600 muestras = ~4,5 segundos.** Viable.

Y aparece una tercera opción que no habíamos considerado: **commit por lote**.
En vez de una transacción por escritura, una cada N. Es el punto medio entre
durabilidad y velocidad, y es lo que hace cualquier base de datos seria.

## 6 · Lo que NO se ha hecho aún

- **La replicación no está en el binario de la NAS.** `mvm-nas` no usa
  `lumen-nodo`, así que no tiene `hechos_store` ni `hechos_wire`. Lo que se ha
  probado en la NAS es el **motor y LMDB**, no la replicación.
- Para probar la replicación en la NAS haría falta o bien portar el módulo a
  `mvm-nas`, o compilar un binario desde `lumen-nodo` para ARM.

## 7 · Decisión pendiente

El hallazgo del `fsync` obliga a decidir **antes** de seguir con la replicación:

1. **Una transacción por hecho** (actual): simple, correcto, inservible a escala
   en disco lento.
2. **NOSYNC**: rápido, pero se pierde lo último ante un corte. Para telemetría
   puede ser aceptable — una muestra perdida de 21.600 no cambia nada.
3. **Commit por lote** (cada N hechos): el equilibrio. Más código, pero es lo
   que hace un sistema serio.

Mi recomendación: **por lote, configurable en el perfil** — encaja con la idea de
que todo es configurable, y permite que un barco elija durabilidad y un dron
elija velocidad.
