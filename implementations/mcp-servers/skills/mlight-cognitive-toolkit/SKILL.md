---
name: mlight-cognitive-toolkit
description: M-Light como sistema operativo cognitivo — patrones M reutilizables, PDB como memoria del agente, M-Light + Thinking combinados, triggers para automatización, y workflows de análisis de datos con $ORDER.
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, m-light, pdb, cognition, mumps, patterns]
---

# 🧠 M-Light Cognitive Toolkit

M-Light no es solo un lenguaje de consulta — es el **shell script de tu cerebro LUMEN**. Este skill te enseña a usar código M para potenciar tu cognición, combinando PDB (memoria), Thinking (razonamiento), y Kanban (planificación).

---

## 📚 M-Code Pattern Library

Guarda estos fragmentos en `^PATTERNS(id, campo)` para reutilizarlos:

### Traversal (el alma de M)
```
F  S I=$O(^ns(I)) Q:I=""  S V=$G(^ns(I,"field"))  ; recorrer todo
F  S I=$O(^ns(I),-1) Q:I=""  ; recorrer al revés
```

### Filtro con Condición
```
F  S I=$O(^ns(I)) Q:I=""  I $G(^ns(I,"pop"))>N  W $G(^ns(I,"name")),!
```

### Agregación (contar, sumar)
```
S total=0 F  S I=$O(^ns(I)) Q:I=""  S total=total+1
S suma=0 F  S I=$O(^ns(I)) Q:I=""  S suma=suma+$G(^ns(I,"val"))
```

### Naked Reference (^(campo) → último global)
```
F  S I=$O(^ns(I)) Q:I=""  I ^(I,"pop")>N  W $G(^ns(I,"name")),": ",^(I,"pop"),!
```

### Copiar/Migrar entre namespaces
```
F  S I=$O(^SRC(I)) Q:I=""  S ^DST(I,"name")=$G(^SRC(I,"name"))
```

---

## 🧠 PDB como Memoria Cognitiva

Usa estos namespaces para persistir el estado de tu razonamiento:

```
^AGENT("sessions", id, "topic")
^AGENT("sessions", id, "decisions")
^AGENT("patterns", id, "code")       ; M patterns guardados
^AGENT("patterns", id, "uses")        ; contador de reutilización
^AGENT("checklist", type, item)       ; ^CHECKLIST(session_start, item)
^AGENT("work_log", work_id, "status") ; tracking multi-sesión
```

---

## 🔗 M-Light + Thinking Combinados

### Pattern: "Data-Driven Decision"
```
1. web_extract(url) → obtener datos
2. pdb_set vía M-Light → estructurar en ^DATA
3. F  S I=$O(^DATA(I)) → analizar con M-Light
4. decision_log(conclusión) → persistir la decisión
5. pattern_record(patrón descubierto) → aprendizaje institucional
```

### Pattern: "Audit de Código con M-Light"
```
1. search_files(pattern) → encontrar archivos
2. read_file(path) → leer contenido
3. pdb_set vía M-Light → guardar métricas en ^AUDIT
4. F  S I=$O(^AUDIT(I)) W $G(^AUDIT(I,"file")),! → reporte
5. wiki_create → documentar hallazgos
```

### Pattern: "Objective Verification con M-Light"
```
Cuando un objective alcanza TESTING:
1. Cargar acceptance criteria en ^CRITERIA
2. Ejecutar verificaciones con M-Light
3. Si todos pasan → objective_judge(mark_done=true)
4. Si alguno falla → crear tarea de fix en kanban
```

---

## ⚡ Triggers para Automatización Cognitiva

```
pdb_trigger_define(
  ns="AGENT",
  event="ON_SET",
  trigger_id="log_change",
  action="LOG",
  params={"dest_ns": "AUDIT_LOG", "include_value": true}
)
```

Esto registra automáticamente cada cambio en ^AGENT en ^AUDIT_LOG. Ideal para debugging de sesiones.

---

## 📊 Workflows de Análisis con M-Light

### Ejemplo 1: Auditoría de Documentación
```python
# Guardar datos del audit
for i, finding in enumerate(findings, 1):
    m.eval(f'S ^AUDIT({i},"file")="{finding.file}" S ^AUDIT({i},"before")="{finding.before}" S ^AUDIT({i},"after")="{finding.after}"')

# Query con M-Light
m.eval('S I="" F  S I=$O(^AUDIT(I)) Q:I=""  W $G(^AUDIT(I,"file")),": ",$G(^AUDIT(I,"before"))," -> ",$G(^AUDIT(I,"after")),!')
```

### Ejemplo 2: Benchmark con PDB + M-Light
```
1. pdb_set para cada operación de benchmark
2. F  S I=$O(^BENCH(I)) → recuperar resultados
3. sequential_thinking → analizar bottlenecks
4. wiki_create → documentar hallazgos
```

### Ejemplo 3: Análisis de Sesiones
```
F  S id=$O(^AGENT("sessions",id)) Q:id=""  D
. W "Sesión ",id,": ",$G(^AGENT("sessions",id,"topic")),!
. S d="" F  S d=$O(^AGENT("sessions",id,"decisions",d)) Q:d=""  W "  - ",$G(^(d)),!
```

---

## 🎯 Cuándo Usar M-Light vs Python

| Escenario | M-Light | Python |
|:----------|:-------:|:------:|
| Recorrer árboles jerárquicos | ✅ `$ORDER` es imbatible | ❌ Código verboso |
| Computación numérica pesada | ❌ No es su fuerte | ✅ NumPy/Pandas |
| Filtrar datos con condiciones | ✅ Una línea con `I cond` | ✅ También fácil |
| Guardar en PDB | ✅ `S ^ns(subs)=val` nativo | ✅ `pdb_set(...)` también |
| Triggers/automatización | ✅ ON SET/ON KILL | ❌ No disponible |
| Interactuar con LLM | ✅ `sequential_thinking` | ❌ No disponible |

---

## 🚀 Quick Start

```python
# 1. Cargar el skill
skill_view(name='mlight-cognitive-toolkit')

# 2. Crear tu primer patrón M
m = MEvaluator(pdb_tools)
m.eval('S ^PATTERNS(1,"name")="Traversal basico" S ^PATTERNS(1,"code")="F  S I=$O(^ns(I)) Q:I=\"\" "')

# 3. Usar el patrón
m.eval('S I="" F  S I=$O(^ns(I)) Q:I=""  W $G(^ns(I,"name")),!')
```

---

## 📝 Pitfalls

- **No inicializar variables**: en M, una variable no definida es `""`. Usa `S I=""` antes de `$O`.
- **Naked reference sin contexto**: `^(subs)` solo funciona si hubo un `^GLOBAL` antes.
- **Strings con comas en WRITE**: separa los items de `W` a depth=0 (respetando paréntesis).
- **Journal mode DELETE**: PDB ya no usa WAL. No hay archivos `.shm`/`.wal` que limpiar.
