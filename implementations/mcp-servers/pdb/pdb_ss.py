"""D ^%SS — PDB System Status v3.
Lee de PDB, ^ANGI, ^TOM, MVM y muestra estado real del ecosistema.

Secciones: Database · MVM · Agents · Services · Cron · Changes · Storage · System
"""
import json, time, os, sys, re

sys.path.insert(0, os.path.dirname(__file__) or '.')
import pdb_tools

def _ts(): return time.strftime("%Y-%m-%d %H:%M:%S")
def _fmt(n):
    for u in ['B','KB','MB','GB']:
        if n < 1024: return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"
def _bar(pct, w=12): return '█' * int(pct/100*w) + '░' * (w - int(pct/100*w))

def _schema():
    try:
        r = pdb_tools.tool_schema({})
        if not r or not isinstance(r, dict): return {}
        ns = r.get("namespaces", [])
        db = r.get("database", "?")
        sz = os.path.getsize(db) if os.path.exists(db) else 0
        top = sorted(ns, key=lambda n: -n.get("nodes",0))
        return {"path":db,"size":_fmt(sz),"sz":sz,"ns":len(ns),
                "nodes":sum(n.get("nodes",0) for n in ns),
                "small":len([n for n in ns if n.get("nodes",0)<=5]),
                "top":[(n.get("ns","?"),n.get("nodes",0),n.get("with_values",0)) for n in top[:12]]}
    except: return {}

def _mvm():
    try:
        r = pdb_tools.tool_mvm_list({})
        if not r: return {}
        pp = r.get("processes",[])
        test = [p for p in pp if not re.search(r'test|debug|fix|hotswap|legacy|oog|orig|promote|llm_', p.get('name',''))]
        return {"t":len(pp),"real":len(test),"test":len(pp)-len(test),
                "alive":sum(1 for p in pp if p.get('status') in ('RUNNING','READY')),
                "dead":sum(1 for p in pp if p.get('status')=='DEAD'),
                "procs":test[:8]}
    except: return {}

def _services():
    try:
        sv = []; k=""
        while True:
            r = pdb_tools.tool_order({"ns":"System","subs":["services","registry",k]})
            if r is None: break
            nk = r.get("value") if isinstance(r,dict) else r
            if not nk or nk==k: break
            k=nk
            v = pdb_tools.tool_get({"ns":"System","subs":["services","registry",k]})
            if v and v.get("success") and v.get("value"):
                d = v["value"]
                if isinstance(d,str):
                    try: d=json.loads(d)
                    except: pass
                sv.append({"name":k,"agent":d.get("agent","?") if isinstance(d,dict) else "?"})
        return sv
    except: return []

def _angi():
    try:
        from pdb_angi_workspace import angi_status, angi_list_alerts, angi_list_incidents
        s=angi_status()
        al=angi_list_alerts(unacknowledged_only=True)
        inc=angi_list_incidents(unresolved_only=True)
        return {"team":s.get("team_count",0),"decisions":s.get("decisions_count",0),
                "incidents":len(inc),"alerts":len(al),
                "crit":len([a for a in al if a.get("severity") in ("critical","high")])}
    except: return {}

def _tom():
    try:
        from pdb_tom_tracker import tom_status
        s=tom_status()
        return {"a":s.get("active",0),"ok":s.get("completed",0),"fail":s.get("failed",0),"t":s.get("total",0)}
    except: return {}

def _chron():
    try:
        import subprocess
        r = subprocess.run([sys.executable,"-m","hermes_cli.main","cron","list","--json"],
            capture_output=True,text=True,timeout=8,
            cwd=os.path.expanduser("~/AppData/Local/hermes/hermes-agent"))
        if r.returncode==0 and r.stdout:
            jobs=json.loads(r.stdout).get("jobs",[])
            return {"t":len(jobs),"a":sum(1 for j in jobs if j.get("enabled")),
                    "p":sum(1 for j in jobs if not j.get("enabled")),
                    "f":sum(1 for j in jobs if j.get("last_status")=="error"),
                    "jobs":[{"n":j.get("name","?"), "s":j.get("schedule","?"),
                             "ok":j.get("last_status")=="ok"} for j in jobs[:8]]}
    except: return {}

def _changes():
    try:
        r = pdb_tools.tool_query({"sql":"SELECT value FROM _globals WHERE ns='CHANGES' AND value!='' ORDER BY rowid DESC LIMIT 5","params":[]})
        cc=[]
        if r and isinstance(r,dict):
            for row in r.get("rows",[]):
                v=row.get("value","") if isinstance(row,dict) else row
                if isinstance(v,str):
                    try: v=json.loads(v)
                    except: pass
                if isinstance(v,dict):
                    cc.append({"ts":str(v.get("timestamp",""))[:19],"op":v.get("op","?"),"ns":v.get("ns","?")})
        return cc
    except: return []

