# Arquitectura de sitios — las tres capas

> Decidido el 22-nov-2026 por Gonzalo. Sustituye la sección 3 del brief anterior.

## Las tres capas, de abajo arriba

| Capa | Sitio | Qué hace | Tono |
|---|---|---|---|
| **Motor** | `lumen-protocol.cadences.app` | **La oficial.** Documentación, protocolo, cómo se usa | Proyecto abierto. Explica, no vende |
| **Producto** | `lumen.cadences.app` | Demo y presentación de Cadences | "Una forma de verlo". Muestra |
| **Plataforma** | `ecos.cadenceslab.com` | ECOS, la capa superior | Vende |

### Por qué `.app` y no `.com`
- **`.com` vende** — es el dominio comercial del grupo (cadenceslab.com).
- **`.app` muestra** — es donde vive lo técnico y lo demostrable.

Por eso la web oficial del protocolo va en `cadences.app`: es documentación
técnica, no escaparate comercial. Aunque cadences.app también tenga productos,
el registro de esta página es "proyecto".

### La frontera LUMEN / ECOS
**Se queda como está.** No se mueve nada. Decisión explícita de Gonzalo: no es
el momento de redefinir qué se libera. La web del protocolo documenta lo que ya
es público (el repo `lumen-protocol`, MIT); no anuncia liberaciones futuras.

## Idioma

**Ambos, todo traducido.** Inglés como referencia (es el idioma del README y del
código), español completo al lado.

Implementación: selector EN/ES en la cabecera, mismo contenido en ambos.
- Rutas: `/` (inglés) y `/es/` (español).
- El contenido vive en un solo sitio y se traduce; no dos webs paralelas.
- Los docs de `docs/` que estén solo en español hay que traducirlos al inglés
  (empezando por `CASOS_USO_AGENTES.md`, que es el que el README ya enlaza).

## Qué NO va en lumen-protocol.cadences.app
- Chat con agentes en vivo → eso es `ecos.cadenceslab.com`.
- Tono comercial, superlativos, comparativas con otros frameworks.

## Relación entre sitios
- `lumen-protocol` es la referencia técnica. Enlaza a la demo.
- `lumen` es la demo. Enlaza a la documentación.
- `ecos` es la plataforma. No se menciona desde el protocolo salvo como
  "implementación".
