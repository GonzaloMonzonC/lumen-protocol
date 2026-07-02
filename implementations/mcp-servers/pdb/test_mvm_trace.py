import sys, os, tempfile
sys.path.insert(0, '.')
import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', 'pdb_tools.py')
pdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb)

import mvm
from m_light import MEvaluator

# Monkey-patch evaluator write
orig_write = MEvaluator._exec_write
def debug_write(self, line, pos):
    print(f'  [EVAL WRITE] io={self._current_io} dm={self._device_manager is not None}')
    if self._device_manager:
        dev = self._device_manager.devices.get(self._current_io)
        if dev:
            print(f'    device={dev.name} is_open={dev.is_open}')
    return orig_write(self, line, pos)
MEvaluator._exec_write = debug_write

vm = mvm.MVM(pdb)
tmp = os.path.join(tempfile.gettempdir(), 'mvm_trace.txt').replace('\\', '/')
print(f'Path: {tmp}')
code = 'O 5:"' + tmp + '"\nU 5\nW "hello from MVM"\nC 5'
print(f'Code: {code}')
pid = vm.spawn(code, name='trace')
vm.tick_all(10)

print(f'File exists: {os.path.exists(tmp)}')
if os.path.exists(tmp):
    with open(tmp) as f:
        c = f.read()
        print(f'Content ({len(c)} chars): {c}')
    os.unlink(tmp)
