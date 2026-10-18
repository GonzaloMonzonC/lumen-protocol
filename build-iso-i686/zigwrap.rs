// Wrapper zig como CC/AR de cc-rs. Variantes por nombre de exe:
//   *gnu*  -> target x86-linux-gnu   (glibc, soporta cdylib/.so)
//   *musl* -> target x86-linux-musl  (estatico)
//   *ar*   -> zig ar ; *ranlib* -> zig ranlib
// Filtra flags que cc-rs inyecta y zig no entiende (--target=..., -m32, -m64).
use std::env;
use std::path::Path;
use std::process::{Command, exit};

const ZIG: &str = "C:/Users/gonzalo/tools/zig-x86_64-windows-0.16.0/zig.exe";

fn main() {
    let me = env::args().next().unwrap_or_default();
    let name = Path::new(&me)
        .file_name()
        .map(|s| s.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();

    let es64 = name.contains("x64") || name.contains("x86_64");
    let is_ranlib = name.contains("ranlib");
    let is_ar = !is_ranlib && name.contains("ar") && !name.contains("cc");
    let gnu = name.contains("gnu");

    let raw: Vec<String> = env::args().skip(1).collect();
    let filtered: Vec<String> = raw
        .into_iter()
        .filter(|a| !a.starts_with("--target=") && !a.contains("melf")
                && a != "-m32" && a != "-m64")
        .collect();

    let mut cmd = Command::new(ZIG);
    if is_ranlib {
        cmd.arg("ranlib");
    } else if is_ar {
        cmd.arg("ar");
    } else {
        // -nostartfiles: el crt1.o lo pone rustc (self-contained). Si zig mete el
        // suyo -> "duplicate symbol: _start".
        let target = if es64 {
            if gnu { "x86_64-linux-gnu" } else { "x86_64-linux-musl" }
        } else if gnu {
            "x86-linux-gnu"
        } else {
            "x86-linux-musl"
        };
        cmd.args(["cc", "-target", target, "-nostartfiles"]);
        if !es64 {
            cmd.arg("-mcpu=i686");
        }
    }
    cmd.args(&filtered);
    match cmd.status() {
        Ok(st) => exit(st.code().unwrap_or(1)),
        Err(e) => {
            eprintln!("zigwrap: no pude ejecutar zig: {e}");
            exit(127);
        }
    }
}
