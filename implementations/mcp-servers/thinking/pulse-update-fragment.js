function pulseUpdate(works){
  const now=Date.now()/1000;
  const fmtTime=ts=>{const s=Math.round(now-ts);return s<60?s+'s':s<3600?Math.floor(s/60)+'m':Math.floor(s/3600)+'h'};
  const fmtDur=d=>{const m=d/60;return m<60?m.toFixed(0)+'m':(m/60).toFixed(1)+'h'};
  const shortItem=s=>s&&s.length>22?s.slice(0,22)+'...':s||'';
  // NOW: in_progress works started within last 60 minutes
  const active=works.filter(w=>w.status==='in_progress'&&w.started_at&&(now-w.started_at)<3600).slice(0,5);
  // Recent: completed within 24h
  const done=works.filter(w=>w.status==='done'&&w.done_at&&(now-w.done_at)<86400).sort((a,b)=>(b.done_at||0)-(a.done_at||0)).slice(0,5);
  const blocked=works.filter(w=>w.status==='blocked').slice(0,3);
  // Show modal on click with full work data
  window.showWorkInfo=function(w){
    if(!w)return;
    const lines=['<div style="font-size:13px;font-weight:600;margin-bottom:8px">'+(w.item||'Unnamed')+'</div>'];
    if(w.description)lines.push('<div class="dim" style="font-size:11px;margin-bottom:8px">'+w.description.slice(0,300)+'</div>');
    lines.push('<div class="chain-row"><span class="dim">Status</span><span class="tag '+(w.status==='done'?'green':w.status==='in_progress'?'cyan':'red')+'">'+(w.status||'?')+'</span></div>');
    if(w.started_at)lines.push('<div class="chain-row"><span class="dim">Started</span><span class="mono">'+new Date(w.started_at*1000).toLocaleString()+'</span></div>');
    if(w.done_at)lines.push('<div class="chain-row"><span class="dim">Completed</span><span class="mono">'+new Date(w.done_at*1000).toLocaleString()+'</span></div>');
    if(w.started_at&&w.done_at)lines.push('<div class="chain-row"><span class="dim">Duration</span><span class="mono">'+fmtDur(w.done_at-w.started_at)+'</span></div>');
    if(w.started_at&&!w.done_at)lines.push('<div class="chain-row"><span class="dim">Elapsed</span><span class="mono">'+fmtDur(now-w.started_at)+'</span></div>');
    if(w.category)lines.push('<div class="chain-row"><span class="dim">Category</span><span>'+w.category+'</span></div>');
    if(w.block_reason)lines.push('<div class="chain-row"><span class="dim">Blocked by</span><span style="color:var(--red)">'+w.block_reason+'</span></div>');
    $('modal-container').innerHTML='<div class="modal-overlay" onclick="this.remove()"><div class="modal" onclick="event.stopPropagation()"><button class="modal-close" onclick="this.parentElement.parentElement.remove()">&times;</button>'+lines.join('')+'</div></div>';
  };
  // Build clickable cards
  const renderCard=(w,color,sub)=>{
    const json=encodeURIComponent(JSON.stringify(w));
    return '<div class="chain-row" style="cursor:pointer;padding:8px 10px;margin-bottom:4px;background:rgba(255,255,255,.02);border-radius:8px;border-left:3px solid '+color+';transition:background .2s" onclick="showWorkInfo(JSON.parse(decodeURIComponent(\''+json+'\')))" onmouseover="this.style.background=\'rgba(255,255,255,.06)\'" onmouseout="this.style.background=\'rgba(255,255,255,.02)\'"><span style="font-size:11px;font-weight:700;color:'+color+'">'+(w.status==='done'?'\u2714\uFE0F':w.status==='in_progress'?'\u25B6':'\u274C')+'</span><span class="mono" style="flex:1;margin:0 8px;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+shortItem(w.item||w.title||'')+'</span><span class="dim" style="font-size:9px;white-space:nowrap">'+sub+'</span></div>';
  };
  $('pulse-now').innerHTML=active.length?active.map(w=>renderCard(w,'#22d3ee',fmtDur((now-w.started_at)/60))).join(''):'<div class="dim" style="font-size:11px;padding:12px;text-align:center">None active</div>';
  $('pulse-recent').innerHTML=done.length?done.map(w=>renderCard(w,'rgba(34,211,238,.5)',(w.done_at?fmtTime(w.done_at):'')+' ago')).join(''):'<div class="dim" style="font-size:11px;padding:12px;text-align:center">None done</div>';
  $('pulse-blocked').innerHTML=blocked.length?blocked.map(w=>renderCard(w,'#ef4444','')).join(''):'<div class="dim" style="font-size:11px;padding:12px;text-align:center">None blocked</div>';
}