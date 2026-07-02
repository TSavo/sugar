use std::ffi::OsString;
use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use serial_test::serial;
use sugar_cli::component_plan::{plan_workspace, DiagnosticLevel};
use tempfile::TempDir;

struct EnvGuard {
    key: &'static str,
    previous: Option<OsString>,
}

impl EnvGuard {
    fn set(key: &'static str, value: impl AsRef<std::ffi::OsStr>) -> Self {
        let previous = std::env::var_os(key);
        std::env::set_var(key, value);
        Self { key, previous }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        if let Some(previous) = self.previous.take() {
            std::env::set_var(self.key, previous);
        } else {
            std::env::remove_var(self.key);
        }
    }
}

struct FakeComponent {
    root: TempDir,
    pid_file: PathBuf,
    transcript: PathBuf,
}

impl FakeComponent {
    fn hung(name: &str) -> Self {
        Self::new(
            name,
            r#"printf '%s\n' "$$" > "$1"
IFS= read -r line
printf '%s\n' "$line" >> "$2"
while :; do
  sleep 60
done
"#,
        )
    }

    fn healthy(name: &str) -> Self {
        Self::new(
            name,
            r#"printf '%s\n' "$$" > "$1"
while IFS= read -r line; do
  printf '%s\n' "$line" >> "$2"
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"healthy-component","protocol_version":"sugar-component/1","capabilities":{}}}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"decision":"claim","plugins":[{"name":"fake-lift","kind":"lift","surface":"fake-surface","emit":"ir-document"}],"lift_manifests":[{"surface":"fake-surface","name":"fake-lift","command":["/bin/echo"],"working_dir":"."}],"diagnostics":[{"level":"info","message":"healthy component planned"}]}}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
        )
    }

    fn new(name: &str, body: &str) -> Self {
        let root = TempDir::new().expect("component root tempdir");
        let component_dir = root.path().join(name);
        fs::create_dir_all(&component_dir).expect("component dir");
        let script = component_dir.join("component.sh");
        let pid_file = component_dir.join("component.pid");
        let transcript = component_dir.join("transcript.jsonl");
        write_executable(&script, &format!("#!/bin/sh\nset -eu\n{body}"));
        fs::write(
            component_dir.join("manifest.toml"),
            format!(
                "name = \"{name}\"\nprotocol_version = \"sugar-component/1\"\ncommand = [\"sh\", {}, {}, {}]\n",
                toml_string(&script.display().to_string()),
                toml_string(&pid_file.display().to_string()),
                toml_string(&transcript.display().to_string())
            ),
        )
        .expect("write component manifest");
        Self {
            root,
            pid_file,
            transcript,
        }
    }

    fn component_path(&self) -> &Path {
        self.root.path()
    }

    fn pid(&self) -> u32 {
        let text = fs::read_to_string(&self.pid_file)
            .unwrap_or_else(|error| panic!("read {}: {error}", self.pid_file.display()));
        text.trim().parse().expect("component pid")
    }

    fn transcript(&self) -> String {
        fs::read_to_string(&self.transcript)
            .unwrap_or_else(|error| panic!("read {}: {error}", self.transcript.display()))
    }
}

fn write_executable(path: &Path, contents: &str) {
    {
        let mut file = fs::File::create(path).expect("create executable");
        file.write_all(contents.as_bytes())
            .expect("write executable");
        file.sync_all().expect("sync executable");
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(path).expect("metadata").permissions();
        perms.set_mode(0o755);
        fs::set_permissions(path, perms).expect("chmod executable");
    }
}

fn toml_string(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}

fn assert_pid_reaped(pid: u32) {
    for _ in 0..20 {
        let output = Command::new("ps")
            .args(["-o", "stat=", "-p", &pid.to_string()])
            .output()
            .expect("ps");
        let stat = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !output.status.success() || stat.is_empty() {
            return;
        }
        assert!(
            !stat.contains('Z'),
            "component process {pid} was left as a zombie: {stat}"
        );
        std::thread::sleep(Duration::from_millis(100));
    }
    panic!("component process {pid} was still present after timeout cleanup");
}

#[test]
#[serial]
fn hung_component_times_out_with_diagnostic() {
    let project = TempDir::new().expect("project tempdir");
    let component = FakeComponent::hung("hung-component");
    let _home = EnvGuard::set("HOME", project.path().join("home"));
    let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", component.component_path());
    let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

    let started = Instant::now();
    let plan = plan_workspace(project.path());
    let elapsed = started.elapsed();

    assert!(
        elapsed < Duration::from_secs(5),
        "plan_workspace should return within about 2x the configured timeout; elapsed={elapsed:?}"
    );
    let diagnostic = plan
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.message.contains("hung-component"))
        .unwrap_or_else(|| panic!("missing component diagnostic: {:?}", plan.diagnostics));
    assert_eq!(diagnostic.level, DiagnosticLevel::Warning);
    assert!(
        diagnostic.message.contains("timed out") && diagnostic.message.contains("initialize"),
        "diagnostic should name the blown initialize rendezvous: {:?}",
        diagnostic
    );
    assert_pid_reaped(component.pid());
}

#[test]
#[serial]
fn healthy_component_plans() {
    let project = TempDir::new().expect("project tempdir");
    let component = FakeComponent::healthy("healthy-component");
    let _home = EnvGuard::set("HOME", project.path().join("home"));
    let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", component.component_path());
    let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

    let plan = plan_workspace(project.path());

    assert!(
        plan.plugins
            .iter()
            .any(|plugin| plugin.surface == "fake-surface"),
        "planned plugins should include fake-surface: {:?}",
        plan.plugins
    );
    assert!(
        plan.lift_manifests
            .iter()
            .any(|manifest| manifest.surface == "fake-surface"),
        "planned lift manifests should include fake-surface: {:?}",
        plan.lift_manifests
    );
    assert!(
        plan.diagnostics
            .iter()
            .any(|diagnostic| diagnostic.level == DiagnosticLevel::Info
                && diagnostic.message == "healthy component planned"),
        "component diagnostics should be preserved: {:?}",
        plan.diagnostics
    );

    let transcript = component.transcript();
    assert!(transcript.contains(r#""method":"initialize""#));
    assert!(transcript.contains(r#""method":"sugar.component.plan""#));
    assert!(transcript.contains(r#""method":"shutdown""#));
    assert_pid_reaped(component.pid());
}
