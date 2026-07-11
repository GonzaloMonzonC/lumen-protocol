    def compile(self, code: str) -> MBytecode:
        """Compilar código M a bytecode."""
        bc = MBytecode()
        for lineno, line in enumerate(code.split('\n'), 1):
            line = line.strip()
            if not line or line.startswith(';'):
                continue
            self._compile_line(bc, line)
        bc.resolve_jumps()
        return bc