import sqlite3, sys

# El subkey de _globals es BINARIO: \x02NS\xff\x02campo\xff
# Lo aprendimos leyendo carga::leer_de_sqlite.

def subkey(ns, campo):
    # La ruta canonica empieza por NET: ^SYS("NET",<campo>). Aunque la tabla
    # se llame ns='SYS', el subkey lleva la RUTA completa.
    return b'\x02NET\xff\x02' + campo.encode() + b'\xff'

def crear_perfil(ruta, campos):
    conn = sqlite3.connect(ruta)
    conn.execute('CREATE TABLE IF NOT EXISTS _globals (ns TEXT, subkey BLOB, value TEXT, PRIMARY KEY (ns, subkey))')
    for (ns, campo), valor in campos.items():
        conn.execute('INSERT OR REPLACE INTO _globals VALUES (?,?,?)',
                     (ns, subkey(ns, campo), valor))
    conn.commit()
    # Verificar que se puede leer
    n = conn.execute("SELECT COUNT(*) FROM _globals WHERE ns='SYS'").fetchone()[0]
    conn.close()
    return n

if __name__ == '__main__':
    base = sys.argv[1]
    raiz_pub = sys.argv[2]
    clave_pub = sys.argv[3]
    rol = sys.argv[4]
    n = crear_perfil(base, {
        ('SYS', 'role'): rol,
        ('SYS', 'mode'): 'Lan',
        ('SYS', 'transport'): 'Quic',
        ('SYS', 'storage'): 'Lmdb',
        ('SYS', 'identity'): 'pubkey',
        ('SYS', 'sign'): 'hash-chain',
        ('SYS', 'raiz_armador'): raiz_pub,
        ('SYS', 'clave_publica'): clave_pub,
    })
    print('perfil %s: %d campos SYS' % (rol, n))
