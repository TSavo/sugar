use std::ffi::OsString;
use std::fs;
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use serde_json::Value;
use serial_test::serial;
use sugar_cli::component_plan::{plan_workspace, DiagnosticLevel, PlanIntent};
use tempfile::TempDir;

fn sugar_bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sugar"))
}

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

    fn crashed(name: &str) -> Self {
        Self::new(
            name,
            r#"printf '%s\n' "$$" > "$1"
exit 1
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

    fn declining(name: &str, language: &str) -> Self {
        Self::new_with_args(
            name,
            r#"printf '%s\n' "$$" > "$1"
language="$3"
while IFS= read -r line; do
  printf '%s\n' "$line" >> "$2"
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"declining-component","protocol_version":"sugar-component/1","capabilities":{}}}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '{"jsonrpc":"2.0","id":2,"result":{"decision":"decline","languages":["%s"],"reason":"component explicitly declined workspace"}}\n' "$language"
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
            &[language.to_string()],
        )
    }

    fn rust_claiming(name: &str, lifter: &Path) -> Self {
        Self::new_with_args(
            name,
            r#"printf '%s\n' "$$" > "$1"
lifter="$3"
while IFS= read -r line; do
  printf '%s\n' "$line" >> "$2"
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"rust-claiming-component","protocol_version":"sugar-component/1","capabilities":{}}}'
      ;;
    *'"method":"sugar.component.plan"'*)
      printf '{"jsonrpc":"2.0","id":2,"result":{"decision":"claim","plugins":[{"name":"rust-lift","kind":"lift","surface":"rust","emit":"ir-document"}],"lift_manifests":[{"surface":"rust","name":"rust-lift","command":["sh","%s"],"working_dir":"."}],"diagnostics":[{"level":"info","message":"rust component planned"}]}}\n' "$lifter"
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
            &[lifter.display().to_string()],
        )
    }

    fn new(name: &str, body: &str) -> Self {
        Self::new_with_args(name, body, &[])
    }

    fn new_with_args(name: &str, body: &str, extra_args: &[String]) -> Self {
        let root = TempDir::new().expect("component root tempdir");
        let component_dir = root.path().join(name);
        fs::create_dir_all(&component_dir).expect("component dir");
        let script = component_dir.join("component.sh");
        let pid_file = component_dir.join("component.pid");
        let transcript = component_dir.join("transcript.jsonl");
        write_executable(&script, &format!("#!/bin/sh\nset -eu\n{body}"));
        let mut command_args = vec![
            "sh".to_string(),
            script.display().to_string(),
            pid_file.display().to_string(),
            transcript.display().to_string(),
        ];
        command_args.extend(extra_args.iter().cloned());
        let manifest_command = command_args
            .iter()
            .map(|arg| toml_string(arg))
            .collect::<Vec<_>>()
            .join(", ");
        fs::write(
            component_dir.join("manifest.toml"),
            format!(
                "name = \"{name}\"\nprotocol_version = \"sugar-component/1\"\ncommand = [{manifest_command}]\n",
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

fn fake_rust_lifter(root: &Path) -> PathBuf {
    let script = root.join("fake-rust-lifter.sh");
    write_executable(
        &script,
        r#"#!/bin/sh
set -eu
while IFS= read -r line; do
  case "$line" in
    *'"method":"initialize"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":1,"result":{"name":"fake-rust-lifter","protocol_version":"pep/1.7.0","capabilities":{"surfaces":["rust"]}}}'
      ;;
    *'"method":"lift"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":2,"result":{"kind":"ir-document","sourceLanguage":"rust","ir":[],"diagnostics":[]}}'
      ;;
    *'"method":"shutdown"'*)
      printf '%s\n' '{"jsonrpc":"2.0","id":3,"result":null}'
      exit 0
      ;;
  esac
done
"#,
    );
    script
}

fn write_rust_project(root: &Path) {
    fs::write(
        root.join("Cargo.toml"),
        "[package]\nname = \"component-plan-rust-fixture\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
    )
    .expect("write Cargo.toml");
    let src = root.join("src");
    fs::create_dir_all(&src).expect("create src");
    fs::write(src.join("lib.rs"), "pub fn id(x: i64) -> i64 { x }\n").expect("write lib.rs");
}

fn component_path(components: &[&FakeComponent]) -> OsString {
    std::env::join_paths(
        components
            .iter()
            .map(|component| component.component_path()),
    )
    .expect("join component path")
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

fn first_component_plan_intent(component: &FakeComponent) -> String {
    let transcript = component.transcript();
    for line in transcript.lines() {
        let value: Value = serde_json::from_str(line).unwrap_or_else(|error| {
            panic!("component transcript line was not JSON: {error}: {line}")
        });
        if value.get("method").and_then(Value::as_str) == Some("sugar.component.plan") {
            return value
                .pointer("/params/intent")
                .and_then(Value::as_str)
                .unwrap_or_else(|| panic!("component plan request missing intent: {line}"))
                .to_string();
        }
    }
    panic!("component transcript had no component-plan request: {transcript}");
}

fn component_plan_intent_from_cli_verb(verb: &str) -> String {
    let project = TempDir::new().expect("project tempdir");
    write_rust_project(project.path());
    let lifter = fake_rust_lifter(project.path());
    let component = FakeComponent::rust_claiming(&format!("{verb}-intent-component"), &lifter);

    let mut command = Command::new(sugar_bin());
    match verb {
        "lift" => {
            command.arg("lift").arg(project.path());
        }
        "prove" => {
            command.arg("prove").arg(project.path());
        }
        "verify" => {
            command.arg("verify").arg("--project").arg(project.path());
        }
        other => panic!("unsupported CLI verb for component-plan intent test: {other}"),
    }
    let output = command
        .env("HOME", project.path().join("home"))
        .env("SUGAR_COMPONENT_PATH", component.component_path())
        .env("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2")
        .output()
        .unwrap_or_else(|error| panic!("run sugar {verb}: {error}"));

    let transcript = component.transcript();
    assert!(
        transcript.contains(r#""method":"sugar.component.plan""#),
        "sugar {verb} should query the component plan\nstatus: {}\nstdout:\n{}\nstderr:\n{}\ntranscript:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
        transcript
    );
    assert_pid_reaped(component.pid());
    first_component_plan_intent(&component)
}

#[test]
#[serial]
fn component_plan_intents_follow_cli_verb() {
    let actual = [
        component_plan_intent_from_cli_verb("lift"),
        component_plan_intent_from_cli_verb("prove"),
        component_plan_intent_from_cli_verb("verify"),
    ];

    assert_eq!(actual, ["lift", "prove", "verify"]);
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
    let plan = plan_workspace(project.path(), PlanIntent::Lift);
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
    assert_eq!(diagnostic.level, DiagnosticLevel::Error);
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

    let plan = plan_workspace(project.path(), PlanIntent::Lift);

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

#[test]
#[serial]
fn crashed_component_fails_the_run() {
    let project = TempDir::new().expect("project tempdir");
    write_rust_project(project.path());
    let lifter = fake_rust_lifter(project.path());
    let crashed = FakeComponent::crashed("python-crashed-component");
    let rust = FakeComponent::rust_claiming("rust-claiming-component", &lifter);
    let joined_components = component_path(&[&crashed, &rust]);
    let _home = EnvGuard::set("HOME", project.path().join("home"));
    let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", &joined_components);
    let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

    let plan = plan_workspace(project.path(), PlanIntent::Lift);
    let diagnostic = plan
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.message.contains("python-crashed-component"))
        .unwrap_or_else(|| panic!("missing crash diagnostic: {:?}", plan.diagnostics));
    assert_eq!(diagnostic.level, DiagnosticLevel::Error);
    assert!(diagnostic.message.contains("manifest.toml"));
    assert!(diagnostic.message.contains("command"));
    assert!(diagnostic.message.contains("closed stdout") || diagnostic.message.contains("write"));
    assert_pid_reaped(crashed.pid());

    let output = Command::new(sugar_bin())
        .arg("lift")
        .arg(project.path())
        .env("HOME", project.path().join("home"))
        .env("SUGAR_COMPONENT_PATH", &joined_components)
        .env("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2")
        .output()
        .expect("run sugar lift");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        !output.status.success(),
        "crashed component must abort the lift run\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        stderr.contains("python-crashed-component"),
        "stderr should name the crashed component\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
}

#[test]
#[serial]
fn declining_component_is_not_an_error() {
    let project = TempDir::new().expect("project tempdir");
    fs::write(project.path().join("demo.py"), "def f(x):\n    return x\n").expect("write python");
    let component = FakeComponent::declining("python-declining-component", "python");
    let _home = EnvGuard::set("HOME", project.path().join("home"));
    let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", component.component_path());
    let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

    let plan = plan_workspace(project.path(), PlanIntent::Lift);

    assert!(
        !plan
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.level == DiagnosticLevel::Error),
        "a protocol decline should not be an error: {:?}",
        plan.diagnostics
    );
    assert_pid_reaped(component.pid());
}

#[test]
#[serial]
fn unclaimed_census_language_is_an_error() {
    let project = TempDir::new().expect("project tempdir");
    write_rust_project(project.path());
    fs::write(project.path().join("demo.py"), "def f(x):\n    return x\n").expect("write python");
    let lifter = fake_rust_lifter(project.path());
    let rust = FakeComponent::rust_claiming("rust-claiming-component", &lifter);
    let _home = EnvGuard::set("HOME", project.path().join("home"));
    let _component_path = EnvGuard::set("SUGAR_COMPONENT_PATH", rust.component_path());
    let _timeout = EnvGuard::set("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2");

    let plan = plan_workspace(project.path(), PlanIntent::Lift);

    assert!(
        plan.diagnostics.iter().any(|diagnostic| {
            diagnostic.level == DiagnosticLevel::Error
                && diagnostic.message.to_ascii_lowercase().contains("python")
        }),
        "a Python census hit with no claimer or decliner must be an error: {:?}",
        plan.diagnostics
    );
    assert_pid_reaped(rust.pid());
}

#[test]
#[serial]
fn allow_failed_components_downgrades() {
    let project = TempDir::new().expect("project tempdir");
    write_rust_project(project.path());
    let lifter = fake_rust_lifter(project.path());
    let crashed = FakeComponent::crashed("python-crashed-component");
    let rust = FakeComponent::rust_claiming("rust-claiming-component", &lifter);
    let joined_components = component_path(&[&crashed, &rust]);

    let output = Command::new(sugar_bin())
        .arg("lift")
        .arg("--allow-failed-components")
        .arg(project.path())
        .env("HOME", project.path().join("home"))
        .env("SUGAR_COMPONENT_PATH", &joined_components)
        .env("SUGAR_COMPONENT_PLAN_TIMEOUT_SECS", "2")
        .output()
        .expect("run sugar lift with allow-failed-components");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        output.status.success(),
        "--allow-failed-components should let the run proceed\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        stderr.contains("warning") && stderr.contains("python-crashed-component"),
        "downgraded failure should be printed as a warning\nstdout:\n{stdout}\nstderr:\n{stderr}"
    );
    assert!(
        stdout.contains(r#""kind":"ir-document""#) || stdout.contains("\"kind\": \"ir-document\"")
    );
}
