import sys, os, tempfile
sys.path.insert(0, '.')
import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', 'pdb_tools.py')
pdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb)

import mvm
from mvm import FileDevice

# Monkey-patch FileDevice.open
orig_open = FileDevice.open
def debug_open(self, params=''):
    result = orig_open(self, params)
    print(f'  [FileDevice.open] params={params!r} result={result} is_open={self.is_open} path={self._filepath!r}')
    return result
FileDevice.open = debug_open

# Monkey-patch write
orig_write = FileDevice.write
def debug_write(self, data):
    print(f'  [FileDevice.write] is_open={self.is_open} data={data!r}')
    return orig_write(self, data)
FileDevice.write = debug_write

vm = mvm.MVM(pdb)

tmp = os.path.join(tempfile.gettempdir(), 'mvm_final_test.txt').replace('\\', '/')
print(f'Target: {tmp}')

code = 'O 5:"' + tmp + '"\nU 5\nW "hello from MVM"\nC 5'
print(f'Code: {code}')

pid = vm.spawn(code, name='io_test')
vm.tick_all(10)

# Also try standalone
print('\n--- Standalone test ---')
fd = FileDevice()
fd.open('w ' + tmp)
fd.write('standalone test')
fd.close()

print(f'\nFile exists: {os.path.exists(tmp)}')
if os.path.exists(tmp):
    with open(tmp) as f:
        print(f'Content: {f.read()}')
    os.unlink(tmp)
