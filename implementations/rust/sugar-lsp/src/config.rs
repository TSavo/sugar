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
//   [auto]
//   lift = true
//   download_sources = true
//   download_recursive = false
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
    /// Auto-mode / Download sources knobs (#4007 / #4106).
    /// Env vars still win when set; this is the workspace-default surface.
    #[serde(default)]
    pub auto: AutoConfig,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AutoConfig {
    /// Default on. Maps to SUGAR_LSP_AUTO_LIFT when env unset.
    #[serde(default = "default_true")]
    pub lift: bool,
    /// Maven-class sdist/VCS fetch. Maps to SUGAR_LSP_DOWNLOAD_SOURCES.
    #[serde(default = "default_true")]
    pub download_sources: bool,
    /// Fetch Requires-Dist of sealed packages (direct deps only).
    #[serde(default)]
    pub download_recursive: bool,
}

fn default_true() -> bool {
    true
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
            auto: AutoConfig {
                lift: true,
                download_sources: true,
                download_recursive: false,
            },
        }
    }
}

impl Default for AutoConfig {
    fn default() -> Self {
        Self {
            lift: true,
            download_sources: true,
            download_recursive: false,
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
