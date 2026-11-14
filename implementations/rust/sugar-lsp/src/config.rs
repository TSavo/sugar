// Configuration for the Sugar LSP server.
//
// Reads `.sugar/config.toml` at workspace root. Example:
//
//   [server]
//   backend = "sugar"
//   backend_args = ["verify", "--format", "json"]
//   timeout_ms = 5000
//   cache_dir = ".sugar/cache"
//
//   [[language]]
//   name = "go"
//   extensions = [".go"]
//   plugin = "sugar-lsp-go"
//   plugin_args = ["--rpc"]
//
// Language plugins are spawned as child processes and spoken to via JSON-RPC.

use serde::Deserialize;
use std::path::Path;

#[derive(Debug, Clone, Deserialize)]
pub struct LspConfig {
    #[serde(default = "default_server")]
    pub server: ServerConfig,
    #[serde(default)]
    pub language: Vec<LanguagePluginConfig>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ServerConfig {
    #[serde(default = "default_backend")]
    pub backend: String,
    #[serde(default)]
    pub backend_args: Vec<String>,
    // timeout_ms and cache_dir removed (unused)
}

#[derive(Debug, Clone, Deserialize)]
pub struct LanguagePluginConfig {
    pub name: String,
    #[serde(default)]
    pub extensions: Vec<String>,
    /// External plugin binary path or name (looked up in PATH)
    pub plugin: Option<String>,
    #[serde(default)]
    pub plugin_args: Vec<String>,
}

impl LspConfig {
    /// Find the language config for a given file path.
    pub fn for_path(&self, path: &Path) -> Option<&LanguagePluginConfig> {
        let ext = path.extension()?.to_str()?;
        let with_dot = format!(".{}", ext);
        self.language.iter().find(|l| {
            l.extensions.iter().any(|e| {
                let e = if e.starts_with('.') {
                    e.clone()
                } else {
                    format!(".{}", e)
                };
                e == with_dot
            })
        })
    }
}

impl Default for LspConfig {
    fn default() -> Self {
        Self {
            server: default_server(),
            language: Vec::new(),
        }
    }
}

fn default_server() -> ServerConfig {
    ServerConfig {
        backend: default_backend(),
        backend_args: Vec::new(),
    }
}

fn default_backend() -> String {
    "sugar".to_string()
}

pub fn load_config(path: impl AsRef<Path>) -> Result<LspConfig, String> {
    let path = path.as_ref();
    if !path.exists() {
        return Ok(LspConfig::default());
    }

    let text = std::fs::read_to_string(path).map_err(|e| format!("read config: {}", e))?;

    let config: LspConfig = toml::from_str(&text).map_err(|e| format!("parse config: {}", e))?;

    Ok(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_declares_no_language_kits() {
        let cfg = LspConfig::default();

        assert!(
            cfg.language.is_empty(),
            "LSP language kits must be explicitly configured; got defaults: {:?}",
            cfg.language
        );
    }

    #[test]
    fn language_lookup_comes_from_configured_extensions() {
        let cfg = LspConfig {
            language: vec![LanguagePluginConfig {
                name: "rust".to_string(),
                extensions: vec![".rs".to_string()],
                plugin: Some("sugar-lsp-rust".to_string()),
                plugin_args: Vec::new(),
            }],
            ..LspConfig::default()
        };

        let lang = cfg
            .for_path(Path::new("src/lib.rs"))
            .expect("configured extension should resolve");
        assert_eq!(lang.name, "rust");
    }
}
