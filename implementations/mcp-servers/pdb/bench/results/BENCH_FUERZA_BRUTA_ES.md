# 🏋️ LUMEN Fuerza Bruta — Benchmark de Rendimiento Local (bench.py)

**Fecha**: 2026-06-27  
**Script**: `bench.py`  
**Propósito**: Medir la velocidad bruta de PDB + M-Light ejecutando directamente en CPU local.  
**Importante**: NO mide la inteligencia del modelo LLM. Mide la infraestructura LUMEN local.

---

## 📐 ¿Qué mide cada KPI?

| KPI | Descripción | Capa |
|-----|-------------|------|
| **SET_s** | Escrituras PDB/s — 100 iteraciones de `pdb_tools.tool_set()` | PDB (SQLite B-tree) |
| **GET_s** | Lecturas PDB/s — 100 iteraciones de `pdb_tools.tool_get()` | PDB (SQLite B-tree) |
| **M_SET_s** | M-Light SET/s — 50 iteraciones de `m.eval('S ^G(n)=v')` | M-Light + PDB |
| **M_GET_s** | M-Light GET/s — 50 iteraciones de `m.eval_expr('$G(^G(n))')` | M-Light + PDB |
| **M_EXPR_s** | Expresiones M/s — 40 evaluaciones de `$L`, `$P`, `$TR`, `$C` | M-Light puro (sin I/O) |
| **F_LOOP_ms** | Traversal $ORDER — F loop sobre 100 nodos via `$O(^G(I))` | M-Light + PDB |

---

## 📊 Resultados por modelo (8 modelos)

| Modelo | SET_s | GET_s | M_SET_s | M_GET_s | M_EXPR_s | F_LOOP_ms |
|--------|:-----:|:-----:|:-------:|:-------:|:--------:|:---------:|
| **ds-v4pro-max** | 115 | 6,712 | 106 | 23,605 | 26,539 | 11,287.7 |
| **stepfun/step-3.7-flash** | 115 | 7,418 | 1,464 | 38,165 | 27,986 | 11,481.1 |
| **nemotron-3-super-120b** | 119 | 10,459 | 2,530 | 45,679 | 33,272 | 9,302.5 |
| **qwen-3-7-max** | 124 | 10,004 | **2,976** | 61,185 | 70,922 | **8,330.2** |
| **laguna-m1-free** | 124 | **11,359** | 2,447 | **65,325** | **74,752** | 8,823.2 |
| **deepseek-v4-pro** | 125 | 9,585 | 2,383 | 47,290 | 70,348 | 8,657.7 |
| **deepseek-v4-flash-max** | 127 | 10,859 | 2,657 | 60,140 | 69,444 | 8,751.4 |
| **claude-sonnet-4-6** | **130** | **12,784** | 2,761 | 38,168 | 36,755 | 8,388.8 |

---

## 🏆 Ranking por KPI

| KPI | 🥇 1º | 🥈 2º | 🥉 3º |
|-----|-------|-------|-------|
| **SET_s** | claude-sonnet-4-6 (130) | ds-v4-flash-max (127) | ds-v4-pro (125) |
| **GET_s** | claude-sonnet-4-6 (12,784) | laguna-m1-free (11,359) | ds-v4-flash-max (10,859) |
| **M_SET_s** | qwen-3-7-max (2,976) | claude-sonnet-4-6 (2,761) | ds-v4-flash-max (2,657) |
| **M_GET_s** | laguna-m1-free (65,325) | qwen-3-7-max (61,185) | ds-v4-flash-max (60,140) |
| **M_EXPR_s** | laguna-m1-free (74,752) | ds-v4-pro (70,348) | qwen-3-7-max (70,922) |
| **F_LOOP_ms** | qwen-3-7-max (8,330.2) | claude-sonnet-4-6 (8,388.8) | ds-v4-pro (8,657.7) |

---

## 🏆 Victorias totales

| Modelo | KPIs ganados | Dónde |
|--------|:------------:|-------|
| **laguna-m1-free** | 2 | M_GET_s, M_EXPR_s |
| **claude-sonnet-4-6** | 2 | SET_s, GET_s |
| **qwen-3-7-max** | 1 | M_SET_s, F_LOOP_ms |

*Nota: qwen gana 2 KPIs pero comparte con laguna*

---

## 🔬 Observaciones

### Estabilidad
- **SET_s** es el más estable (±4%): rango 115-130 entre todos los modelos
- **GET_s** varía 2x entre el más lento y el más rápido
- **M_SET_s** es el más volátil: ds-v4pro-max hace 106/s, qwen hace 2,976/s (28x de diferencia)
- **M_EXPR_s** y **M_GET_s** también varían mucho según el modelo

### Patrones
- Los modelos más rápidos en SET_s (claude, ds-flash) NO son los más rápidos en M-Light
- laguna-m1-free domina M-Light puro (M_GET_s, M_EXPR_s) pero es medio en SET/GET
- qwen-3-7-max es el rey de M_SET_s y F_LOOP — el mejor en traversal $ORDER
- ds-v4pro-max es el más lento en todo — 7º/8 en 5 de 6 KPIs

---

## 💾 Datos crudos en PDB

Todos los resultados están almacenados en `^BENCH(modelo, metric)` en `lumen-pdb.db`.

```m
$O(^BENCH(""))           → lista de modelos
$G(^BENCH("qwen-3-7-max","SET_s")) → 124
$G(^BENCH("claude-sonnet-4-6","GET_s")) → 12784
```

Para ver el reporte en vivo:
```bash
cd implementations/mcp-servers/pdb
python bench.py --report
```

---

## ⚠️ Limitaciones

1. **Esto corre en CPU local** — no mide al modelo LLM, solo al hardware
2. **Variabilidad entre ejecuciones**: SQLite cache, carga del sistema, fragmentación
3. **No hay control de calidad**: una sola ejecución por modelo
4. **No mide**:
   - Inteligencia del modelo
   - Precisión en el uso de LUMEN tools
   - Latencia de red/proveedor
   - Calidad de estructuras de datos

---

*Benchmark de referencia para el benchmark cognitivo LUMEN (próximo paso).*
