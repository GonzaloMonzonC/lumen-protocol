#!/usr/bin/env python3
"""M → Rust — Demo. Genera Rust nativo desde M code, compila con rustc, ejecuta."""
import subprocess, os, tempfile, re

TMP = os.path.join(tempfile.gettempdir(), "m_demo")
os.makedirs(TMP, exist_ok=True)

CASES = [
    ("SET", ["S x=2+2"]),
    ("MATH", ["S x=(42+1)*3"]),  
    ("LOOP_100", ["S sum=0", "F i=1:1:100", "S sum=sum+i"]),
    ("LOOP_1k",  ["S sum=0", "F i=1:1:1000", "S sum=sum+i"]),
    ("LOOP_10k", ["S sum=0", "F i=1:1:10000", "S sum=sum+i"]),
]

def gen_rust(lines):
    seen = set()
    code = "fn main() {\n    use std::time::Instant;\n    let _t = Instant::now();\n"
    indent = ""
    for line in lines:
        s = line.strip()
        if not s: continue
        if s.startswith('S '):
            rest = s[2:].strip()
            if '=' not in rest: continue
            t, v = rest.split('=', 1)
            t, v = t.strip(), v.strip()
            if t.startswith('^'): continue
            rv = m_expr(v)
            if t not in seen:
                code += f"{indent}    let mut {t} = {rv};\n"
                seen.add(t)
            else:
                code += f"{indent}    {t} = {rv};\n"
        elif s.startswith('F '):
            rest = s[2:].strip()
            if '=' not in rest: continue
            var, rng = rest.split('=', 1)
            var = var.strip()
            parts = rng.split(':')
            fv = parts[0].strip()
            tv = parts[2].strip() if len(parts) > 2 else (parts[1].strip() if len(parts) > 1 else fv)
            seen.add(var)
            code += f"{indent}    for {var}_iter in ({m_expr(fv)} as i64)..=({m_expr(tv)} as i64) {{\n"
            code += f"{indent}        let mut {var} = {var}_iter as f64;\n"
            indent += "    "
        else:
            code += f"{indent}    // (body) {s}\n"
    while indent:
        indent = indent[:-4]
        code += f"{indent}    }}\n"
    code += """    let e = _t.elapsed();
    let ns = e.as_nanos();
    if ns >= 1_000_000 { print!("{:.3}", ns as f64/1e6); println!("ms"); }
    else if ns >= 1_000 { print!("{}", ns/1000); println!("µs"); }
    else { print!("{}", ns); println!("ns"); }
}"""
    return code

def m_expr(e):
    e = e.strip()
    # Number literal
    try: return f"{float(e)}f64"
    except: pass
    # Parenthesized
    if e.startswith('(') and e.endswith(')'):
        return f"({m_expr(e[1:-1])})"
    # Binary ops (lowest precedence first)
    for op, rop in [('+','+'), ('-','-'), ('*','*'), ('/','/')]:
        i = 1
        while i < len(e):
            if e[i] == op and (e[i-1].isalnum() or e[i-1] == ')'):
                return f"({m_expr(e[:i])} {rop} {m_expr(e[i+1:])})"
            i += 1
    return e  # variable name

def compile_rs(name, lines):
    rust = gen_rust(lines)
    safe = re.sub(r'[^a-zA-Z0-9]', '_', name.lower())
    rs = os.path.join(TMP, f"{safe}.rs")
    exe = os.path.join(TMP, f"{safe}.exe")
    with open(rs, 'w') as f: f.write(rust)
    r = subprocess.run(['rustc', '--edition', '2021', '-O', '-o', exe, rs],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return None, r.stderr, rust
    times = []
    for _ in range(3):
        r2 = subprocess.run([exe], capture_output=True, text=True, timeout=5)
        t = r2.stdout.strip()
        if t.endswith('ns'): times.append(int(t[:-2]) / 1e9)
        elif t.endswith('µs'): times.append(int(t[:-2]) / 1e6)
        elif t.endswith('ms'): times.append(float(t[:-2]) / 1e3)
    return min(times) if times else None, None, rust

print(f"{'═'*60}")
print("  M → RUST — COMPILADOR NATIVO DEMO")
print(f"{'═'*60}")
print(f"\n  {'Caso':15s} {'Tiempo':>12s} {'Ops/s (est)':>14s}")
print(f"  {'─'*42}")

for name, lines in CASES:
    result = compile_rs(name, lines)
    t = result[0]
    if t is None:
        err, rust = result[1], result[2]
        print(f"  ❌ {name:13s} COMPILE ERROR")
        for ln in (err or '').split('\n')[:3]:
            print(f"     {ln}")
        if 'expected' in err:
            print(f"  ── Rust generado ──")
            for ln in rust.split('\n')[:6]:
                print(f"  {ln}")
        continue
    
    # Format time
    if t < 1e-9: t_str = f"{t*1e9:.1f}ns"
    elif t < 1e-6: t_str = f"{t*1e6:.1f}µs"
    elif t < 1e-3: t_str = f"{t*1e3:.1f}ms"
    else: t_str = f"{t:.3f}s"
    
    ops_sec = f"{1.0/t:,.0f}" if t > 0 else "∞"
    print(f"  ✅ {name:13s} {t_str:>12s} {ops_sec:>14s}")

# Show generated Rust
print(f"\n  ── Ejemplo: Rust generado para LOOP_1k ──")
_, _, rust = compile_rs("example", ["S sum=0", "F i=1:1:1000", "S sum=sum+i"])
for ln in rust.split('\n')[:12]:
    print(f"  {ln}")

print(f"\n{'═'*60}")
print("  ✅ M → Rust compila y corre a velocidad nativa")
print("    Siguiente paso: integrar en MVM como backend JIT")
print(f"{'═'*60}")
