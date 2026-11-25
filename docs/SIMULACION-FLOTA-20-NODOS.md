# Simulación de flota — 20 nodos reales

> 2026-11-24. Veinte procesos `mvm-nas` reales, cada uno con su LMDB, escribiendo
> a la vez. Orquestador: `simular_flota.py`.

---

## 1 · Qué simula y qué no

**Simula:** N nodos independientes escribiendo telemetría en paralelo, cada uno
con su proceso y su base. Eso estresa CPU, disco, memoria y descriptor de
ficheros de forma realista.

**No simula:** la red. Aquí no hay replicación por QUIC entre nodos; cada uno
escribe en local. La replicación está probada aparte (`quic_e2e`,
`flota_multinodo`).

## 2 · Resultado

```
SIMULACION DE FLOTA — 20 nodos, 300 muestras cada uno
total muestras a escribir: 6000

[1] ESCRITURA EN PARALELO
    nodos que terminaron bien: 20 de 20
    tiempo por nodo: min=7.749 ms  mediana=8.212 ms  max=8.477 ms
    tiempo de PARED (los 20 a la vez): 8,5 s
    muestras/s agregadas: 706

[2] INTEGRIDAD
    nodos con pérdida: 0 de 20      ← ninguna muestra perdida

[3] ESPACIO
    ocupado: 671 MB (33 MB por nodo)
```

**La flota aguanta.** Ni un error, ni una muestra perdida.

Los tiempos por nodo están **muy agrupados** (7,7 – 8,5 s): no hay uno que se
quede atrás, que es lo que pasaría si hubiera contención seria.

## 3 · Tres cosas que salieron al ejecutarlo

Ninguna era del sistema. Las tres eran del entorno, y las tres importan.

### 3.1 LMDB reserva 1 GB de mmap por defecto

Con 20 nodos son **20 GB de espacio de direcciones**. En un disco con poco
margen da `error 112: Espacio en disco insuficiente`.

Solución: `LUMEN_LMDB_MAPSIZE_MB`. En la simulación se usa 32 MB, y sigue siendo
realista — un barco no necesita 1 GB de mapa.

**Es un ajuste que el perfil debería poder fijar**, igual que la durabilidad.
Hoy es variable de entorno.

### 3.2 El disco del PC estaba al 100 %

**117 MB libres.** Mis propias simulaciones anteriores dejaron 2,2 GB de
temporales, y eso hizo fallar la de 20 nodos de una forma que **parecía un bug
del sistema**:

```
nodos que terminaron bien: 0 de 3
```

Antes de acusar al software, mirar el disco. Costó dos intentos darse cuenta.

### 3.3 `data.mdb` de 1 GB no es lo ocupado

Al medir el espacio, `data.mdb` aparece con 1 GB por nodo: es el **mmap
reservado**, no disco escrito. El consumo real se ve en los bloques asignados
(o bajando `MAPSIZE`).

## 4 · Lo que esto NO prueba

- **No prueba replicación entre los 20.** Cada nodo escribe en su LMDB y nadie
  se lo lleva. La verificación de flota con varios nodos está en
  `flota_multinodo.rs`, con 5 barcos por QUIC.
- **No prueba cortes ni particiones.** Todos escriben de corrido.
- **No prueba el hub.** No hay hub central en esta simulación.

## 5 · Siguiente paso natural

**Juntar las dos cosas:** los 20 nodos escribiendo *y* replicando a un hub por
QUIC. Eso sí sería el escenario del paper: una flota convergiendo.

Hoy están separadas porque la replicación necesita el módulo de `lumen-nodo` y
`mvm-nas` no lo lleva. Habría que portarlo o compilar el nodo desde
`lumen-nodo`.

## 6 · Cómo repetirlo

```bash
cd ~/AppData/Local/hermes/scripts
LUMEN_LMDB_MAPSIZE_MB=32 python simular_flota.py 20 300
```

Parámetros: `[n_nodos] [n_muestras]`. Con `--keep` conserva los datos para
inspeccionarlos.
