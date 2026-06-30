"""Scan lumen-protocol and generate FS batch for PDB."""
import os, json

root = 'C:/Users/gonzalo/Documents/GitHub/lumen-protocol'
batch = []

total_files = 0
total_dirs = 0
total_size = 0

for dirpath, dirs, files in os.walk(root):
    rel_dir = os.path.relpath(dirpath, root)
    if rel_dir == '.':
        rel_dir = '(root)'
    rel_dir = rel_dir.replace('\\', '/')
    
    for f in files:
        fp = os.path.join(dirpath, f)
        try:
            sz = os.path.getsize(fp)
            rel_path = os.path.join(rel_dir, f).replace('\\', '/')
            if rel_path.startswith('(root)/'):
                rel_path = rel_path[6:]
            ext = os.path.splitext(f)[1].lower() or '(none)'
            
            total_files += 1
            total_size += sz
            
            # By extension: ^FS('ext', ext, path) = size
            batch.append({'ns': 'FS', 'subs': ['ext', ext, rel_path], 'value': str(sz)})
            
            # By directory: ^FS('dir', rel_dir, path) = size
            batch.append({'ns': 'FS', 'subs': ['dir', rel_dir, rel_path], 'value': str(sz)})
            
            # File metadata
            batch.append({'ns': 'FS', 'subs': ['file', rel_path, 'size'], 'value': str(sz)})
            batch.append({'ns': 'FS', 'subs': ['file', rel_path, 'ext'], 'value': ext})
            batch.append({'ns': 'FS', 'subs': ['file', rel_path, 'dir'], 'value': rel_dir})
            
        except:
            pass

# Meta
batch.append({'ns': 'FS', 'subs': ['meta', 'total_files'], 'value': str(total_files)})
batch.append({'ns': 'FS', 'subs': ['meta', 'total_dirs'], 'value': str(total_dirs)})
batch.append({'ns': 'FS', 'subs': ['meta', 'total_size'], 'value': str(total_size)})

print(f'Files: {total_files}')
print(f'Dirs: {total_dirs}')
print(f'Size: {total_size} bytes ({total_size/1024/1024:.1f} MB)')
print(f'Batch items: {len(batch)}')

out = 'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/bench-results/fs_batch.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(batch, f, ensure_ascii=False)
print(f'Saved: {out}')
