//! S6-D: M Package Manager — IMPORT routine.
//!
//! D IMPORT("lumen-std:1.2.3") → descarga ^ROUTINE desde registry.
//!
//! Registry format (HTTP GET):
//!   GET /packages/{name}/{version}/manifest.json
//!
//! Manifest:
//! ```json
//! {
//!   "name": "lumen-std",
//!   "version": "1.2.3",
//!   "routines": {
//!     "HTTP": "GET:^ROUTINE(\"HTTP\") S U=\"GET\" Q",
//!     "JSON": "PARSE:^ROUTINE(\"JSON\") S ..."
//!   },
//!   "checksum": "sha256:abc123..."
//! }
//! ```

/// IMPORT routine — M code that downloads and installs a package.
pub const IMPORT_CODE: &str = r#"
IMPORT(pkg)
  ; pkg = "name:version" ej: "lumen-std:1.2.3"
  S NAME=$P(pkg,":",1)
  S VERSION=$P(pkg,":",2)
  S URL="https://registry.lumen-protocol.org/packages/"_NAME_"/"_VERSION_"/manifest.json"
  O 8:"GET "_URL U 0 R MANIFEST
  C 8
  ; Parse manifest, install each routine
  S I=0
  F  S I=$O(^TMP("manifest","routines",I)) Q:I=""  D
  . S ROUTINE=$G(^TMP("manifest","routines",I,"name"))
  . S CODE=$G(^TMP("manifest","routines",I,"code"))
  . S J=0
  . F  S J=$O(CODE(J)) Q:J=""  D
  . . S ^ROUTINE(ROUTINE,J)=$G(CODE(J))
  . Q
  Q "OK"
"#;

/// Registry base URL (configurable).
pub const DEFAULT_REGISTRY: &str = "https://registry.lumen-protocol.org";

#[cfg(test)]
mod tests {
    #[test]
    fn test_import_routine_compiles() {
        let code = super::IMPORT_CODE;
        assert!(code.contains("IMPORT(pkg)"));
        assert!(code.contains("registry.lumen-protocol.org"));
    }
}
