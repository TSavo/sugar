// SPDX-License-Identifier: MIT OR Apache-2.0
//
// The unforgeable `Kit` frontend handle (SEAM 3b of the compiler-shape
// plan: ~/.claude/plans/sugar-compiler-liftshift.md).
//
// A `Kit` is minted ONLY by `Kit::rendezvous`: given a resolved lift
// manifest (the CLI's census/selection-policy output -- WHICH plugin
// command answers WHICH surface, per `dialect_for_surface`/`lift_kit_name`/
// `find_manifest` in `sugar-cli/src/lift_plugin.rs`), rendezvous performs a
// LIVE handshake -- spawn the manifest's command, run `initialize` +
// `sugar.plugin.kit_declaration` + `shutdown` over its stdio (via
// `kit_declaration::load_kit_declaration_with_command`, moved here from
// `sugar-cli/src/kit_declaration.rs` in the same follow-up that added this
// handshake) -- before constructing the kit's own dispatch registration and
// owning the resulting `LiftKit` transport on the handle. A manifest whose
// command doesn't spawn, doesn't speak the protocol, or returns an invalid
// declaration cannot mint a `Kit`: `RendezvousError::Handshake` names the
// stage. Holding a `Kit` is therefore proof a real kit process answered its
// declaration RPC, not just that a manifest shape parsed: there is no
// `Kit::new`, no `From<Value>`, no `Default`, no `Deserialize` (see
// `sugar-compiler/tests/kit_unforgeable.rs`).
//
// `Kit::lift` folds `dispatch_lift_path`'s body (originally
// `sugar-cli/src/lift_plugin.rs:293-379`): build the lift request, run it
// through the `kit_path` engine's `execute_path`, and return the terminal
// `DomainClaim`. The `KitRegistry::default()` that call used to build fresh
// on every dispatch (`lift_plugin.rs:346`) becomes this Kit's own
// `registry` field, built once at rendezvous time.
//
// SCOPE NOTE (reported to the coordinator, not silently narrowed): the
// workspace CENSUS (`sugar-cli/src/component_plan.rs`'s
// `census_workspace`/`plan_workspace`/`planned_lift_manifest`, ~2663 lines,
// integrated with `project_config`'s `PluginEntry` parsing) is SELECTION
// POLICY -- deciding which plugin command answers a surface -- and the
// brief itself says to keep selection policy in the thin CLI client
// (`dialect_for_surface`, `lift_kit_name`, `find_manifest`). `rendezvous`
// therefore takes the census's OUTPUT (a `LiftManifest`) as an argument
// rather than re-deriving it inside `sugar-compiler`: a `Kit` still cannot
// be forged from a bare surface string or a `Value`, because the manifest
// itself only exists once the CLI's census has run and resolved a real
// plugin command. The full component_plan.rs mechanism move into libsugar
// (SEAM 3b-i in the brief) is NOT done in this pass -- flagged, not hidden.
//
// `LiftManifest` field privacy (#3855): fields are private; the only public
// builder is `LiftManifest::resolved(...)`. Live handshake still refuses
// non-kits; privacy narrows the syntactic forgery surface so casual
// `LiftManifest { .. }` construction is a compile error (trybuild).
//
// Strong `Kit::lift` request (#3855 residual): `lift` takes `LiftRequest`, not
// free-form `serde_json::Value`. Trybuild `lift_request_is_not_value.rs` pins
// the type door.
//
// SourceMemento relocate (#3855): locator types live in libsugar; sugar-compiler
// has no sugar-walk Cargo edge (arch-guard). Residual: census move, pool
// single-owner.

use std::path::{Path, PathBuf};

use libsugar::core::{
    address, ConformanceDeclaration, Dialect, HashMapInputCatalog, Input, Path as CorePath,
    PathAlgebra, Verb,
};
use serde::Serialize;
use serde_json::Value;
use sugar_claim_envelope::KitDeclaration;

use crate::kit_declaration::{load_kit_handshake_with_command, KitDeclarationLoadError};
use crate::kit_path::{execute_path, KitRegistry, LiftKit, PathExecutionError};
use crate::resolve::{
    resolve_source, resolve_testimony, ResolvedSource, SourceRefusal, TestimonyError,
    TestimonyResolution,
};
use libsugar::core::SourceMemento;

