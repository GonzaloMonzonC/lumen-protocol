#!/usr/bin/env python3
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()
i = s.find('TELNET_ON" = "si"')
print("repr de la zona:")
print(repr(s[i - 60:i + 260]))