def _health(s,m,a,t):
    sc=100; r=[]
    inc=a.get("incidents",0)
    if inc>2: sc-=min(inc*3,15); r.append(f"{inc} incidentes")
    elif inc>0: sc-=5; r.append(f"{inc} incidentes (leves)")
    if a.get("crit",0)>0: sc-=a["crit"]*10; r.append(f"{a['crit']} alertas críticas")
    if t.get("a",0)>3: sc-=t["a"]*5; r.append(f"{t['a']} tareas running")
    if t.get("fail",0)>3: sc-=t["fail"]*3; r.append(f"{t['fail']} fallos Tom")
    if s.get("sz",0)>500*1024**2: sc-=5; r.append("BD >500MB")
    return max(0,sc),r

def ss():
    s=_schema(); m=_mvm(); sv=_services(); a=_angi(); t=_tom(); ch=_changes(); cr=_chron()
    sc,issues=_health(s,m,a,t)
    L=[]; W=58
    
    L.append("="*W)
    L.append(f"  PDB SYSTEM STATUS  v3   {_ts()}")
    L.append("="*W)
    
    hs="✅ HEALTHY" if sc>=90 else "⚠️  DEGRADED" if sc>=70 else "❌ CRITICAL"
    L.append(f"  Health:  {hs}  {_bar(sc,20)}  {sc}/100")
    for rr in issues: L.append(f"           ⚠  {rr}")
    L.append("")
    
    L.append("── Database ──")
    if s:
        L.append(f"  Size:  {s['size']}  Nodes: {s['nodes']:,}  Namespaces: {s['ns']} ({s['small']} small)")
        for nm,nd,vl in s['top']:
            p=vl/nd*100 if nd>0 else 0
            L.append(f"    ^{nm:<20s} {nd:>8,}  {_bar(p)} {p:5.1f}%")
    L.append("")
    
    L.append("── MVM Processes ──")
    if m:
        L.append(f"  Total: {m['t']}  Real: {m['real']}  Tests: {m['test']}  Alive: {m['alive']}  Dead: {m['dead']}")
        for p in m['procs']:
            L.append(f"    PID {p.get('pid','?'):>4}  {p.get('name','?'):<16s}  {p.get('status','?')}")
    L.append("")
    
    L.append("── Agents ──")
    if a:
        L.append(f"  Team: {a['team']}  Decisions: {a['decisions']}  Incidents: {a['incidents']}  Alerts: {a['alerts']}")
    if t:
        L.append(f"  Tom: {t['t']} total  ({t['ok']} ok / {t['fail']} fail / {t['a']} running)")
    L.append("")
    
    if sv:
        L.append(f"── Services ({len(sv)}) ──")
        by={}
        for s2 in sv:
            ag=s2.get("agent","?")
            if ag not in by: by[ag]=[]
            by[ag].append(s2["name"])
        for ag in sorted(by):
            L.append(f"  {ag:<10s}  {', '.join(by[ag])}")
        L.append("")
    
    if cr:
        L.append(f"── Cron ({cr.get('t',0)} jobs, {cr.get('a',0)} active) ──")
        for j in cr.get("jobs",[]):
            ic="✅" if j.get("ok") else "❌"
            L.append(f"  {ic} {j.get('n','?'):<35s} {j.get('s','?'):<12s}")
        L.append("")
    
    if ch:
        L.append("── Recent Activity (last 5) ──")
        for c in ch:
            L.append(f"  {c.get('ts','?'):20s} {c.get('op','?'):>8s}  {c.get('ns','?')}")
        L.append("")
    
    if s:
        L.append("── Storage ──")
        L.append(f"  DB: {s['size']}")
        try:
            pdb_dir=os.path.dirname(os.path.abspath(pdb_tools.__file__))
            for fn in os.listdir(pdb_dir):
                fp=os.path.join(pdb_dir,fn)
                if os.path.isfile(fp) and fn.endswith(('.db-wal','.db-shm')):
                    L.append(f"  {fn.split('.')[-1].upper()}: {_fmt(os.path.getsize(fp))}")
        except: pass
        L.append("")
    
    import platform
    L.append("── System ──")
    L.append(f"  Python: {platform.python_version()}  Platform: {platform.platform(terse=True)}")
    L.append(f"  PID: {os.getpid()}")
    L.append("")
    
    L.append("="*W)
    return "\n".join(L)

def ss_json():
    return json.dumps({"ts":_ts(),"pdb":_schema(),"mvm":_mvm(),"services":_services(),
                        "angi":_angi(),"tom":_tom(),"changes":_changes()},indent=2)

if __name__=="__main__":
    print(ss())
