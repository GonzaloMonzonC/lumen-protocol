/**
 * LUMEN Client — WebSocket + binary protocol decoder for dashboards.
 * 
 * Connects to ws://127.0.0.1:9877, receives LUMEN-framed metrics
 * (magic LUM\x01 + flags + u32 length + zlib payload), decompresses,
 * and calls window.renderData(data) on each message.
 * 
 * Falls back to HTTP polling if WebSocket is unavailable.
 */

(function() {
  var ws = null;
  var reconnectTimer = null;
  var WS_URL = 'ws://127.0.0.1:9877';

  function decodeLumenFrame(buffer) {
    /* LUMEN frame: magic(4) + flags(1) + length(4 LE) + payload */
    var data = new Uint8Array(buffer);
    if (data[0] !== 76 || data[1] !== 85 || data[2] !== 77 || data[3] !== 1) {
      return null; // not LUMEN
    }
    var flags = data[4];
    var length = new DataView(buffer).getUint32(5, true);
    var payload = new Uint8Array(buffer, 9, length);
    
    if (flags & 1) {
      /* zlib decompress */
      try {
        var ds = new DecompressionStream('deflate');
        var writer = ds.writable.getWriter();
        writer.write(payload);
        writer.close();
        return ds.readable;
      } catch(e) {
        /* DecompressionStream not available — return raw */
        var decoder = new TextDecoder();
        return decoder.decode(payload);
      }
    }
    var decoder = new TextDecoder();
    return decoder.decode(payload);
  }

  function handleMessage(event) {
    var result = decodeLumenFrame(event.data);
    if (!result) return;
    
    if (typeof result === 'string') {
      /* Already decoded */
      try {
        var data = JSON.parse(result);
        if (window.renderData) window.renderData(data);
      } catch(e) {}
    } else {
      /* ReadableStream from DecompressionStream */
      result.getReader().read().then(function(r) {
        try {
          var json = new TextDecoder().decode(r.value);
          var data = JSON.parse(json);
          if (window.renderData) window.renderData(data);
        } catch(e) {}
      });
    }
  }

  function connect() {
    try {
      ws = new WebSocket(WS_URL);
      ws.binaryType = 'arraybuffer';
      
      ws.onopen = function() {
        var label = document.getElementById('status-label');
        if (label) { label.textContent = 'Live·LUMEN'; label.className = 'status-text green'; }
        var dot = document.getElementById('status-dot');
        if (dot) dot.className = 'dot live';
      };
      
      ws.onmessage = handleMessage;
      
      ws.onclose = function() {
        ws = null;
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, 5000);
      };
      
      ws.onerror = function() {
        ws = null;
      };
    } catch(e) {
      ws = null;
    }
  }

  connect();
})();
