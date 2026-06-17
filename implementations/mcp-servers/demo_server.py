#!/usr/bin/env python3
"""
Demo MCP server using the LUMEN SDK.
Shows how 600+ lines of boilerplate collapse to ~15 lines.
"""

from lumen_server import LumenServer

server = LumenServer("demo-server", version="1.0.0")

@server.tool("greet", description="Greet someone by name")
def greet(name: str) -> str:
    return f"Hello, {name}!"

@server.tool("add", description="Add two numbers")
def add(a: int, b: int) -> str:
    return f"{a} + {b} = {a + b}"

if __name__ == "__main__":
    server.run()
