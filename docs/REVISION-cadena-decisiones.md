# Revisión de la cadena de decisiones — Poli, Astrid, Smith y Zalo

**Fecha:** 2026-10-19 · **Consultados:** Poli (`:8082 /v1/chat`), modo **Astrid** (evidencia registrada) y
modo **Creative**; **Smith** (síntesis multi-perspectiva); **Zalo** (KB del ecosistema).
**Método:** mensajes cortos sin acentos (el DLL rompe con UTF-8). **Toda cifra de Poli verificada** con
una segunda consulta independiente antes de darla por buena.

---

## Veredicto de la revisión: **la cadena está mal ordenada**

Las cuatro decisiones (`P0-1` → `host agéntico` → `transporte` → `consulta Zalo`) tienen un problema de
**orden**, no de contenido. Y ninguna de las tres fuentes coincidió con el orden propuesto.

### El orden que propuse

```
P0-1 (podar) → MVM host agéntico → transporte QUIC → Zalo ratifica
```

### El orden que devuelven las tres fuentes

| # | paso | quién lo pide |
|---|---|---|
| **0** | **Zalo pre-ratifica CRITERIOS**, no resultado | Smith |
| **1** | **Reconciliar las 5 cifras de agentes** | Astrid (bloqueante) |
| **2** | **Baseline + grafo de tools** (no solo frecuencia) | Astrid + Smith |
| **3** | **ADR/spike del host agéntico** | Smith |
| **4** | **Podar en olas reversibles** (alias, shadow, flags) | Smith |
| **5** | **Contrato frame v0 + QUIC en paralelo** | Smith |
| **6** | **Certificado de pureza ACOTADO** | Creative + Smith |
| **7** | **Freeze final + ratificación** | todas |

---

## 1. El hallazgo bloqueante (Astrid, verificado)

> *"No puedo criticar el contenido de los 4 docs: no están registrados. No existe en la evidencia: 117 ni 52
> tools. `^SYS(MCP)` sólo tiene type=http y url de 5 servers. **Cero telemetría por tool.**"*

**Sin telemetría, la poda 117→52 es un acto de fe, no de arquitectura.** Mi propuesta usaba el uso real
*del estudio del Asus* — un agente, una máquina, una semana. Eso no es telemetría del sistema.

Y hay una contradicción que yo mismo señalé y no apliqué: **P0-2 (telemetría) estaba en el backlog y lo
puse por detrás de P0-1.** Astrid lo detecta: *"podar sin prerrequisito de medición rompe consumidores de
forma invisible y no falsificable"*.

## 2. Las cinco cifras de agentes (verificado dos veces)

| Fuente | Valor |
|---|---|
| `^MVM(agents)` | **8** |
| `^MVM(api) agent_count` | **7** |
| `^MVM(api) agents_count` | **4** |
| `^ANGI(metrics,agents_online)` | **12** |
| `^MVM(router) agents` | **2** |

> *"Entregarle autoridad de host agéntico a un componente cuya propia contabilidad de huéspedes se
> contradice dentro del mismo nodo es riesgo de gobernanza, no de performance. **El host no sabe a quién
> hospeda.**"*

**Confirmado en dos consultas independientes.** Es real y no lo había visto.

**Smith añade el matiz que lo hace más grave:**
> *"Las 5 cifras no son 5 números: son **5 ontologías**. Agente ≠ proceso ≠ sesión ≠ bot ≠ tool caller.
> Reconciliar es definir identidad, no sumar."*

## 3. No hay sustrato para el transporte entre nodos

| Verificado | Resultado |
|---|---|
| `^SPACE` | **3 espacios, los 3 en loopback** (`127.0.0.1:9100/9102/9104`) |
| `^BIND` | **no existe** |
| `^VIRTUAL` | **no existe** |

> *"La decisión 3 (transporte entre nodos) no tiene capa de descubrimiento sobre la cual operar. Es una
> decisión sin prerequisito."*

**Se está decidiendo el wire format para nodos que no existen todavía.** Zalo ratificó `frame.rs` — pero Zalo
ratifica contra su KB, no contra un despliegue multi-nodo real.

## 4. La disputa que aporta más valor: Astrid vs Creative sobre el freeze

