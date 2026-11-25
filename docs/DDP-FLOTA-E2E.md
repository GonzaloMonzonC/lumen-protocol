# DDP de punta a punta — verificación de flota

> 2026-11-24. Cierra el eslabón que faltaba: **probar que la bitácora viene de un
> barco de MI flota**, no solo que alguien con una clave la firmó.
> Código en `src/hechos_wire.rs` · tests en `tests/flota_e2e.rs`.

---

## 1 · La diferencia que resuelve

| Antes | Ahora |
|---|---|
| "alguien con esta clave firmó esto" | **"esta clave es de un barco de mi flota"** |
| Cualquiera genera un par de claves y firma | Solo los barcos certificados por mi raíz de armador |
| El receptor confía en una clave suelta | El receptor confía en su **raíz de armador** |

Sin esto, un atacante genera un par Ed25519, escribe 300 muestras de GPS
perfectamente encadenadas y firmadas, y el hub las acepta como buenas. La
criptografía estaba bien; faltaba la **cadena de confianza**.

## 2 · Las cuatro comprobaciones

`verificar_serie_de_flota(serie, certificado, raiz_pub, bloque)`:

1. **El certificado lo emitió mi raíz** — si no, el barco no es de mi flota.
2. **La serie es coherente** — cadena de hashes sin huecos.
3. **El certificado habla de ESTE nodo** — si el certificado es de BARCO-A pero
   los hechos dicen BARCO-B, fuera.
4. **Los sellos de bloque** — verificados con la clave del certificado.

## 3 · Resultado de los tests

```
[OK] barco de MI flota                    -> bitacora aceptada (3 sellos)
[OK] barco de OTRA flota                  -> rechazado: no pertenece a la flota
[OK] impostor con certificado prestado    -> rechazado: el hecho es de BARCO-Z
                                             pero el certificado es de BARCO-A
[OK] certificado con el nombre cambiado   -> rechazado: no pertenece a la flota
[OK] barco de la flota suplantando a otro -> rechazado: el hecho es de BARCO-A
                                             pero el certificado es de BARCO-B
```

## 4 · El agujero que faltaba cerrar (comprobación 3)

La comprobación 3 **no estaba prevista y resultó imprescindible**.

Un barco con certificado válido podía firmar hechos **a nombre de otro barco**.
Técnicamente su firma verifica: es una clave de la flota y firmó correctamente.
El problema es que los hechos decían `BARCO-B` cuando quien firmaba era `BARCO-A`.

Sin esa comprobación, cualquier barco de la flota puede **escribir en la bitácora
de otro**. En un contexto marítimo eso significa que un barco puede falsear la
posición de otro barco de su armador.

Ahora se rechaza con un mensaje explícito que dice qué nodo firmó y qué nodo
consta en el certificado.

## 5 · Flujo completo verificado

```
barco escribe 300 muestras en LMDB
  → firma los sellos con su clave
  → el hub las lee
  → verifica la flota (3 pasos)
  → SOLO SI verifica, las guarda en su LMDB
  → 300 de 300 en el hub
```

Y el certificado sobrevive al viaje por texto plano (`armador|barco|clave|firma`),
que es como se transmitiría en una conexión real.

## 6 · Estado del conjunto

| Pieza | Estado |
|---|---|
| Firma Ed25519 real | ✅ |
| Perfil desde fichero (4 perfiles) | ✅ |
| Persistencia LMDB | ✅ sobrevive al reinicio |
| Transporte por `lumen-znet` | ✅ 500 mensajes verificados |
| Doble defensa (cadena + sello) | ✅ probadas por separado |
| Idempotencia | ✅ |
| **Verificación de flota** | ✅ **5 casos, incluida suplantación** |

**173 tests, todos verdes.**

## 7 · Lo que queda

1. **Compactación sobre disco.** Probada en el prototipo Python, no en LMDB.
2. **Split-brain.** Dos hubs aceptando escrituras durante una partición. Ni
   probado ni diseñado.
3. **Transporte real por QUIC.** Hoy los mensajes se construyen y se pasan en
   memoria; el protocolo está probado pero no viaja por un socket real en el E2E.
4. **Réplica parcial.** Un enjambre de 1.000 drones no puede replicar todo a todos.