/// The census's resolved answer to "what plugin command answers this
/// surface." Produced by the CLI's selection policy
/// (`component_plan::planned_lift_manifest` / `lift_plugin::find_manifest`)
/// and handed to `Kit::rendezvous` by value, so rendezvous can never
/// silently re-resolve a different manifest than the one the caller
/// already settled on.
///
/// Fields are private. The only public construction door is
/// [`LiftManifest::resolved`] — census/selection mints through that door so
/// manifest forgery is deliberate (`resolved(...)` call) rather than casual
/// field assignment. Trybuild pins the private-fields invariant.
#[derive(Debug, Clone)]
pub struct LiftManifest {
    surface: String,
    name: String,
    dialect: Dialect,
    command: Vec<String>,
    working_dir: Option<PathBuf>,
    /// Optional JSON-RPC method override (manifest.toml's `method = "..."`),
    /// e.g. consumer surfaces such as `rust-implications` that answer
    /// `sugar.plugin.lift_implications` instead of the default `lift`.
    /// `None` keeps the transport's default method.
    method: Option<String>,
}

impl LiftManifest {
    /// The only public builder for a resolved lift manifest.
    ///
    /// Callers (CLI census, LSP selection, focused tests) assemble the
    /// already-resolved plugin command + absolute working_dir here. Relative
    /// working_dir and empty command remain rendezvous-stage refusals — this
    /// constructor is the syntactic door, not a second validation layer.
    pub fn resolved(
        surface: impl Into<String>,
        name: impl Into<String>,
        dialect: Dialect,
        command: Vec<String>,
        working_dir: Option<PathBuf>,
        method: Option<String>,
    ) -> Self {
        Self {
            surface: surface.into(),
            name: name.into(),
            dialect,
            command,
            working_dir,
            method,
        }
    }

    /// Plugin display name from the census (manifest.toml `name`), distinct
    /// from `surface` (the selection key). Exposed deliberately via accessor
    /// rather than a public field — same privacy door as construction.
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn surface(&self) -> &str {
        &self.surface
    }

    pub fn dialect(&self) -> &Dialect {
        &self.dialect
    }

    pub fn command(&self) -> &[String] {
        &self.command
    }

    pub fn working_dir(&self) -> Option<&Path> {
        self.working_dir.as_deref()
    }

    pub fn method(&self) -> Option<&str> {
        self.method.as_deref()
    }
}

/// Failure to mint a `Kit`. Every arm names a concrete rendezvous-stage
/// failure, never a bare `String`.
#[derive(Debug, thiserror::Error)]
pub enum RendezvousError {
    #[error("no lift manifest resolved for surface `{0}` (empty plugin command)")]
    EmptyCommand(String),
    #[error(
        "relative working_dir `{working_dir}` for surface `{surface}`: LiftManifest's contract \
         is a RESOLVED working directory -- resolve against the project root before rendezvous \
         (the CLI census does this via resolved_working_dir)"
    )]
    RelativeWorkingDir {
        surface: String,
        working_dir: String,
    },
    #[error("kit declaration handshake failed for surface `{surface}`: {source}")]
    Handshake {
        surface: String,
        #[source]
        source: KitDeclarationLoadError,
    },
}

