Ejecuta el benchmark de LUMEN para este modelo. Sigue estos pasos exactamente:

1. Carga los skills necesarios:
   skill_view('pdb-kv')
   skill_view('mlight-cognitive-toolkit')

2. Ejecuta el benchmark desde terminal:
   cd C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb
   python bench.py [nombre-del-modelo]

   Sustituye [nombre-del-modelo] por el nombre del modelo que estás usando ahora mismo (ej: nous-free, claude-sonnet-4, etc.)

3. Cuando termine, ejecuta esto para ver la comparación:
   python bench.py --report

4. Dime los resultados. No hace falta que analices nada — solo ejecuta los comandos y muéstrame lo que sale.

Importante:
- Usa exactamente el mismo nombre de modelo que ves en tu configuración
- Si el script da error, dímelo y no intentes arreglarlo tú
- No modifiques el archivo bench.py
