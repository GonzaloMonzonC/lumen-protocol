# Publicación en OpenTimestamps (el "notario")

El doc `10` lo pide explícitamente:

> *"LUMEN no necesita una cadena para ser confiable; necesita **raíces de Merkle y
> un notario público**. La cadena es una opción de compra, no la arquitectura."*

`merkle_epoch.py` + `anclaje.py` dan las raíces. Esto da el notario.

---

## Por qué no se usa el cliente `ots`

`opentimestamps-client` depende de `python-bitcoinlib` con su parte nativa, y
**falla en Windows**:

```
OSError: [WinError 193] %1 no es una aplicación Win32 válida
```

Así que `publicar_ots.py` habla el protocolo **directamente por HTTP**.

---

## El protocolo, en corto

Un calendar server acepta un **POST de 32 bytes** (el digest sha256) y devuelve
una **prueba de compromiso** binaria:

```
POST https://alice.btc.calendar.opentimestamps.org/digest
Content-Type: application/x-www-form-urlencoded
Accept: application/vnd.opentimestamps.v1
<body: 32 bytes del digest>

→ HTTP 200, application/vnd.opentimestamps.v1
→ 137-172 bytes: "tu digest está en mi árbol, en tal posición"
```

Horas después el calendar agrega su árbol en una **transacción de Bitcoin**.
Entonces la prueba se puede completar (`upgrade`) y verificar contra el bloque.

Los calendars públicos son **gratuitos**: alice, bob (ambos de OpenTimestamps) y
finney (Eternity Wall). Se prueban en orden; si uno falla, el siguiente.

---

## Uso

```python
from anclaje import sellar_epoch

sello = sellar_epoch(pdb, "LOTE", publicar="ots")
# sello["publicado"]   -> True
# sello["publicado_en"] -> "https://alice.btc.calendar.opentimestamps.org"
# sello["ots"]["prueba_hex"] -> la prueba de compromiso
```

O directo:

```python
from publicar_ots import sellar_en_ots, pedir_upgrade

s = sellar_en_ots(root_hex)
s = pedir_upgrade(bytes.fromhex(s["prueba_hex"]))   # horas después
```

Ficheros: `ots/<root[:16]>.ots.bin` (prueba binaria) y `.json` (sello completo).
Directorio configurable con `LUMEN_OTS_DIR`.

---

## Verificado (con red)

```
calendar : alice.btc.calendar.opentimestamps.org
root     : 391ed86342da8c7abbd99e08ce27133c...
bytes    : 172
publicado: True
```

Y en el flujo completo: `sellar_epoch(pdb, "LOTE", publicar="ots")` calcula el
root, lo deja en `^AUDIT`, lo ancla en Bitcoin y guarda la prueba.

`test_ots.py` cubre: calendars responden, anclaje, persistencia, digests
distintos y la integración con el sellado. **Si no hay red, sale con SKIP** (no
FALLO): el anclaje externo es opcional, el resto del sistema funciona sin él.

---

## Lo que esto consigue

Antes: la prueba de inclusión valía si te fiabas de quien te la daba.

Ahora: **el root está comprometido en un árbol público cuyo compromiso acaba en
Bitcoin**. Un auditor puede comprobar:

1. que el dato está en el root (prueba de Merkle, local, sin red)
2. que el root existía en una fecha (la prueba OTS + el bloque)

Sin llamar a LUMEN, sin creerse nada de LUMEN.

---

## Lo que esto NO hace

- **No verifica hasta el bloque.** `pedir_upgrade` pide la prueba ampliada, pero
  validar la transacción de Bitcoin exige un nodo o un explorador. Eso se hace
  con `ots verify` en Linux/macOS, o consultando el bloque a mano.
- **No hay job de upgrade.** `pedir_upgrade` existe y se llama a mano; falta un
  cron que complete las pruebas cada pocas horas.
- **Depende de la red.** Sin conexión, `publicar="ots"` deja
  `publicado: False` y el sello sigue siendo válido internamente (root + `^AUDIT`
  + prueba de inclusión), solo que sin notario externo.
- **Los calendars pueden caer o cambiar.** Se prueban tres; si todos fallan, el
  sellado no se pierde, solo queda sin anclar.
- **No es una firma.** Prueba que el dato existía en una fecha, no **quién** lo
  emitió. Para eso hace falta HMAC por nodo (existe) o firma asimétrica (no).
