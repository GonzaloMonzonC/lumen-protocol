/**
 * Integration test: CadenciaBridge (TypeScript) ↔ cadencia-bridge (Rust).
 *
 * Spawns the Rust sidecar binary and verifies the JSON command protocol,
 * index operation with real files, and performance metrics.
 *
 * Run: node --import tsx --test src/cadencia.integration.test.ts
 */

import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { CadenciaBridge } from "./cadencia.js";
import { writeFileSync, mkdirSync, rmSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const BINARY = join(
  __dirname,
  "..",
  "..",
  "rust",
  "target",
  "release",
  "cadencia-bridge.exe",
);

const TEST_DIR = join(tmpdir(), "lumen-integration-test");

function setupTestFiles(count: number): string[] {
  if (!existsSync(TEST_DIR)) mkdirSync(TEST_DIR, { recursive: true });
  const files: string[] = [];
  for (let i = 0; i < count; i++) {
    const path = join(TEST_DIR, `test_${i}.txt`);
    writeFileSync(path, `Hello from LUMEN test file ${i}!\n`.repeat(100));
    files.push(path);
  }
  return files;
}

describe("CadenciaBridge Integration", () => {
  let bridge: CadenciaBridge;
  let testFiles: string[];

  before(() => {
    testFiles = setupTestFiles(10);
    bridge = new CadenciaBridge({ binaryPath: BINARY });
  });

  after(() => {
    if (existsSync(TEST_DIR)) rmSync(TEST_DIR, { recursive: true, force: true });
  });

  it("starts and responds to ping", async () => {
    const resp = await bridge.start();
    assert.equal(resp.status, "ok");
    assert.equal(resp.protocol, "lumen/1");
    assert.ok(resp.version);
  });

  it("indexes files and reports stats", async () => {
    const resp = await bridge.index(testFiles);
    assert.equal(resp.status, "ok");
    assert.equal(resp.files, 10);
    assert.ok(resp.total_bytes!, "total_bytes should be > 0");
    assert.ok(resp.wire_bytes!, "wire_bytes should be > 0");
    assert.ok(resp.encode_us!, "encode_us should be > 0");
    assert.ok(resp.elapsed_us!, "elapsed_us should be > 0");

    // LUMEN binary adds overhead for tiny payloads — ratio improves with size
    const ratio = (resp.wire_bytes! / resp.total_bytes! * 100);
    console.error(`  Compression: ${resp.total_bytes}B → ${resp.wire_bytes}B (${ratio.toFixed(1)}%)`);
    console.error(`  Encode: ${resp.encode_us}µs  Elapsed: ${resp.elapsed_us}µs`);
    console.error(`  Note: for ${resp.total_bytes}B total, binary overhead may exceed JSON — expected.`);
  });

  it("stops gracefully", async () => {
    const respPromise = bridge.stop();
    // stop() resolves after the process exits
    await respPromise;
    // CadenciaBridge.stop() calls send({cmd:"stop"}) then kills, no explicit result to assert
    assert.ok(true); // didn't throw
  });
});
