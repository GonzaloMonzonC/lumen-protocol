#!/usr/bin/env python3
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()
i = s.find('HUB=""')
print(repr(s[i - 120:i + 620]))
