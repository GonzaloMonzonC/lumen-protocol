# El nodo real verifica flota de punta a punta

> 2026-11-26. Primera vez que `lumen-nodo` (el binario de producción, no la
> simulación) acepta una escritura **verificando que viene de un barco de la
> flota**. Reproducible: `experimentos/flota/nodo_real_e2e.py`

---

## 1 · El resultado

```
FLOTA: raiz del armador a9b6d470af2bbc5b...
FLOTA: 1 barcos en el registro
--- conexion #1 aceptada ---
  flota OK: 'BARCO-T' firmado y respaldado por la raiz del armador
  aplicado ^FLOTA(BARCO-T,lat,1)=<200 bytes>
--- conexion #1 cerrada: 1 aplicados, 0 fallidos, 230 bytes ---

respuesta: SUCCESS (aplicado por el par)
```

**La frase que importa:** *"flota OK: 'BARCO-T' firmado y respaldado por la raíz
del armador"*.

---

## 2 · Lo que NO faltaba

Mi primer diagnóstico fue erróneo y conviene dejarlo escrito:

> *"El nodo real no sabe recibir hechos; falta el bucle de recepción."*

**Falso.** El bucle ya existía:

```rust
nodo::atender(&mut transporte, destino, firmar, firmante,
              registro.as_ref(), raiz.as_deref(), &mut log)
```

Con registro de flota, raíz del armador y contadores de aplicados/fallidos. El
código estaba completo; **lo que faltaba era saber arrancarlo**.

## 3 · Lo que sí faltaba: saber configurar el nodo

El nodo se niega a verificar si no tiene con qué, y lo dice:

```
rechazado: este nodo no tiene registro de flota ni raiz de armador:
           no puede verificar muestras firmadas
```

**Ese rechazo es correcto.** Es el comportamiento que se busca: no guardar nada
que no se pueda comprobar.

Para que verifique hacen falta cuatro cosas:

| Pieza | Dónde |
|---|---|
| `^SYS("NET","raiz_armador")` | perfil del nodo (PDB) |
| `^SYS("NET","identity")="pubkey"` + `clave_publica` | perfil del nodo (PDB) |
| `semilla` de la identidad | `--semilla <hex>`, **nunca en el perfil** |
| `^FLOTA(<barco>,"clave"/"certificado")` | almacén del nodo (`^almacen`) |

## 4 · Tres trampas que costaron el rato

**1. El subkey de `_globals` es binario y lleva la RUTA, no el namespace.**

```python
# MAL: la tabla se llama ns='SYS', pero la ruta es ^SYS("NET",...)
subkey = b'\x02SYS\xff\x02' + campo + b'\xff'

# BIEN
subkey = b'\x02NET\xff\x02' + campo + b'\xff'
```

Con el formato mal, el nodo **no da error**: usa el perfil mínimo por defecto, y
luego rechaza el tráfico. El síntoma aparece lejos de la causa.

**2. La raíz solo se lee si `identity=pubkey`.** Con `identity=none` el nodo
arranca, escucha... y nunca lee `raiz_armador`. El bloque que la carga está dentro
de la rama de identidad pública.

**3. El registro de flota va en el ALMACÉN, no en la PDB.** `--registrar-barco`
escribe en `^FLOTA` del `--almacen`, y el nodo lo lee de ahí al arrancar.

## 5 · Qué significa para una versión funcional

**No falta código.** La replicación, la verificación de flota, la cadena, las
firmas y la custodia de epoch están implementadas, probadas y ahora **ejercitadas
de punta a punta en el binario real**.

Lo que falta es **documentar el arranque**: los cuatro pasos de la sección 3, y
las tres trampas de la sección 4. Eso es lo que convierte "funciona en mi prueba"
en "se puede desplegar".

## 6 · Lo que este script NO prueba

- **Un barco que envíe hechos firmados de flota por el protocolo de hechos.**
  Este E2E usa `--enviar` (escritura M firmada y encadenada), que es el camino de
  producción de la PDB. El camino de hechos (`recibir_hechos_de_flota`, mensaje
  `CERT|`) está probado en `sim_flota` con 40 barcos y en los tests unitarios.

  **Son dos caminos distintos y conviene no confundirlos:**
  - `--enviar` → escrituras M → `nodo::atender` (probado aquí)
  - hechos firmados → `recibir_hechos_de_flota` (probado en simulación)

- **Reinicio y persistencia** del nodo real tras esta conexión.
- **Varios barcos** contra el mismo hub real (solo se probó uno).
