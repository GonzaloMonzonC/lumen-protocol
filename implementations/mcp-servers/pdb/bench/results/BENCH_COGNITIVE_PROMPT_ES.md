# 🧠 LUMEN Benchmark Cognitivo — Prompt Estandarizado

> ⚠️ **Antes de empezar**: reemplaza `{MODEL_NAME}` por el nombre real del modelo (ej. `claude-sonnet-4-6`, `qwen-3-7-max`, `laguna-m1-free`)

Tu nombre de modelo es: **{MODEL_NAME}**

Estás participando en el LUMEN Cognitive Benchmark. Este benchmark mide cómo usas las LUMEN tools (PDB, M-Light, Thinking, Wiki, Kanban) para completar tareas estructuradas.

**Reglas:**
- Usa las LUMEN tools reales por su nombre estándar (`pdb_set`, `pdb_get`, `pdb_order`, `pdb_m_eval`, `sequential_thinking`, `decision_log`, `pattern_record`, `wiki_create`, `qa_ask`, `task_create`, `task_move`, `task_link`)
- Guarda los datos de verificación en `^BENCH_MODEL({MODEL_NAME}, C, "clave")` como se indica al final de cada circuito
- NO te saltes circuitos ni inventes datos — ejecuta cada paso usando las herramientas reales
- Si una tool no está disponible en tu sesión, dilo y continúa con el siguiente circuito

---

## Circuito 1 — PDB CRUD (peso: 25%)

**Objetivo**: Crear datos jerárquicos en PDB, recorrer con $ORDER, calcular agregados.

### Pasos

1. **Crea 5 registros de clientes** usando `pdb_set`:
   ```
   ^CLIENTES(1,"nombre") = "Ana García"
   ^CLIENTES(1,"ciudad") = "Madrid"
   ^CLIENTES(1,"saldo")  = 2500

   ^CLIENTES(2,"nombre") = "Carlos López"
   ^CLIENTES(2,"ciudad") = "Barcelona"
   ^CLIENTES(2,"saldo")  = 800

   ^CLIENTES(3,"nombre") = "Elena Martínez"
   ^CLIENTES(3,"ciudad") = "Valencia"
   ^CLIENTES(3,"saldo")  = 1500

   ^CLIENTES(4,"nombre") = "David Ruiz"
   ^CLIENTES(4,"ciudad") = "Sevilla"
   ^CLIENTES(4,"saldo")  = 300

   ^CLIENTES(5,"nombre") = "Laura Torres"
   ^CLIENTES(5,"ciudad") = "Bilbao"
   ^CLIENTES(5,"saldo")  = 4200
   ```

2. **Recorre con $ORDER**: Usa `pdb_order` para iterar sobre todos los IDs de cliente y sumar sus saldos.  
   Pista: empieza con `pdb_order({'ns':'CLIENTES','subs':['']})` para obtener la primera clave.

3. **Guarda el total** en:
   ```
   ^CLIENTES("total","saldo") = <suma>
   ```

4. **Guarda datos de verificación**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',1,'total'],'value':'<suma>'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',1,'count'],'value':'5'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',1,'status'],'value':'done'})
   ```

---

## Circuito 2 — M-Light (peso: 20%)

**Objetivo**: Usar el evaluador M-Light (`pdb_m_eval`) para categorizar clientes y calcular promedios.

### Pasos

1. **Categoriza clientes** usando expresiones M-Light. Para cada cliente en `^CLIENTES`:
   - saldo > 1000 → "PREMIUM"
   - saldo > 500  → "STANDARD"
   - else         → "BASIC"

   Guarda las categorías usando `pdb_set`:
   ```
   ^CLIENTES(1,"categoria") = "PREMIUM"
   ^CLIENTES(2,"categoria") = "STANDARD"
   ^CLIENTES(3,"categoria") = "PREMIUM"
   ^CLIENTES(4,"categoria") = "BASIC"
   ^CLIENTES(5,"categoria") = "PREMIUM"
   ```

   Usa `pdb_m_eval` con `$SELECT` para determinar la categoría, por ejemplo:
   ```
   pdb_m_eval({'expression':'$S(2500>1000:"PREMIUM",2500>500:"STANDARD",1:"BASIC")'})
   ```

2. **Calcula el saldo promedio** usando M-Light:
   ```
   pdb_m_eval({'expression':'...'})
   ```
   (Calcula `<total_saldo> / <count>` usando los valores del Circuito 1)

3. **Guarda datos de verificación**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',2,'media'],'value':'<promedio>'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',2,'premium_count'],'value':'3'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',2,'status'],'value':'done'})
   ```