/// Failure during `Kit::lift`.
#[derive(Debug, thiserror::Error)]
pub enum KitError {
    #[error("encode lift request: {0}")]
    RequestEncoding(serde_json::Error),
    #[error("lift path execution failed: {0}")]
    PathExecution(#[from] PathExecutionError),
    /// Part 6: `sugar.enumerate` step failures (spawn/wire/decode, or a
    /// singular seek finding no matching node). See `tree::EnumerateError`.
    #[error("tree enumeration failed: {0}")]
    Enumerate(#[from] crate::tree::EnumerateError),
}

/// Strong lift request at the `Kit` boundary (#3855 residual).
///
/// Free-form `serde_json::Value` is no longer accepted by [`Kit::lift`]. The
/// only construction doors are [`LiftRequest::project`] (minimal whole-project
/// walk) and the builder methods that attach optional wire fields the language
/// kits already consume. Wire JSON keys stay stable so kit RPC params do not
/// drift when the type hardens.
///
/// Nested option keys use the historical camelCase names (`identifyOnly`,
/// `reportSummary`, `workspaceOverride`) because that is the kit wire, not a
/// new Rust surface.
#[derive(Debug, Clone, Serialize)]
pub struct LiftRequest {
    workspace_root: PathBuf,
    source_paths: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    surface: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    config_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    options: Option<LiftRequestOptions>,
    #[serde(skip_serializing_if = "Option::is_none")]
    contract_bindings: Option<Vec<Value>>,
}

/// Nested `options` object on the lift wire. Built by the CLI census path
/// (`build_lift_params`); optional for focused tests that only need a
/// workspace walk.
#[derive(Debug, Clone, Serialize)]
pub struct LiftRequestOptions {
    layer: String,
    #[serde(rename = "identifyOnly")]
    identify_only: bool,
    #[serde(rename = "emit", skip_serializing_if = "Option::is_none")]
    emit: Option<String>,
    #[serde(rename = "reportSummary", skip_serializing_if = "Option::is_none")]
    report_summary: Option<bool>,
    #[serde(rename = "workspaceOverride", skip_serializing_if = "Option::is_none")]
    workspace_override: Option<String>,
}

impl LiftRequestOptions {
    /// Full options object the CLI mints for a surface. `report_summary` is
    /// only serialized when true (historical wire shape).
    pub fn resolved(
        layer: impl Into<String>,
        identify_only: bool,
        emit: Option<String>,
        report_summary: bool,
        workspace_override: Option<String>,
    ) -> Self {
        Self {
            layer: layer.into(),
            identify_only,
            emit,
            report_summary: report_summary.then_some(true),
            workspace_override,
        }
    }

    pub fn layer(&self) -> &str {
        &self.layer
    }

    pub fn identify_only(&self) -> bool {
        self.identify_only
    }

    pub fn emit(&self) -> Option<&str> {
        self.emit.as_deref()
    }

    pub fn report_summary(&self) -> bool {
        self.report_summary.unwrap_or(false)
    }

    pub fn workspace_override(&self) -> Option<&str> {
        self.workspace_override.as_deref()
    }
}

impl LiftRequest {
    /// Minimal project-root lift: walk `source_paths` under `workspace_root`.
    ///
    /// This is the door focused tests use (`source_paths = ["."]`). CLI/census
    /// paths add surface/config/options via the builder methods.
    pub fn project(
        workspace_root: impl Into<PathBuf>,
        source_paths: impl IntoIterator<Item = impl Into<String>>,
    ) -> Self {
        Self {
            workspace_root: workspace_root.into(),
            source_paths: source_paths.into_iter().map(Into::into).collect(),
            surface: None,
            config_path: None,
            options: None,
            contract_bindings: None,
        }
    }

    pub fn with_surface(mut self, surface: impl Into<String>) -> Self {
        self.surface = Some(surface.into());
        self
    }

    pub fn with_config_path(mut self, config_path: impl Into<String>) -> Self {
        self.config_path = Some(config_path.into());
        self
    }

    pub fn with_options(mut self, options: LiftRequestOptions) -> Self {
        self.options = Some(options);
        self
    }

    pub fn with_contract_bindings(mut self, bindings: Vec<Value>) -> Self {
        if !bindings.is_empty() {
            self.contract_bindings = Some(bindings);
        }
        self
    }

    pub fn workspace_root(&self) -> &Path {
        &self.workspace_root
    }

    pub fn source_paths(&self) -> &[String] {
        &self.source_paths
    }

    pub fn surface(&self) -> Option<&str> {
        self.surface.as_deref()
    }

    pub fn config_path(&self) -> Option<&str> {
        self.config_path.as_deref()
    }

    pub fn options(&self) -> Option<&LiftRequestOptions> {
        self.options.as_ref()
    }

    /// Encode to the JSON object kits already parse. Used by mint path
    /// `Input::Spec` and CLI tests that still inspect the wire shape.
    pub fn to_wire_value(&self) -> Result<Value, serde_json::Error> {
        serde_json::to_value(self)
    }

    fn to_json_bytes(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(self)
    }
}

/// The unforgeable frontend handle. Private fields; the only minter is
/// `Kit::rendezvous`.
///
/// The enumeration connection owns its resident child and canonical-question
/// cache. Their validity window is the handle's lifetime: CLI keeps one for a
/// command, LSP keeps one for an analysis, and dropping the last clone closes
/// the child and discards all cached answers coherently. There is no global
/// resident pool and no entry-level invalidation path.
pub struct Kit {
    manifest: LiftManifest,
    declaration: KitDeclaration,
    initialize_response: Value,
    registry: KitRegistry,
    kit_name: String,
}

impl Kit {
    /// The ONLY way to mint a `Kit`. Takes the resolved manifest (the
    /// census's output) and performs a LIVE handshake before constructing
    /// anything: spawns `manifest.command`, runs `initialize` +
    /// `sugar.plugin.kit_declaration` + `shutdown` over its stdio, and
    /// requires a valid `KitDeclaration` back (`load_kit_declaration_with_command`
    /// already calls `KitDeclaration::validate`). Only after that
    /// round-trip succeeds does rendezvous register the `LiftKit` transport
    /// against `KitRegistry` (the path-algebra dispatch table, distinct
    /// from `libsugar::core::ComponentRegistry`'s verifier-backed
    /// `CompilerRegistry`) -- exactly the construction `dispatch_lift_path`
    /// used to do inline on every call (`lift_plugin.rs:346-360`);
    /// rendezvous does it once, here, and the result lives on the handle.
    /// A forged manifest pointing at a non-kit command (e.g. `/bin/false`)
    /// fails here with `RendezvousError::Handshake`, before any `Kit`
    /// exists.
    pub fn rendezvous(manifest: LiftManifest) -> Result<Kit, RendezvousError> {
        if manifest.command.is_empty() {
            return Err(RendezvousError::EmptyCommand(manifest.surface.clone()));
        }
        // The manifest's contract: working_dir arrives RESOLVED (absolute).
        // A relative dir would silently run the kit in whatever CWD this
        // process happens to have -- refuse loudly instead (answer the
        // "relative to what?" question ONCE, at the census that resolves it).
        if let Some(dir) = &manifest.working_dir {
            if dir.is_relative() {
                return Err(RendezvousError::RelativeWorkingDir {
                    surface: manifest.surface.clone(),
                    working_dir: dir.display().to_string(),
                });
            }
        }
        let handshake =
            load_kit_handshake_with_command(&manifest.command, manifest.working_dir.as_deref())
                .map_err(|source| RendezvousError::Handshake {
                    surface: manifest.surface.clone(),
                    source,
                })?;
        let declaration = handshake.declaration;
        let kit_name = format!("lift-{}", manifest.surface);
        let mut registry = KitRegistry::default();
        let mut lift_kit = LiftKit::new(
            manifest.dialect.clone(),
            manifest.surface.clone(),
            manifest.command.clone(),
            manifest.working_dir.clone(),
        );
        if let Some(method) = manifest.method.as_deref() {
            lift_kit = lift_kit.with_method(method);
        }
        registry.register(
            kit_name.clone(),
            lift_kit,
            ConformanceDeclaration::NonCarrier {
                reason: "lifts source bytes to DomainClaim; no target source produced",
            },
        );
        Ok(Kit {
            manifest,
            declaration,
            initialize_response: handshake.initialize_response,
            registry,
            kit_name,
        })
    }

    /// The kit's own declared identity, methods, and proof-resolution
    /// strategy, as answered by the live handshake in `rendezvous`.
    pub fn declaration(&self) -> &KitDeclaration {
        &self.declaration
    }

    /// Whether the live declaration advertises an RPC method. Callers must use
    /// this before choosing a protocol path whose method is not universal.
    pub fn supports_rpc_method(&self, method: &str) -> bool {
        declaration_advertises_rpc_method(&self.declaration, method)
    }

    pub fn initialize_response(&self) -> &Value {
        &self.initialize_response
    }

    /// `Kit::lift(request)`: folds `dispatch_lift_path`'s body (build request
    /// -> `Input::Source` -> `CorePath` -> `execute_path` -> terminal claim).
    ///
    /// `request` is a strong [`LiftRequest`] (#3855): free-form `Value` no
    /// longer types as a kit lift input. Wire JSON is produced here from the
    /// typed request so kit RPC params stay shape-stable.
    pub fn lift(&self, request: LiftRequest) -> Result<libsugar::core::DomainClaim, KitError> {
        let source = Input::Source {
            dialect: self.manifest.dialect.clone(),
            bytes: request.to_json_bytes().map_err(KitError::RequestEncoding)?,
        };
        let source_cid = address(&source);
        let mut inputs = HashMapInputCatalog::default();
        inputs.put(source_cid.clone(), source);
        let path_input = Input::Path(Box::new(CorePath {
            algebra: vec![PathAlgebra {
                name: "lift".to_string(),
                kit: self.kit_name.clone(),
                inputs: vec![source_cid],
                depends_on: vec![],
                verb: Verb::Transform,
            }],
        }));
        let chain = execute_path(&path_input, &self.registry, &inputs)?;
        Ok(chain.into_terminal_claim())
    }

    pub fn surface(&self) -> &str {
        &self.manifest.surface
    }

    /// Part 6: build the `tree::KitConn` an enumeration RPC needs to reach
    /// THIS kit's manifest command again for `workspace_root`. Crate-private
    /// -- `tree.rs`'s `impl Kit` block is the only external caller.
    pub(crate) fn enumerate_conn(&self, workspace_root: &Path) -> crate::tree::KitConn {
        crate::tree::KitConn {
            surface: self.manifest.surface.clone(),
            command: self.manifest.command.clone(),
            working_dir: self.manifest.working_dir.clone(),
            workspace_root: workspace_root.to_path_buf(),
            audit_frontier: false,
            allowed_broken_components: Vec::new(),
            transport: crate::kit_path::LiftPluginKit::new(
                self.manifest.surface.clone(),
                self.manifest.command.clone(),
                self.manifest.working_dir.clone(),
            )
            .with_method("sugar.enumerate"),
        }
    }

    /// SEAM 4 -- the testimony verb. Asks THIS kit (the one this handle
    /// rendezvous'd with) for its vendor dependency-proof catalog over
    /// `sugar.plugin.resolve_dependency_proofs`, decoded into typed,
    /// speaker-stamped `ProofBytes`. A kit that doesn't implement the
    /// method (or never answers) is `TestimonyOutcome::Unavailable` -- a
    /// LINK-class absence, not an error -- per `resolve::resolve_testimony`.
    ///
    /// `workspace_root` is the project being scanned for dependency proofs
    /// (the RPC's `project_root` param) -- distinct from `manifest.working_dir`
    /// (the spawned kit process's cwd), the same distinction
    /// `kit_dispatch::dependency_proofs_for_command` preserved.
    pub fn testimony(&self, workspace_root: &Path) -> Result<TestimonyResolution, TestimonyError> {
        resolve_testimony(
            &self.manifest.surface,
            &self.manifest.command,
            self.manifest.working_dir.as_deref(),
            workspace_root,
        )
    }

    /// SEAM 4 -- the source verb. Asks THIS kit to resolve a `SourceMemento`
    /// over `sugar.plugin.resolve_source_memento`, exact-or-refuse: CID
    /// drift on the kit's side of the membrane comes back as
    /// `SourceRefusal::Refused`, never a silently-empty answer.
    pub fn source(
        &self,
        workspace_root: &Path,
        memento: &SourceMemento,
    ) -> Result<ResolvedSource, SourceRefusal> {
        resolve_source(
            &self.manifest.surface,
            &self.manifest.command,
            self.manifest.working_dir.as_deref(),
            workspace_root,
            memento,
        )
    }
}

fn declaration_advertises_rpc_method(declaration: &KitDeclaration, method: &str) -> bool {
    declaration
        .rpc
        .methods
        .iter()
        .any(|declared| declared.name == method)
}

#[cfg(test)]
mod rendezvous_tests {
    use super::*;

    #[test]
    fn rpc_capability_query_distinguishes_enumerating_from_lift_only_kits() {
        let lift_only: KitDeclaration = serde_json::from_value(serde_json::json!({
            "kit": {"id": "lift-only", "language": "rust", "version": "1"},
            "rpc": {"methods": [{"name": "lift", "required": true}]},
            "proofResolution": {"strategy": "none"},
            "residueCategories": []
        }))
        .expect("fixture declaration");

        assert!(declaration_advertises_rpc_method(&lift_only, "lift"));
        assert!(!declaration_advertises_rpc_method(
            &lift_only,
            "sugar.enumerate"
        ));
    }

    /// The negative arm of unforgeability: a forged manifest pointing at a
    /// command that is not a kit must FAIL the live handshake -- no Kit is
    /// minted. This is the discrimination test for the doc's claim that
    /// holding a Kit proves a real kit process answered its declaration RPC.
    #[test]
    fn rendezvous_refuses_a_forged_manifest_to_a_non_kit() {
        let forged = LiftManifest::resolved(
            "forged",
            "forged",
            Dialect::Rust,
            vec!["/bin/false".to_string()],
            None,
            None,
        );
        match Kit::rendezvous(forged) {
            Err(RendezvousError::Handshake { surface, .. }) => {
                assert_eq!(surface, "forged");
            }
            Err(other) => panic!("expected Handshake refusal, got: {other:?}"),
            Ok(_) => panic!("a non-kit command must never mint a Kit"),
        }
    }

    /// A relative working_dir refuses before spawning: the manifest's
    /// contract is resolved-absolute (macroscope on #3854 -- a "." dir would
    /// silently run the kit in this process's CWD instead of the project).
    #[test]
    fn rendezvous_refuses_a_relative_working_dir() {
        let forged = LiftManifest::resolved(
            "relative",
            "relative",
            Dialect::Rust,
            vec!["/bin/false".to_string()],
            Some(PathBuf::from(".")),
            None,
        );
        assert!(matches!(
            Kit::rendezvous(forged),
            Err(RendezvousError::RelativeWorkingDir { .. })
        ));
    }

    /// Empty command refuses before spawning anything.
    #[test]
    fn rendezvous_refuses_an_empty_command() {
        let forged = LiftManifest::resolved("empty", "empty", Dialect::Rust, vec![], None, None);
        assert!(matches!(
            Kit::rendezvous(forged),
            Err(RendezvousError::EmptyCommand(_))
        ));
    }

    /// Wire shape for the minimal project door stays kit-compatible
    /// (`workspace_root` + non-empty `source_paths`; no Value blob at the
    /// Kit boundary).
    #[test]
    fn lift_request_project_wire_shape() {
        let request = LiftRequest::project("/tmp/proj", ["."]);
        let wire = request.to_wire_value().expect("LiftRequest serializes");
        assert_eq!(wire["workspace_root"].as_str(), Some("/tmp/proj"));
        assert_eq!(
            wire["source_paths"]
                .as_array()
                .expect("source_paths array")
                .len(),
            1
        );
        assert_eq!(wire["source_paths"][0].as_str(), Some("."));
        assert!(wire.get("surface").is_none());
        assert!(wire.get("options").is_none());
    }

    /// CLI-shaped request carries surface/options with historical camelCase
    /// option keys so kit RPC params do not drift under the type.
    #[test]
    fn lift_request_cli_options_preserve_wire_keys() {
        let request = LiftRequest::project("/ws", ["."])
            .with_surface("rust")
            .with_config_path(".sugar/config.toml")
            .with_options(LiftRequestOptions::resolved(
                "library-bindings",
                false,
                Some("ir-document".to_string()),
                true,
                Some("vendor/dep".to_string()),
            ));
        let wire = request.to_wire_value().expect("serialize");
        assert_eq!(wire["surface"].as_str(), Some("rust"));
        assert_eq!(wire["config_path"].as_str(), Some(".sugar/config.toml"));
        assert_eq!(wire["options"]["layer"].as_str(), Some("library-bindings"));
        assert_eq!(wire["options"]["identifyOnly"].as_bool(), Some(false));
        assert_eq!(wire["options"]["emit"].as_str(), Some("ir-document"));
        assert_eq!(wire["options"]["reportSummary"].as_bool(), Some(true));
        assert_eq!(
            wire["options"]["workspaceOverride"].as_str(),
            Some("vendor/dep")
        );
    }
}