**Astrid (evidencia):**
> *"Canonización invertida. Se congela el wire format sin una sola instancia productiva que lo valide. Si el
> frame se congela primero, la poda y el re-scope del host se vuelven breaking changes. **Es la decisión más
> cara de revertir y está puesta como última — pero opera como primera.**"*

**Creative (dispara):**
> *"Discrepo: congelar `frame.rs` es barato y reversible; lo caro e irreversible es el **certificado de
> pureza** que emite. […] El riesgo mayor no es el hielo, es el museo: exhibir un frame disecado como si
> fuera la película."*

**Smith resuelve el conflicto, y la resolución es mejor que las dos posturas:**
> *"Astrid tiene razón en que el freeze final va al final; pero necesita un **freeze provisional** antes. La
> diferencia es «contrato de trabajo» vs «lock irreversible»."*

**Esto es lo que se nos escapaba.** Yo planteé el canónico como una decisión binaria (sí/no). No lo es:
hay **contrato v0** (para poder medir y construir) y **freeze final** (con certificado). Separarlos desbloquea
todo sin comprometer nada.

## 5. Donde Smith corrige a las dos

> *"**frame.rs y QUIC no son una sola decisión.** El codec debe ser transport-agnostic. Si acoplas frame a
> QUIC, el certificado de pureza se vuelve imposible o carísimo."*

**Esto invalida una parte de mi propuesta de transporte.** Yo escribí *"LUMEN sobre QUIC"* como si fuera una
unidad. Son dos capas: **el codec (frame) y el transporte (QUIC)**. Acoplarlas impide certificar el codec.

## 6. El aviso sobre la poda que no había considerado

> *"**Podar por uso no es podar por valor.** Tools de bajo uso pueden ser fallback crítico, ruta de seguridad
> o long tail de tareas. La unidad de decisión es el **grafo de tareas**, no el ranking de llamadas."*

Mi whitelist de 17 se basó en "qué usa el agente del Asus". Eso es ranking de llamadas. **No es grafo de
tareas.** Y el propio estudio del Asus dice que `pattern_*`, `model_*` y `objective_*` no se usaron — pero
tampoco existía el flujo que las justifica. **Podarlas ahora cierra la puerta a un flujo que aún no se ha
probado.**

---

## 7. Correcciones concretas a los cuatro documentos

| Doc | Qué cambia |
|---|---|
| **P0-1 perfiles** | Deja de ser el paso 1. **P0-2 (telemetría) pasa delante**: sin inventario de invocaciones, la poda no es falsificable. Y el whitelist de 17 se revisa con **grafo de tareas**, no con ranking de uso |
| **MVM host agéntico** | Bloqueado por las **5 cifras**. Antes de dar autoridad de host hay que reconciliar identidad |
| **Transporte** | **Separar codec y transporte.** Contrato frame v0 ya; freeze final al final. QUIC puede arrancar en paralelo, no acoplado |
| **Consulta Zalo** | Zalo ratificó el canónico **sin instancia multi-nodo que lo valide**. La ratificación es válida como criterio, no como evidencia de producción |

## 8. Lo que esto NO cambia

- **`frame.rs` sigue siendo el canónico** (Zalo + código). Lo que cambia es **cuándo** se congela.
- **`filesystem` y `web` se quedan** (medido: 0,31 ms, 4 tools únicas, DDG gratis). Eso lo sostuve con datos
  reales de esta máquina, y ninguno de los tres consultados lo cuestionó.
- **La tesis del estudio del Asus** (el stack falla por superficie) sigue en pie. Lo que falla es mi plan
  para actuar sobre ella.

---

## Conclusión

**La cadena propuesta tenía el orden invertido en dos ejes**, y las tres fuentes coinciden en señalarlo aunque
discrepen en el detalle:

1. **Medir antes de podar** — y yo tenía la telemetría en el backlog, detrás de la poda.
2. **Reconciliar identidad antes de dar autoridad de host** — cinco cifras contradictorias en el mismo nodo.
3. **Separar contrato de freeze** — ni congelar ya (Astrid) ni dejarlo para el final sin contrato (mi plan).
4. **Separar codec de transporte** — acoplarlos hace imposible certificar el codec.

**El próximo paso real no es escribir código: es P0-2 (telemetría por tool).** Es la pieza que hoy no existe,
que desbloquea la poda con datos y que además es la entrada para reconciliar las 5 cifras. Es la única de todo
el backlog que es **prerrequisito de las demás**.
