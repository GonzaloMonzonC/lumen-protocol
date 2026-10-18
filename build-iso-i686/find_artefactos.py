#!/usr/bin/env python3
"""Donde estan los artefactos de lumen-m-light?"""
import glob, os

cands = [
    "C:/Users/gonzalo/Documents/GitHub/mvm-nas/target",
    "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/target",
]
for base in cands:
    print(f"\n=== {base} ===")
    if not os.path.isdir(base):
        print("  (no existe)")
        continue
    subs = sorted(os.listdir(base))
    print(f"  subdirs: {subs[:10]}")
    hits = glob.glob(os.path.join(base, "**", "*lumen_m_light*"), recursive=True)
    print(f"  artefactos lumen_m_light: {len(hits)}")
    for h in hits[:5]:
        print(f"    {os.path.getsize(h):>10} B  {os.path.basename(h)[:60]}")

# y el deps del target i686 de mvm-nas: cuantos ficheros hay?
d = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/target/i686-unknown-linux-musl/release/deps"
print(f"\n=== deps de mvm-nas i686 ===")
print("  existe:", os.path.isdir(d))
if os.path.isdir(d):
    fs = os.listdir(d)
    print(f"  ficheros: {len(fs)}")
    lum = [f for f in fs if "lumen" in f.lower()]
    print(f"  con 'lumen': {len(lum)}  ->  {lum[:5]}")