---

## Circuito 3 — Cognitive (peso: 20%)

**Objetivo**: Usar razonamiento estructurado, registrar decisiones y guardar patrones.

### Pasos

1. **Analiza el problema** usando `sequential_thinking`:
   > "Un cliente premium con saldo > 2000 debe recibir un descuento del 10% en su próxima compra. La cliente #5 (Laura Torres) tiene saldo 4200 y es PREMIUM."

   Razona paso a paso: elegibilidad, cálculo del descuento, impacto en el saldo total, consideraciones de implementación.

2. **Registra una decisión** usando `decision_log`:
   Registra la decisión arquitectónica sobre cómo implementar la lógica de descuento. Incluye justificación y alternativas consideradas.

3. **Guarda un patrón** usando `pattern_record`:
   Nombre: `premium-discount-audit`
   Guarda esto como un patrón reutilizable para futuras auditorías de descuentos.

4. **Guarda datos de verificación**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',3,'status'],'value':'done'})
   ```

---

## Circuito 4 — Knowledge (peso: 15%)

**Objetivo**: Documentar resultados en la base de conocimiento persistente.

### Pasos

1. **Crea una página wiki** llamada `"Benchmark Report {MODEL_NAME}"` usando `wiki_create`:
   Incluye:
   - Número de clientes: 5
   - Saldo total: `<suma del C1>`
   - Saldo promedio: `<promedio del C2>`
   - Clientes premium: 3
   - Resumen de categorización
   - Análisis de descuento del C3

2. **Registra una Q&A** usando `qa_ask`:
   - Pregunta: "¿Qué modelo genera mejores estructuras PDB?"
   - Respuesta: Resume tu enfoque para estructurar `^CLIENTES`

3. **Guarda datos de verificación**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',4,'wiki_title'],'value':'Benchmark Report {MODEL_NAME}'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',4,'qa_question'],'value':'Which model generates better PDB structures?'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',4,'status'],'value':'done'})
   ```

---

## Circuito 5 — Kanban (peso: 10%)

**Objetivo**: Organizar trabajo usando el tablero kanban.

### Pasos

1. **Crea 3 tareas** usando `task_create`:
   - "Review premium clients" (prioridad alta, tag: audit)
   - "Update discount rules" (prioridad media, tag: discounts)
   - "Audit client balances" (prioridad media, tag: audit)

2. **Mueve tareas** usando `task_move`:
   - Mueve "Review premium clients" → "In Progress"
   - Mueve "Update discount rules" → "In Progress"

3. **Enlaza la primera tarea** con el patrón del Circuito 3 usando `task_link` (si está disponible) o `task_link_url`.

4. **Guarda datos de verificación**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',5,'task_count'],'value':'3'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',5,'status'],'value':'done'})
   ```

---

## Circuito 6 — Integración (peso: 10%)

**Objetivo**: Encadenar PDB + M-Light + Cognitive en un flujo de trabajo coherente.

### Pasos

1. **Procesa a Laura Torres (cliente #5)**: es PREMIUM con saldo 4200. Aplica un descuento del 10%.

2. **Usa M-Light** para calcular el nuevo saldo:
   ```
   pdb_m_eval({'expression':'4200 * 0.9'})
   ```

3. **Actualiza PDB**:
   ```
   pdb_set({'ns':'CLIENTES','subs':[5,'saldo'],'value':3780})
   pdb_set({'ns':'CLIENTES','subs':[5,'descuento'],'value':'10%'})
   ```

4. **Documenta el cambio** en la página wiki creada en el Circuito 4 — `wiki_update` con mode=append:
   Añade una sección "Client #5 Discount Applied" con los detalles.

5. **Crea una tarea kanban** "Verify Laura discount applied" y muévela a "In Progress".

6. **Guarda un patrón** para la operación de descuento:
   Nombre: `client-discount-operation`

7. **Guarda datos de verificación**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',6,'new_balance'],'value':'3780'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',6,'status'],'value':'done'})
   ```

---

## Finalización

Una vez completados los 6 circuitos:

1. **Guarda la confirmación final**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}','total'],'value':'6'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}','complete'],'value':'1'})
   ```

2. **Reporta**: Hecho. El script judge.py evaluará ahora tus resultados.

---

*Fin del prompt del benchmark. Ejecuta los 6 circuitos en orden usando LUMEN tools.*
