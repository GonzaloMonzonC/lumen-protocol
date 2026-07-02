import sys, os, tempfile
sys.path.insert(0, '.')
import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', 'pdb_tools.py')
pdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb)

# Clear old CRON
pdb.tool_kill({'ns': 'CRON', 'subs': []})
pdb.tool_kill({'ns': 'CRON_RES', 'subs': []})
print('CRON cleared')

import mvm
vm = mvm.MVM(pdb)

tmp = os.path.join(tempfile.gettempdir(), 'mvm_clean_test.txt')
tmp_fwd = tmp.replace('\\', '/')
code = 'O 5:"' + tmp_fwd + '"\nU 5\nW "hello MVM!"\nC 5\nU 0\nW "console"'
print(f'Code: {code}')

pid = vm.spawn(code, name='clean_test')
vm.tick_all(15)

print(f'File exists: {os.path.exists(tmp)}')
if os.path.exists(tmp):
    with open(tmp) as f:
        print(f'Content: [{f.read()}]')
    os.unlink(tmp)
else:
    print('FILE NOT CREATED')
