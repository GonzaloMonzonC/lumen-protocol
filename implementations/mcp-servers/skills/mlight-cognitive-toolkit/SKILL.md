---
name: mlight-cognitive-toolkit
description: "M-Light como sistema operativo cognitivo. Patrones M reutilizables, M-Light + Thinking combinados, triggers para automatizacion. Requiere pdb-kv + pdb-enterprise."
version: 1.1.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, m-light, pdb, cognition, mumps, patterns, composition]
---

# 🧠 M-Light Cognitive Toolkit

M-Light es el shell script de tu cerebro LUMEN. Este skill asume que ya tienes `pdb-kv` y `pdb-enterprise` cargados. Para MVM, carga `pdb-mvm`.

---

## 📚 M-Code Pattern Library

### Traversal (el alma de M)
```
F  S I=$O(^ns(I)) Q:I=""  S V=$G(^ns(I,"field"))
F  S I=$O(^ns(I),-1) Q:I=""                   ; al reves
```

### Filtro con Condicion
```
F  S I=$O(^ns(I)) Q:I=""  I $G(^ns(I,"pop"))>N  W $G(^ns(I,"name")),!
```

### Agregacion
```
S total=0 F  S I=$O(^ns(I)) Q:I=""  S total=total+1
S suma=0 F  S I=$O(^ns(I)) Q:I=""  S suma=suma+$G(^ns(I,"val"))
```

### Naked Reference (^(campo) -> ultimo global)
```
F  S I=$O(^ns(I)) Q:I=""  I ^(I,"pop")>N  W $G(^ns(I,"name")),": ",^(I,"pop"),!
```

### Copiar entre namespaces
```
F  S I=$O(^SRC(I)) Q:I=""  S ^DST(I,"name")=$G(^SRC(I,"name"))
```

---

## 🔗 M-Light + Thinking Combinados

### Pattern: Data-Driven Decision
```
1. web_extract(url) -> obtener datos
2. pdb_set via M-Light -> estructurar en ^DATA
3. F  S I=$O(^DATA(I)) -> analizar con M-Light
4. decision_log(conclusion) -> persistir
5. pattern_record(patron) -> aprendizaje institucional
```

### Pattern: Objective Verification
```
Cuando un objective esta en TESTING:
1. Cargar criterios en ^CRITERIA
2. Verificar con M-Light (contar, comparar, filtrar)
3. Si OK -> objective_judge(mark_done=true)
4. Si FAIL -> crear tarea en kanban
```

---

## ⚡ Triggers para Automatizacion

```
pdb_trigger_define("AGENT", "ON_SET", "LOG", {"dest_ns":"AUDIT_LOG"})
```

Registra automaticamente cada cambio en ^AGENT en ^AUDIT_LOG.

---

## 🎯 M-Light vs Python

| Escenario | M-Light | Python |
|:----------|:-------:|:------:|
| Recorrer arboles jerarquicos | ✅ $ORDER imbatible | ❌ Codigo verboso |
| Guardar en PDB | ✅ `S ^ns(subs)=val` | ✅ `pdb_set(...)` tambien |
| Triggers/automatizacion | ✅ ON SET/ON KILL | ❌ No disponible |
| Computacion numerica pesada | ❌ | ✅ NumPy/Pandas |

---

## 📝 Pitfalls

- Variables no inicializadas -> `""`. Usa `S I=""` antes de `$O`
- Naked reference sin contexto: `^(subs)` solo funciona tras un ^GLOBAL
- Strings con comas en WRITE: se separan a depth=0
- journal_mode DELETE: ya no hay .shm/.wal que limpiar
