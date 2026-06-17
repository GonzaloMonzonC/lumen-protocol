/**
 * Echo server for transport tests.
 *
 * Handles both LUMEN negotiation (probe → ack) and JSON-RPC echo.
 * Used by transport.test.ts as the subprocess.
 *
 * Run: node --import tsx src/__test_echo__.ts
 */

import { FrameAssembler } from "./frame-assembler.js";
import { buildFrame, buildSize, TYPE_PROBE, FLAG_COMPRESSED } from "./frame.js";
import { compressValue } from "./compress.js";

const assembler = new FrameAssembler();
let lumenMode = false;
let jsonBuffer = "";

process.stdin.on("data", (chunk: Buffer) => {
  const data = new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength);

  if (!lumenMode) {
    // Try to detect a LUMEN PROBE frame
    const frames = assembler.push(data);
    for (const frame of frames) {
      if (frame.frameType === TYPE_PROBE) {
        // Build PROBE_ACK response
        const ackPayload = compressValue({ v: 1, caps: ["compression"] } as Record<string, unknown>);
        const total = buildSize(ackPayload.length);
        const buf = new Uint8Array(total);
        buildFrame(0x10 /* TYPE_PROBE_ACK */, FLAG_COMPRESSED, ackPayload, buf, 0);
        process.stdout.write(Buffer.from(buf));
        lumenMode = true;
        assembler.reset();
        return;
      }
    }

    // JSON-RPC mode: accumulate and echo complete lines
    jsonBuffer += chunk.toString();
    const lines = jsonBuffer.split("\n");
    jsonBuffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) {
        process.stdout.write(line + "\n");
      }
    }
  } else {
    // LUMEN mode: echo frames back verbatim
    const frames = assembler.push(data);
    for (const frame of frames) {
      const total = buildSize(frame.payload.length);
      const buf = new Uint8Array(total);
      buildFrame(frame.frameType, frame.flags, frame.payload, buf, 0);
      process.stdout.write(Buffer.from(buf));
    }
  }
});

// Flush any remaining buffered JSON on exit
process.on("beforeExit", () => {
  if (jsonBuffer.trim()) {
    process.stdout.write(jsonBuffer + "\n");
  }
});
