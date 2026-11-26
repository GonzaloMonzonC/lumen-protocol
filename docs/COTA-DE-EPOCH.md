# Cota de epoch — lo que la custodia sola no puede parar

> 2026-11-26. Cuarta y última pieza de "semanas" del diseño de reconvergencia.
> Código: `lumen-nodo/src/cota_epoch.rs` + `epoch::verificar_con_cota`

---

## 1 · El ataque, tal como lo describió Smith

> *"Cualquiera con la clave de un dron fabrica `epoch = 2^63`, y como el merge es
> monótono, ese sello es **estado absorbente irreversible** — no puedes deshacerlo
> sin violar 'nunca se borra'."*

## 2 · Por qué la custodia no basta

La cadena de custodia (`epoch.rs`) exige que **cada salto esté firmado**. Impide
inventar un salto de 3 a 1000 sin firmar los 997 intermedios.

**Pero un nodo comprometido puede firmarlos todos.** Tiene la clave.

Verificado en test:

```
atacante firma 100 saltos validos
[OK] la custodia los acepta: Valido      ← EL AGUJERO
```

**Las firmas son válidas. La custodia no tiene nada que objetar.**

## 3 · La cota

Una segunda comprobación independiente: **¿es creíble este salto total?**

| Ataque | Lo para |
|---|---|
| Salto sin firmar | custodia |
| **1000 saltos firmados por un nodo comprometido** | **la cota** |

```
[OK] la cota lo detecta y NO lo absorbe
     epoch 0 -> 100: salto de 100, cota 1 — puede ser reinstalacion legitima
     o un nodo comprometido. NO se absorbe: requiere revision
```

## 4 · Cuarentena, no rechazo

El veredicto **no es "inválido"**: es **"no se absorbe, requiere revisión"**.

Esa distinción importa. Un salto grande puede ser:
- Un dron reinstalado tras perder la configuración (legítimo)
- Un nodo comprometido (ataque)

**No se puede saber cuál.** Así que la rama se aparta y **el nodo sigue operando
con la buena**:

```
[OK] la rama atacante queda apartada
[OK] la rama buena sigue operando
[OK] un operador puede liberarla tras revisar
```

## 5 · El texto del motivo dice lo que se sabe, no lo que se supone

```
epoch 0 -> 5000: salto de 5000, cota 1 — puede ser reinstalacion legitima
o un nodo comprometido. NO se absorbe: requiere revision
```

**No dice "ataque".** No se puede saber. Dice las dos posibilidades y deja la
decisión a quien tiene contexto.

## 6 · Y un detalle que evita un ataque de CPU

**La cota se comprueba ANTES de verificar las firmas.**

Si no, un atacante podría mandar un epoch enorme con 10.000 saltos firmados y
obligar al nodo a verificar 10.000 firmas Ed25519 antes de rechazarlo. En la NAS
eso son **3,5 ms por firma**: 35 segundos de CPU por mensaje.

Comprobar la cota primero cuesta **una resta**. Es la diferencia entre un ataque
de denegación y nada.

## 7 · Es configurable, porque el número depende del despliegue

| Despliegue | Cota razonable |
|---|---:|
| Dron que no se toca nunca | **1** (por defecto) |
| Dron que se reinstala a menudo | 5-10 |
| Flota con mantenimiento frecuente | 20+ |

```
[OK] cota 1  -> cuarentena (salto de 8)
[OK] cota 10 -> aceptado (salto de 8)
```

## 8 · Lo que esto NO hace

**No previene el ataque.** Smith fue explícito:

> *"Sin consenso, un dron comprometido es dueño del cielo. Lo único honesto es
> **detectar**, no prevenir."*

Un nodo comprometido **puede** seguir escribiendo hechos válidos con la clave que
tiene. La cota detecta el **salto de epoch**, que es la vía para hacerse con el
control del estado. Las demás vías necesitan:
- **Escrow** (un solo emisor por recurso) — meses
- **Consenso / BFT** — años

## 9 · Estado del diseño

| Pieza | Estado |
|---|---|
| **Tipado de hechos** | ✅ |
| **Digest recalculable** | ✅ |
| **Hecho de conflicto explícito** | ✅ |
| **Cota de epoch (cuarentena)** | ✅ |
| Propiedad por recurso (escrow) | ⬜ meses |

**Las cuatro piezas de "semanas" están completas. 279 tests verdes.**

## 10 · Lo que queda para cerrar la reconvergencia

Las piezas están, pero **no están cableadas entre sí**:

- **`recibir_hechos` no llama a `verificar_con_cota`.** La función está probada;
  falta usarla al recibir.
- **El hub no emite hechos de conflicto automáticamente.** Igual: probado, sin
  cablear.
- **La cuarentena no se persiste.** Hoy vive en memoria de un `Cuarentena`; si el
  nodo reinicia, se olvida — el mismo error que corregimos con los conflictos.

**Eso es fontanería, no diseño.** Y es lo siguiente que toca.
