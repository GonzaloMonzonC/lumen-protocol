#!/usr/bin/env python3
"""ddp:pull con PREFIJO opcional: $DEVICE("ddp:pull","NODO",limit,depth,"<id>")
Asi el nodo trae SOLO su subarbol (su memoria), no la de todos los nodos."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light/src/host.rs"
s = open(P, encoding="utf-8", newline="").read()

old_uso = '''                            return Err(
                                "uso: $DEVICE(\\"ddp:pull\\",\\"NS\\",[limit],[depth])".to_string()
                            );'''
new_uso = '''                            return Err(
                                "uso: $DEVICE(\\"ddp:pull\\",\\"NS\\",[limit],[depth],[prefix])"
                                    .to_string()
                            );'''
assert old_uso in s, "no encontre el uso"
s = s.replace(old_uso, new_uso, 1)

old_lim = '''                        let limit_req = args.get(1).map(|v| v.as_number() as i64).unwrap_or(0);
                        let depth = args.get(2).map(|v| v.as_number() as i64).unwrap_or(-1);'''
new_lim = '''                        let limit_req = args.get(1).map(|v| v.as_number() as i64).unwrap_or(0);
                        let depth = args.get(2).map(|v| v.as_number() as i64).unwrap_or(-1);
                        // Namespace por nodo: prefijo para traer SOLO un subarbol
                        // (^NODO("<id>") = memoria propia del nodo).
                        let prefijo = args.get(3).map(|v| v.as_string()).unwrap_or_default();'''
assert old_lim in s, "no encontre limit/depth"
s = s.replace(old_lim, new_lim, 1)

old_path = '''                        let path = format!(
                            "/ddp/pull?ns={}&limit={}&offset={}&depth={}",
                            crate::ddp_client::urlenc(&ns),
                            pagina,
                            offset,
                            depth
                        );'''
new_path = '''                        let path = if prefijo.is_empty() {
                            format!(
                                "/ddp/pull?ns={}&limit={}&offset={}&depth={}",
                                crate::ddp_client::urlenc(&ns),
                                pagina,
                                offset,
                                depth
                            )
                        } else {
                            format!(
                                "/ddp/pull?ns={}&limit={}&offset={}&depth={}&prefix={}",
                                crate::ddp_client::urlenc(&ns),
                                pagina,
                                offset,
                                depth,
                                crate::ddp_client::urlenc(&prefijo)
                            )
                        };'''
assert old_path in s, "no encontre la construccion del path"
s = s.replace(old_path, new_path, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
print("host.rs OK: ddp:pull acepta prefijo")
