# ADR-003 — Identidad de flota y prueba de bitácora

**Fecha:** 24-nov-2026
**Estado:** implementado y verificado
**Contexto:** ADR-002 (perfil de nodo). Paper P2P de LUMEN.

---

## El problema

Una telemetría que **llega** no es una telemetría que **prueba** nada. Hoy en el
mar eso se resuelve con AIS (un formato de 2001, sin integridad de payload) o con
terminales satelitales cerrados. En ninguno de los dos puedes responder, con
pruebas, a estas cuatro preguntas:

1. ¿Está **completa** la secuencia, o alguien quitó las horas que no le
   convenían?
2. ¿La alteró alguien por el camino?
3. ¿**Quién** la escribió?
4. ¿Ese quién es de **mi flota**, o se está haciendo pasar por uno de los míos?

Este ADR documenta el sistema que responde a las cuatro, verificado en
ejecución. Responde a esas cuatro y a **ninguna más**: lo que no prueba está en
la última sección, y es tan importante como lo que sí.

---

## Las cuatro pruebas

### 1. Completitud — `sign=hash-chain`

Cada muestra encadena el hash de la anterior:

```
hash_muestra = sha256( prev_hash || valor )
valor guardado = <valor>|<prev_hash>|<hash>
```

Como `prev` es el hash de la muestra anterior, **cambiar cualquier muestra
anterior cambia todos los hashes posteriores**. El verificador recorre la serie
y localiza el hueco exacto:

```
falta la muestra 7 (entre 6 y 8)
```

Cada 100 muestras se sella el bloque
(`sha256(sello_anterior || hash_1 || … || hash_100)`), lo que permite verificar
21.600 muestras con 216 comprobaciones en vez de 21.600 — la diferencia entre
auditar a bordo o no poder.

### 2. Integridad frente a manipulación

Misma cadena. Un valor cambiado sin recalcular el hash no cuadra; un hash
recalculado rompe el enlace con el siguiente. El verificador distingue los dos
casos (`CadenaRota` por valor vs por enlace).

### 3. Autoría — `identity=pubkey`

Cada muestra va firmada con la clave Ed25519 del barco:

```
valor guardado = <valor>|<prev_hash>|<hash>|<firma>
```

Se firma **el hash**, y eso tiene una consecuencia grande: como el hash incluye
el `prev`, **la firma cubre toda la cadena hasta el génesis**. Alterar la
muestra 3 hace que la firma de la muestra 4.000 deje de verificar.

El mensaje firmado incluye `ns` y los subíndices:

```
LUMEN-MUESTRA/v1\n<ns>\n<subs>\n<hash>
```

Eso impide **mover una muestra firmada a otra serie o posición**: la firma de
`^FLOTA(ESTRELLA,lat,7)` no vale para `^FLOTA(SIRIUS,lat,7)`.

### 4. Pertenencia a flota — raíz de armador

```
RAÍZ DEL ARMADOR (Ed25519)
   └── firma ──▶ clave del BARCO
                  └── firma ──▶ sus muestras
```

Un barco acepta a otro si su clave **cuelga de la raíz de su armador**. Sin
listas de hashes copiadas a mano y sin autoridad remota.

**Decisión importante:** se rechaza **por flota, no por firma**. Un barco de
otra armadora puede presentar una firma criptográficamente perfecta y aun así
se rechaza. Para un armador, "la firma es buena" no basta: tiene que ser **de
esta flota**.

---

## Verificación de entrada

Un nodo con raíz de armador configurada comprueba, **antes de escribir**:

1. el barco está en el registro de flota
2. su certificado lo emitió **nuestra** raíz
3. la clave del registro coincide con la del certificado
4. la cadena es válida y **cada muestra viene firmada** por esa clave

Si falla cualquiera, se responde `FAILURE` con el motivo. **No se guarda lo que
no se puede verificar.**

La muestra recibida se guarda **tal cual llegó**. El nodo no la re-encadena ni
la re-firma: si lo hiciera, dejaría de ser del barco y pasaría a ser del nodo,
y se perdería justo la autoría que se quiere probar.

### El registro no se toca por red

`^FLOTA(<barco>,"clave"|"certificado")` se siembra con una orden **local**
(`--registrar-barco`). Es deliberado: si un par pudiera registrar barcos por
red, **se registraría a sí mismo** y la verificación no serviría de nada.

---

## Qué prueba y qué NO prueba

Esta tabla es la parte más importante del documento.

| | `hash-chain` | `pubkey` + raíz |
|---|---|---|
| que no falta ningún tramo | ✅ | — |
| que nadie alteró una muestra | ✅ | ✅ |
| **quién** lo escribió | ❌ | ✅ |
| de qué flota es | ❌ | ✅ |
| **que el dato sea verdadero** | ❌ | ❌ |
| **que el reloj del barco fuera correcto** | ❌ | ❌ |
| **que el sensor no estuviera manipulado** | ❌ | ❌ |
| **que la clave no estuviera comprometida** | ❌ | ❌ |
| **que no existan dos historias válidas** | ❌ | ❌ |

Las cuatro últimas filas importan:

- **Dato verdadero**: se firma lo que el barco dice. Si el sensor miente, se
  firma una mentira con autoría perfecta.
- **Reloj**: el orden de la cadena es el orden en que el barco escribió. Si su
  reloj iba mal, las marcas de tiempo van mal y la firma no lo detecta.
- **Clave comprometida**: si alguien obtiene la semilla del barco, puede firmar
  como él y la verificación no lo distingue. La mitigación es custodia (la
  semilla no va en la PDB ni en el perfil) y **revocación por certificado**, que
  hoy no está implementada.
- **Dos historias**: si el barco emite dos ramas de su cadena (una para el
  armador y otra para el seguro), las dos verificarían por separado. **No hay
  anti-equivocación.** Eso requiere consenso, y es dinero — ver abajo.

---

## Lo que NO está implementado

| falta | por qué importa | coste |
|---|---|---|
| **Revocación de certificados** | una clave comprometida hoy sigue valiendo | diseño + lista de revocación por raíz |
| **Anti-equivocación** (dos ramas de la misma serie) | un barco puede contar dos historias | consenso — es el problema del dinero |
| **Atravesar NAT** (ICE/STUN/TURN) | detrás de CGNAT un barco no conecta | bloque grande, no un valor de config |
| `discovery=seeds` | solo hace falta fuera de la LAN; el problema real ahí es NAT | bajo, poco valor hoy |
| **Custodia de la semilla de la raíz** | si se filtra, hay que reemitir toda la flota | procedimiento operativo, no código |
| Verificación en el `--verificar` con sello firmado por bloque | hoy se verifica la cadena y las firmas de muestra; el sello se emite y se firma, pero el verificador aún no lo exige | bajo |

---

## Consecuencias

**A favor:** un barco puede demostrar completitud, integridad, autoría y flota
**sin confiar en ningún servidor**. Eso es lo que un armador, un asegurador o un
SAR necesitan, y hoy no lo tienen.

**En contra:** la PKI añade custodia de claves. Una semilla filtrada hoy no se
puede revocar. El sistema da pruebas de procedencia; **no** da verdad del dato.

**Y la frontera que no hay que cruzar:** esto **no es una criptomoneda**. No hay
ledger de valor, ni orden total, ni consenso, ni anti-doble-gasto. Es una
bitácora verificable. Llamarla dinero sería exactamente el tipo de exageración
que el ADR-002 existe para evitar. Si algún día hace falta dinero, antes hay que
escribir el ADR de consenso.
