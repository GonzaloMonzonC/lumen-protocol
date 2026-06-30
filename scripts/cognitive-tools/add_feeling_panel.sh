# Add feeling panel to dashboard.html

python -c "
p = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\dashboard.html'
with open(p) as f:
    c = f.read()

# 1. Add feeling panel card (before the Wiki panel on the grid2 section)
panel_html = '''<div class=\"glass\"><h3>🧠 Cognitive State</h3><div id=\"feeling-list\"><div class=\"dim\" style=\"font-size:11px\">No feeling recorded</div></div></div>
'''

# Insert before Wiki panel
c = c.replace('<div class=\"glass\"><h3>📚 Wiki</h3><div id=\"wiki-list\">', panel_html + '<div class=\"glass\"><h3>📚 Wiki</h3><div id=\"wiki-list\">')
print('1. Added feeling panel card')

# 2. Add feeling loading JS in the metrics loading function
# Find where sessions are loaded and add feeling there
load_js = '''
    // ── Cognitive State ──
    const feeling = (d.sessions_detail && d.sessions_detail[Object.keys(d.sessions_detail)[0]]?.feeling) || null;
    if (feeling && feeling.mood) {
        const moodIcons = {focused:'🎯', frustrated:'😤', stuck:'🫤', tired:'😴', confident:'💪', curious:'🤔', overwhelmed:'😰', neutral:'😐'};
        const icon = moodIcons[feeling.mood] || '🧠';
        const confidencePct = (feeling.confidence || 5) * 10;
        const energyPct = (feeling.energy || 5) * 10;
        const ts = feeling.ts ? new Date(feeling.ts * 1000).toLocaleTimeString() : '';
        $('feeling-list').innerHTML = '<div style=\"text-align:center;padding:4px 0\">' +
            '<span style=\"font-size:28px\">' + icon + '</span>' +
            '<div style=\"font-size:14px;font-weight:600;margin:4px 0\">' + feeling.mood + '</div>' +
            '<div style=\"font-size:11px;color:var(--text-muted)\">' + (feeling.context || '') + '</div>' +
            '<div style=\"margin:8px 0\"><div style=\"font-size:10px;color:var(--dim);margin-bottom:2px\">Confidence</div>' +
            '<div style=\"height:6px;background:var(--border);border-radius:3px;overflow:hidden\"><div style=\"height:100%;width:' + confidencePct + '%;background:var(--acc);border-radius:3px\"></div></div></div>' +
            '<div style=\"margin:8px 0\"><div style=\"font-size:10px;color:var(--dim);margin-bottom:2px\">Energy</div>' +
            '<div style=\"height:6px;background:var(--border);border-radius:3px;overflow:hidden\"><div style=\"height:100%;width:' + energyPct + '%;background:var(--purp);border-radius:3px\"></div></div></div>' +
            '<div class=\"mono dim\" style=\"font-size:10px\">' + ts + '</div></div>';
    } else {
        $('feeling-list').innerHTML = '<div class=\"dim\" style=\"font-size:11px\">No feeling recorded</div>';
    }

'''

# Insert after the sessions section in loadMetrics
old = '''    // ── Sessions ──'''
if old in c:
    c = c.replace(old, load_js + old)
    print('2. Added feeling JS')
else:
    print('2. Pattern not found')

with open(p, 'w') as f:
    f.write(c)
print('✓ Dashboard updated')
"
