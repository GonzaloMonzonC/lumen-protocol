# MSM→Lumen: Catálogo de rutinas MSM disponibles

> Generado por `rut_parser.py` desde MGR301208.RUT (481 rutinas, 72K líneas)
> Fecha: 2026-07-12

## 📊 Por categoría

| Categoría | Rutinas | Estado |
|:---------:|:-------:|:------:|
| JRNL (Journaling) | 101 | ✅ A1-A4 completados |
| DDP (Distributed) | 109 | ✅ B1-B3 completados |
| JOB (Procesos) | 160 | ✅ C1-C3 completados |
| CONFIG (Sistema) | 254 | 📥 Parcial (STU1-2 cargados) |
| ERROR (Errores) | 234 | ✅ %ET adaptado |
| LOCK (Bloqueos) | 46 | 📥 Pendiente revisión |
| GLOBAL (Globals) | 27 | 📥 %GCMP pendiente |
| Z-FUNC (Funciones) | 6 | 📥 Pendiente revisión |

## 📋 Tareas pendientes (MSM-01 a MSM-06)

Ver kanban en niche_46 (msm-to-lumen-planning).

## 🛠️ Herramienta

`rut_parser.py` — Parser de ficheros .RUT (routine save) de MSM.
```bash
python rut_parser.py MGR301208.RUT --categories
python rut_parser.py MGR301208.RUT --list
python rut_parser.py MGR301208.RUT --search JRNL
python rut_parser.py MGR301208.RUT --info BIJ
```
