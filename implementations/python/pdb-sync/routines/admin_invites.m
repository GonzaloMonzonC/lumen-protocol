ADMIN ; /web/admin/invites — Gestion de invitaciones pendientes
 N token,node,ts,html,count
 S html="<!DOCTYPE html>"
 S html=html_"<html><head>"
 S html=html_"<meta charset='utf-8'>"
 S html=html_"<meta name='viewport' content='width=device-width,initial-scale=1'>"
 S html=html_"<style>"
 S html=html_"*{margin:0;padding:0;box-sizing:border-box}"
 S html=html_"body{font-family:system-ui,sans-serif;padding:16px;max-width:800px;margin:0 auto;background:#0a0a0f;color:#ddd}"
 S html=html_"h1{font-size:1.25rem;margin-bottom:.5rem}"
 S html=html_".sub{color:#888;font-size:.75rem;margin-bottom:1rem}"
 S html=html_"table{width:100%;border-collapse:collapse;margin-bottom:1rem}"
 S html=html_"th,td{padding:.5rem .75rem;text-align:left;border-bottom:1px solid #222;font-size:.875rem}"
 S html=html_"th{color:#888;font-weight:500}"
 S html=html_"tr:hover{background:#ffffff04}"
 S html=html_".btn{display:inline-block;padding:.25rem .75rem;border-radius:4px;font-size:.75rem;cursor:pointer;border:none;margin-right:.25rem}"
 S html=html_".btn-ok{background:#51cf6622;color:#51cf66;border:1px solid #51cf6644}"
 S html=html_".btn-no{background:#ff6b6b22;color:#ff6b6b;border:1px solid #ff6b6b44}"
 S html=html_".badge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.625rem;font-weight:600}"
 S html=html_".badge-pending{background:#ffd43b22;color:#ffd43b}"
 S html=html_"@media(max-width:480px){table,thead,tbody,th,td,tr{display:block}"
 S html=html_"th{display:none}"
 S html=html_"td{padding:.375rem .5rem;border:none;display:flex;justify-content:space-between;align-items:center}"
 S html=html_"td:before{content:attr(data-label);font-weight:600;font-size:.625rem;color:#888;margin-right:.5rem}}"
 S html=html_"</style></head><body>"
 S html=html_"<h1>🎫 Invitaciones Pendientes</h1>"
 S html=html_"<p class='sub'>Tokens que requieren aprobacion</p>"
 
 ; Contar pendientes
 S count=0
 S token="" F  S token=$O(^INVITACION("pending",token)) Q:token=""  D
 . I $G(^INVITACION("pending",token))'="" S count=count+1
 
 I count=0 D  G DONE
 . S html=html_"<p style='color:#888'>No hay invitaciones pendientes ✅</p>"
 
 S html=html_"<table><thead><tr><th>Nodo</th><th>Fecha</th><th>Token</th><th></th></tr></thead><tbody>"
 
 S token="" F  S token=$O(^INVITACION("pending",token)) Q:token=""  D
 . S node=$P($G(^INVITACION("pending",token)),"|",1)
 . S ts=$P($G(^INVITACION("pending",token)),"|",2)
 . S ts=$E(ts,12,19)  ; solo HH:MM:SS
 . S html=html_"<tr>"
 . S html=html_"<td data-label='Nodo'>"_node_"</td>"
 . S html=html_"<td data-label='Fecha'>"_ts_"</td>"
 . S html=html_"<td data-label='Token' style='font-family:monospace;font-size:.7rem'>"_$E(token,1,16)_"...</td>"
 . S html=html_"<td data-label='Accion'>"
 . S html=html_"<button class='btn btn-ok' onclick=\"fetch('/web/admin/invites/approve?token="_token_"',{method:'POST'}).then(()=>location.reload())\">✓</button>"
 . S html=html_"<button class='btn btn-no' onclick=\"fetch('/web/admin/invites/reject?token="_token_"',{method:'POST'}).then(()=>location.reload())\">✕</button>"
 . S html=html_"</td></tr>"
 
 S html=html_"</tbody></table>"
 
 ; Stats
 S html=html_"<p class='sub'>Limite diario: "
 S html=html_$G(^CONFIG("invite_daily_limit"),5)
 S html=html_" | Aprobados: "
 S html=html_$G(^INVITACION("approved_count"),0)
 S html=html_"</p>"
 
DONE
 S html=html_"<p style='margin-top:2rem;font-size:.75rem;color:#555'>"
 S html=html_"<a href='/' style='color:#888'>← Home</a></p>"
 S html=html_"</body></html>"
 W html
 Q
