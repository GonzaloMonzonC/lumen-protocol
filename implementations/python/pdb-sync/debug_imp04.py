"""Debug imp04 test."""
import sys
sys.path.insert(0, sys.path[0])  # current dir

from m_routines import RoutineExecutor, register
import inspect
print('m_routines path:', inspect.getfile(RoutineExecutor))

register('DOTEST', 'D SUB\nQ\nSUB\nS val=99\nQ')
executor = RoutineExecutor()
r = executor.exec('DOTEST')
print('val:', r.get("vars", {}).get("val", "NOT FOUND"))
