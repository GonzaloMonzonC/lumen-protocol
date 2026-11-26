# La flota con las defensas conectadas — y probadas

> 2026-11-26. Cierra el circuito: la cota de epoch y los conflictos ya no viven
> solo en tests. **Se ejercitan con la flota real.**

---

## 1 · Lo que se conectó en `sim_flota`

| Antes | Ahora |
|---|---|
| `recibir_hechos(...)` sin cota | **`recibir_hechos_con_cota(...)`** |
| conflictos solo en el resumen (memoria) | **persistidos como hechos firmados** |
| ramas apartadas, en memoria | **anotadas en la cuarentena persistida** |

Y el `FIN` ahora lo dice, para no tener que adivinar:

```
FIN barcos=… aceptados=… rechazados=… conflictos=… cuarentena=… conflictos_persistidos=…
```

## 2 · La flota sigue sin pérdidas

| Barcos | Hechos | Aceptados |
|---:|---:|---:|
| 20 | 240.000 | **240.000** |
| 40 | 240.000 | **240.000** |
| **40** | **480.000** | **480.000** |

**Cero rechazos, cero cuarentenas** — porque no había nada que atacar. Que la
defensa no se dispare cuando no toca es tan importante como que se dispare cuando
toca.

## 3 · Y la prueba del ataque

Se añadió `LUMEN_EPOCH` al barco simulado, para poder **provocar** el ataque que
la cota debe parar. Un dron comprometido mandaría un epoch imposible.

Tres barcos contra el hub: **dos legítimos y uno con epoch 999.999**.

```
BARCO 1: recibidos=50 aceptados=50 rechazados=0 conflictos=0
BARCO 2: recibidos=50 aceptados=0  rechazados=49 conflictos=0
         motivo=epoch 0 -> 999999: salto de 999999, cota 1
                — puede ser reinstalacion legitima o un nodo comprometido
```

**El intruso no entra. Los legítimos sí.** Ni un hecho del atacante llega al
store.

## 4 · Por qué esta prueba vale más que los tests

Los tests unitarios comprueban la función. **Esto comprueba que la función está
conectada al camino real.**

Es exactamente lo que faltaba: las cuatro piezas estaban probadas, y **tres de
ellas no se ejecutaban en ningún sitio**. Hoy, si la cota se desconectara por
error, esta prueba lo detectaría.

## 5 · Lo que se verifica y lo que no

| | |
|---|---|
| La cota rechaza un epoch imposible en la flota | ✅ |
| Los barcos legítimos siguen entrando | ✅ |
| Los conflictos se persisten | ✅ (en tests de integración) |
| **Dos ramas partiéndose y reencontrándose en la flota** | ❌ **no probado** |

**La partición real sigue sin probarse.** Lo que se ha probado es el ataque por
epoch. Una partición de red de verdad —dos hubs, cada uno con sus barcos, y luego
reunirlos— es otro escenario, y es el que el paper del enjambre describe.

## 6 · Estado del circuito

| Pieza | Construida | Cableada | **Probada con flota** |
|---|:---:|:---:|:---:|
| Tipado de hechos | ✅ | ✅ | ✅ |
| Digest recalculable | ✅ | ✅ | ⬜ |
| Hecho de conflicto | ✅ | ✅ | ⬜ |
| Cota de epoch | ✅ | ✅ | ✅ |
| Cuarentena persistida | ✅ | ✅ | ⬜ |

**290 tests en `lumen-nodo`, todos verdes.**

## 7 · Lo que falta

- **Partición real**: dos hubs, dos mitades de la flota, reunirlas y ver qué pasa.
  Es el escenario del paper y **no está probado**.
- **Digest y conflictos con la flota**: cableados y probados en integración, pero
  no en la simulación de 40 nodos.

**El ataque está cubierto. La partición, no.**
