#!/usr/bin/env python3
"""SHM 10K benchmark."""
import sys, os, time, subprocess, json
sys.path.insert(0, '.'); sys.path.insert(0, '..'); sys.path.insert(0, '../../python/src')
os.environ['PDB_PATH'] = '/c/tmp/shm_10k.db'

from lumen import *
proc = subprocess.Popen([sys.executable, '-u', 'server_shm.py'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)

probe = compress_value({'protocol':'LUMEN','client_name':'b','supported_versions':['1.0']})
buf=bytearray(build_size(len(probe)))
build_frame(TYPE_REQUEST,FLAG_COMPRESSED,probe,buf,0); proc.stdin.write(buf); proc.stdin.flush()
rb=bytearray()
for _ in range(2000):
    b=proc.stdout.read(1)
    if not b: break
    rb.extend(b); r=parse_frame(rb,0)
    if isinstance(r,ParseComplete):
        ack=decompress_value(r.frame.payload) if r.frame.flags & FLAG_COMPRESSED else r.frame.payload; break

time.sleep(0.1)
region=ShmRegion.open(ack['shm_region'],ack['shm_size']); region.validate()
wr=region.ring_buffer(RingSide.A); rr=region.ring_buffer(RingSide.B)
tp=ShmTransport(wr,rr)

req_id=[100]
def call(meth,args):
    req_id[0]+=1
    msg=compress_value({'jsonrpc':'2.0','id':req_id[0],'method':'tools/call','params':{'name':meth,'arguments':args}})
    b=bytearray(build_size(len(msg))); build_frame(TYPE_REQUEST,FLAG_COMPRESSED,msg,b,0)
    tp.send_frame(bytes(b))
    raw=tp.recv_frame()
    rr=parse_frame(bytearray(raw),0)
    if isinstance(rr,ParseComplete):
        return decompress_value(rr.frame.payload) if rr.frame.flags & FLAG_COMPRESSED else rr.frame.payload

# Init
req_id[0]+=1
init={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'b'}}}
msg=compress_value(init); b=bytearray(build_size(len(msg)))
build_frame(TYPE_REQUEST,FLAG_COMPRESSED,msg,b,0); tp.send_frame(bytes(b))
raw=tp.recv_frame(); r=parse_frame(bytearray(raw),0)
if isinstance(r,ParseComplete): pass

print('=== SHM 10K Benchmark ===')
N=10000

def bench(nm, fn):
    t0=time.perf_counter()
    for _ in range(N): fn()
    t=time.perf_counter()-t0
    print(f'  {nm:25s} {N:>6,} ops  {t*1000:>8.1f}ms  {t/N*1e6:>6.1f}us/op')

bench('SET single', lambda: call('pdb_set',{'ns':'B','subs':[0],'value':'x'}))
bench('GET', lambda: call('pdb_get',{'ns':'B','subs':[0]}))
bench('$DATA', lambda: call('pdb_data',{'ns':'B','subs':[0]}))
bench('$INCREMENT', lambda: call('pdb_incr',{'ns':'C','subs':['x'],'increment':1}))
bench('SET 3-level', lambda: call('pdb_set',{'ns':'D','subs':[1,'name'],'value':'u'}))

proc.terminate()
print('DONE')
