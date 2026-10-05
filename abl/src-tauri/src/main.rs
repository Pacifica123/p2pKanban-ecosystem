mod application;
mod desktop_api;
mod domain;
mod infrastructure;
mod navigation_policy;

use std::{io::Write as _, net::Ipv4Addr, path::PathBuf, sync::Arc, time::Duration};

use application::{
    import::ImportService,
    recovery::RecoveryService,
    integration::{IntegrationAdapter, IntegrationService},
    lan_bridge::{LanBridgePayloadHandler, LanBridgeRuntime, LanBridgeService},
    parity::{ParityService, RandomParityIds},
    planner::{PlannerService, RandomPlannerIds},
    workspace::{RandomUuidGenerator, WorkspaceService},
};
use infrastructure::{
    linux::{
        instance::{self, InstanceRole, SecondaryInstance, ACTIVATE_MAIN_V1, MAX_ACTIVATION_PAYLOAD_BYTES},
        integration::LinuxIntegrationAdapter,
        lan_bridge::LinuxLanBridgeRuntime,
        recovery_lock,
        secrets::bootstrap_vault,
        xdg::{DesktopPaths, XdgEnvironment},
    },
    sqlite::{
        import::SqliteImportRepository, parity::SqliteParityRepository,
        repository::SqlitePlannerRepository, recovery::SqliteRecoveryBackend,
        workspace::SqliteWorkspaceCatalog,
    },
};
use crate::domain::{
    integration::{decode_deep_link_activation, encode_deep_link_activation, parse_deep_link, DeepLinkIntent},
    lan_bridge::{seal_lan_bridge_payload, LanBridgeLifecycle, LanBridgeStartRequest, LAN_BRIDGE_NONCE_BYTES, LAN_BRIDGE_TOKEN_BYTES},
};
use tauri::{
    webview::{NewWindowResponse, WebviewWindowBuilder},
    Manager, WebviewUrl,
};



#[derive(Debug, Clone, PartialEq, Eq)]
enum RecoveryCliCommand {
    Doctor { json: bool },
    Backup { json: bool },
    Backups { json: bool },
    SafeMode { json: bool },
    SafeExport { destination: PathBuf, overwrite: bool, json: bool },
    Restore { backup_id: String, confirmed: bool, json: bool },
}

fn parse_recovery_cli(args: &[String]) -> Result<Option<RecoveryCliCommand>, String> {
    let Some(command) = args.first().map(String::as_str) else {
        return Ok(None);
    };
    let only_json = |rest: &[String]| -> Result<bool, String> {
        if rest.is_empty() {
            return Ok(false);
        }
        if rest.len() == 1 && rest[0] == "--json" {
            return Ok(true);
        }
        Err("recovery command accepts only optional --json".to_owned())
    };
    match command {
        "doctor" => Ok(Some(RecoveryCliCommand::Doctor { json: only_json(&args[1..])? })),
        "backup" => Ok(Some(RecoveryCliCommand::Backup { json: only_json(&args[1..])? })),
        "backups" => Ok(Some(RecoveryCliCommand::Backups { json: only_json(&args[1..])? })),
        "safe-mode" => Ok(Some(RecoveryCliCommand::SafeMode { json: only_json(&args[1..])? })),
        "safe-export" => {
            let destination = args
                .get(1)
                .ok_or_else(|| "safe-export requires a destination path".to_owned())?;
            let mut overwrite = false;
            let mut json = false;
            for option in &args[2..] {
                match option.as_str() {
                    "--force" => overwrite = true,
                    "--json" => json = true,
                    _ => return Err(format!("unsupported safe-export option: {option}")),
                }
            }
            Ok(Some(RecoveryCliCommand::SafeExport {
                destination: PathBuf::from(destination),
                overwrite,
                json,
            }))
        }
        "restore" => {
            let backup_id = args.get(1).ok_or_else(|| "restore requires a backup id".to_owned())?;
            let mut confirmed = false;
            let mut json = false;
            for option in &args[2..] {
                match option.as_str() {
                    "--yes" => confirmed = true,
                    "--json" => json = true,
                    _ => return Err(format!("unsupported restore option: {option}")),
                }
            }
            Ok(Some(RecoveryCliCommand::Restore {
                backup_id: backup_id.clone(),
                confirmed,
                json,
            }))
        }
        _ => Ok(None),
    }
}

fn print_doctor_human(report: &crate::domain::recovery::DoctorReport) {
    println!("p2pKanban doctor");
    println!("profile: {}", report.profile_database);
    println!("safe mode required: {}", report.safe_mode_required);
    if let Some(schema) = report.schema_version {
        println!("schema: {schema}");
    }
    for check in &report.checks {
        println!("- {:?} {}: {}", check.level, check.id, check.message);
    }
}

fn run_recovery_cli(
    command: RecoveryCliCommand,
    prepared: &infrastructure::linux::xdg::PreparedDesktopPaths,
) -> Result<(), String> {
    let _exclusive = recovery_lock::acquire(prepared)
        .map_err(|err| format!("unable to acquire recovery profile lock: {err:?}"))?
        .ok_or_else(|| "profile is currently owned by another p2pKanban process; close it before recovery".to_owned())?;
    let service = RecoveryService::new(Box::new(SqliteRecoveryBackend::new(
        prepared.paths.profile.clone(),
    )));

    match command {
        RecoveryCliCommand::Doctor { json } => {
            let report = service.doctor().map_err(|err| format!("doctor failed: {err:?}"))?;
            if json {
                println!("{}", serde_json::to_string_pretty(&report).map_err(|err| err.to_string())?);
            } else {
                print_doctor_human(&report);
            }
        }
        RecoveryCliCommand::Backup { json } => {
            let manifest = service
                .create_manual_backup()
                .map_err(|err| format!("backup failed: {err:?}"))?;
            if json {
                println!("{}", serde_json::to_string_pretty(&manifest).map_err(|err| err.to_string())?);
            } else {
                println!("verified backup created: {}", manifest.backup_id);
                println!("sha256: {}", manifest.database_sha256);
            }
        }
        RecoveryCliCommand::Backups { json } => {
            let backups = service.list_backups().map_err(|err| format!("backup listing failed: {err:?}"))?;
            if json {
                println!("{}", serde_json::to_string_pretty(&backups).map_err(|err| err.to_string())?);
            } else if backups.is_empty() {
                println!("no restore points found");
            } else {
                for backup in backups {
                    println!(
                        "{} verified={} schema={:?} reason={}",
                        backup.backup_id,
                        backup.verified,
                        backup.schema_version,
                        backup.reason.unwrap_or_else(|| "unknown".to_owned())
                    );
                }
            }
        }
        RecoveryCliCommand::SafeMode { json } => {
            let doctor = service.doctor().map_err(|err| format!("safe-mode doctor failed: {err:?}"))?;
            let backups = service.list_backups().map_err(|err| format!("safe-mode backup listing failed: {err:?}"))?;
            if json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&serde_json::json!({
                        "mode": "safe-mode",
                        "networkEnabled": false,
                        "webviewStarted": false,
                        "migrationsEnabled": false,
                        "doctor": doctor,
                        "backups": backups,
                    }))
                    .map_err(|err| err.to_string())?
                );
            } else {
                println!("p2pKanban SAFE MODE (CLI/native recovery plane)");
                println!("network: disabled; WebView: not started; automatic migrations: disabled");
                print_doctor_human(&doctor);
                println!("verified restore points:");
                for backup in backups.into_iter().filter(|backup| backup.verified) {
                    println!("- {} ({})", backup.backup_id, backup.reason.unwrap_or_else(|| "unknown".to_owned()));
                }
                println!("logical planner export: p2pkanban safe-export <path.json>");
                println!("restore with: p2pkanban restore <backup-id> --yes");
            }
        }
        RecoveryCliCommand::SafeExport { destination, overwrite, json } => {
            let report = service
                .export_logical(&destination, overwrite)
                .map_err(|err| format!("safe logical export failed: {err:?}"))?;
            if json {
                println!("{}", serde_json::to_string_pretty(&report).map_err(|err| err.to_string())?);
            } else {
                println!("logical recovery export written: {}", report.path);
                println!("sha256: {}", report.sha256);
                println!("rows: {} across {} table(s)", report.row_count, report.table_count);
                println!("note: this is a recovery/salvage artifact, not p2p_planner_bundle v1");
            }
        }
        RecoveryCliCommand::Restore { backup_id, confirmed, json } => {
            if !confirmed {
                return Err("restore is destructive; rerun with --yes after reviewing `p2pkanban backups`".to_owned());
            }
            let report = service
                .restore(&backup_id)
                .map_err(|err| format!("restore failed: {err:?}"))?;
            if json {
                println!("{}", serde_json::to_string_pretty(&report).map_err(|err| err.to_string())?);
            } else {
                println!("restored verified backup: {}", report.backup_id);
                println!("schema: {}", report.restored_schema_version);
                if let Some(path) = report.quarantine_path {
                    println!("previous profile quarantined at: {path}");
                }
            }
        }
    }
    Ok(())
}

fn startup_deep_link() -> Result<Option<DeepLinkIntent>, String> {
    let mut found = None;
    for argument in std::env::args().skip(1) {
        if argument == "--integration-capabilities-json" {
            continue;
        }
        if !argument.starts_with("p2pkanban:") {
            continue;
        }
        if found.is_some() {
            return Err("only one p2pkanban deep link may be supplied per launch".to_owned());
        }
        found = Some(
            parse_deep_link(&argument)
                .map_err(|error| format!("invalid p2pkanban deep link: {error:?}"))?,
        );
    }
    Ok(found)
}

fn integration_probe_requested() -> bool {
    std::env::args().skip(1).any(|argument| argument == "--integration-capabilities-json")
}


fn lan_bridge_host_probe_requested() -> bool {
    std::env::args().skip(1).any(|argument| argument == "--lan-bridge-host-probe")
}

fn run_lan_bridge_host_probe() -> Result<(), String> {
    if std::env::var("P2PKANBAN_UTS_LAN_BRIDGE_PROBE").ok().as_deref() != Some("1") {
        return Err("LAN bridge host probe is reserved for UserTestSpace verification".to_owned());
    }
    let runtime = LinuxLanBridgeRuntime::host_probe();
    let request = LanBridgeStartRequest::validated(&Ipv4Addr::LOCALHOST.to_string(), 30)
        .map_err(|error| format!("invalid host-probe request: {error:?}"))?;
    let mut token = [0_u8; LAN_BRIDGE_TOKEN_BYTES];
    let mut nonce = [0_u8; LAN_BRIDGE_NONCE_BYTES];
    getrandom::fill(&mut token).map_err(|_| "host-probe randomness unavailable".to_owned())?;
    getrandom::fill(&mut nonce).map_err(|_| "host-probe randomness unavailable".to_owned())?;
    let payload = br#"{"kind":"a14-host-probe"}"#;
    let envelope = seal_lan_bridge_payload(payload, &token, &nonce)
        .map_err(|error| format!("unable to seal host-probe payload: {error:?}"))?;
    let handler: LanBridgePayloadHandler = Arc::new(|plaintext| {
        if plaintext == br#"{"kind":"a14-host-probe"}"# {
            Ok(r#"{"status":"accepted","probe":"a14"}"#.to_owned())
        } else {
            Err("unexpected-host-probe-payload".to_owned())
        }
    });
    let handle = runtime
        .start(request, token, handler)
        .map_err(|error| format!("unable to start host-probe bridge: {error:?}"))?;
    let initial = handle.status();
    let endpoint = initial.endpoint.clone().ok_or_else(|| "host-probe endpoint missing".to_owned())?;
    println!(
        "{}",
        serde_json::json!({
            "protocol": "p2p-kanban-lan-bridge/1",
            "endpoint": endpoint,
            "envelope": String::from_utf8(envelope).map_err(|_| "host-probe envelope was not UTF-8 JSON".to_owned())?,
            "expiresAtUnix": initial.expires_at_unix,
        })
    );
    std::io::stdout().flush().map_err(|error| format!("unable to flush host-probe descriptor: {error}"))?;

    for _ in 0..200 {
        std::thread::sleep(Duration::from_millis(50));
        let status = handle.status();
        match status.lifecycle {
            LanBridgeLifecycle::Completed => return Ok(()),
            LanBridgeLifecycle::Failed | LanBridgeLifecycle::Expired | LanBridgeLifecycle::Stopped => {
                return Err(format!("host-probe bridge terminated before acceptance: {:?} {:?}", status.lifecycle, status.last_result));
            }
            LanBridgeLifecycle::Listening => {}
        }
    }
    let _ = handle.stop();
    Err("host-probe bridge was not consumed within 10 seconds".to_owned())
}

fn print_integration_probe(prepared: &infrastructure::linux::xdg::PreparedDesktopPaths) {
    let adapter = LinuxIntegrationAdapter::new(prepared.activation_socket().is_some());
    let capabilities = adapter.detect();
    println!(
        "{}",
        serde_json::json!({
            "sessionType": capabilities.session.as_str(),
            "desktop": capabilities.desktop.unwrap_or_else(|| "unknown".to_owned()),
            "sessionBus": capabilities.session_bus.as_str(),
            "notifications": capabilities.notifications.as_str(),
            "statusNotifier": capabilities.status_notifier.as_str(),
            "portal": capabilities.portal.as_str(),
            "runtimeActivation": capabilities.runtime_activation.as_str(),
            "trayLifecycle": "disabled",
            "systemdUserService": "disabled",
        })
    );
}

fn run() -> Result<(), String> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    let recovery_command = parse_recovery_cli(&args)?;
    let startup_deep_link = startup_deep_link()?;
    let prepared = DesktopPaths::resolve(&XdgEnvironment::current(), "default")
        .map_err(|err| format!("unable to resolve XDG profile paths: {err:?}"))?
        .prepare()
        .map_err(|err| format!("unable to prepare XDG profile paths: {err:?}"))?;

    if let Some(command) = recovery_command {
        return run_recovery_cli(command, &prepared);
    }
    if integration_probe_requested() {
        print_integration_probe(&prepared);
        return Ok(());
    }
    if lan_bridge_host_probe_requested() {
        return run_lan_bridge_host_probe();
    }

    let mut primary = match instance::acquire(&prepared)
        .map_err(|err| format!("unable to acquire profile instance control: {err:?}"))?
    {
        InstanceRole::Primary(primary) => primary,
        InstanceRole::Secondary(SecondaryInstance::Routed) => {
            if let Some(intent) = &startup_deep_link {
                let payload = encode_deep_link_activation(intent);
                if !instance::route_payload(&prepared, &payload) {
                    return Err("primary instance was activated but validated deep-link routing failed".to_owned());
                }
                eprintln!("p2pKanban is already running; validated deep link routed to the primary instance");
            } else {
                eprintln!("p2pKanban is already running; activation routed to the primary instance");
            }
            return Ok(());
        }
        InstanceRole::Secondary(SecondaryInstance::RoutingUnavailable) => {
            eprintln!(
                "p2pKanban is already running; writer ownership is protected but XDG runtime activation routing is unavailable"
            );
            return Ok(());
        }
    };

    let recovery_preflight = RecoveryService::new(Box::new(SqliteRecoveryBackend::new(
        prepared.paths.profile.clone(),
    )));
    let recovery_report = recovery_preflight
        .doctor()
        .map_err(|err| format!("profile recovery preflight failed: {err:?}"))?;
    if recovery_report.safe_mode_required {
        print_doctor_human(&recovery_report);
        return Err("profile requires recovery; run `p2pkanban safe-mode` before normal startup".to_owned());
    }
    if let Some(snapshot) = recovery_preflight
        .create_pre_migration_backup()
        .map_err(|err| format!("unable to create verified pre-migration recovery point: {err:?}"))?
    {
        eprintln!(
            "p2pKanban recovery: verified pre-migration snapshot {} created before schema write",
            snapshot.backup_id
        );
    }

    let workspace_repository = SqliteWorkspaceCatalog::open(&prepared.paths.profile)
        .map_err(|err| format!("unable to open durable workspace catalog: {err:?}"))?;
    let workspace_service = WorkspaceService::new(
        Box::new(workspace_repository),
        Box::new(RandomUuidGenerator),
    );
    let planner_repository = SqlitePlannerRepository::open(&prepared.paths.profile)
        .map_err(|err| format!("unable to open durable planner repository: {err:?}"))?;
    let planner_service = PlannerService::new(
        Box::new(planner_repository),
        Box::new(RandomPlannerIds),
    );
    let vault_service = Arc::new(bootstrap_vault(&prepared.paths.profile, "default"));
    let import_repository = SqliteImportRepository::open(&prepared.paths.profile)
        .map_err(|err| format!("unable to open durable import repository: {err:?}"))?;
    let import_service = Arc::new(ImportService::new(Box::new(import_repository)));
    let parity_repository = SqliteParityRepository::open(&prepared.paths.profile)
        .map_err(|err| format!("unable to open durable parity repository: {err:?}"))?;
    let parity_service = ParityService::new(
        Box::new(parity_repository),
        Box::new(RandomParityIds),
    );
    let integration_service = IntegrationService::new(Box::new(LinuxIntegrationAdapter::new(
        prepared.activation_socket().is_some(),
    )));
    let lan_bridge_service = LanBridgeService::new(
        Box::new(LinuxLanBridgeRuntime::production()),
        Arc::clone(&import_service),
        Arc::clone(&vault_service),
    );
    if let Some(intent) = startup_deep_link {
        integration_service.enqueue_deep_link(intent);
    }

    let activation_receiver = primary.take_activation_receiver();
    let diagnostics = prepared.diagnostics();

    tauri::Builder::default()
        .manage(primary)
        .manage(diagnostics)
        .manage(application::ApplicationServices::desktop())
        .manage(workspace_service)
        .manage(planner_service)
        .manage(vault_service)
        .manage(import_service)
        .manage(parity_service)
        .manage(integration_service)
        .manage(lan_bridge_service)
        .invoke_handler(tauri::generate_handler![
            desktop_api::desktop_api_health,
            desktop_api::desktop_api_profile_diagnostics,
            desktop_api::desktop_api_vault_status,
            desktop_api::desktop_api_list_workspaces,
            desktop_api::desktop_api_create_workspace,
            desktop_api::desktop_api_list_boards,
            desktop_api::desktop_api_create_board,
            desktop_api::desktop_api_open_board,
            desktop_api::desktop_api_list_columns,
            desktop_api::desktop_api_create_column,
            desktop_api::desktop_api_list_cards,
            desktop_api::desktop_api_create_card,
            desktop_api::desktop_api_move_card,
            desktop_api::desktop_api_swap_card_order,
            desktop_api::desktop_api_set_card_archived,
            desktop_api::desktop_api_delete_card,
            desktop_api::desktop_api_list_checklists,
            desktop_api::desktop_api_create_checklist,
            desktop_api::desktop_api_delete_checklist,
            desktop_api::desktop_api_list_checklist_items,
            desktop_api::desktop_api_create_checklist_item,
            desktop_api::desktop_api_set_checklist_item_done,
            desktop_api::desktop_api_delete_checklist_item,
            desktop_api::desktop_api_pending_change_count,
            desktop_api::desktop_api_list_labels,
            desktop_api::desktop_api_create_label,
            desktop_api::desktop_api_delete_label,
            desktop_api::desktop_api_list_card_label_ids,
            desktop_api::desktop_api_set_card_label,
            desktop_api::desktop_api_list_comments,
            desktop_api::desktop_api_create_comment,
            desktop_api::desktop_api_delete_comment,
            desktop_api::desktop_api_get_appearance,
            desktop_api::desktop_api_set_appearance,
            desktop_api::desktop_api_list_activity,
            desktop_api::desktop_api_unsynced_parity_count,
            desktop_api::desktop_api_integration_capabilities,
            desktop_api::desktop_api_take_deep_link_intents,
            desktop_api::desktop_api_lan_bridge_addresses,
            desktop_api::desktop_api_lan_bridge_status,
            desktop_api::desktop_api_start_lan_bridge,
            desktop_api::desktop_api_stop_lan_bridge
        ])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("p2pKanban")
                .inner_size(1180.0, 760.0)
                .min_inner_size(820.0, 560.0)
                .devtools(false)
                .on_navigation(navigation_policy::allows_top_level_navigation)
                .on_new_window(|_, _| NewWindowResponse::Deny)
                .on_download(|_, _| false)
                .build()?;

            if let Some(receiver) = activation_receiver {
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    let mut buf = [0_u8; MAX_ACTIVATION_PAYLOAD_BYTES];
                    while let Ok(read) = receiver.recv(&mut buf) {
                        let payload = &buf[..read];
                        let accepted = if payload == ACTIVATE_MAIN_V1 {
                            true
                        } else if let Ok(intent) = decode_deep_link_activation(payload) {
                            eprintln!(
                                "p2pKanban integration: accepted validated deep-link target={}",
                                intent.target.kind()
                            );
                            handle.state::<IntegrationService>().enqueue_deep_link(intent);
                            true
                        } else {
                            false
                        };
                        if !accepted {
                            continue;
                        }
                        if let Some(window) = handle.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .map_err(|err| format!("failed to run p2pKanban Arch-native shell: {err}"))
}


#[cfg(test)]
mod a16_cli_tests {
    use super::*;

    fn args(items: &[&str]) -> Vec<String> {
        items.iter().map(|item| (*item).to_owned()).collect()
    }

    #[test]
    fn a16_recovery_cli_is_explicit_and_restore_requires_confirmation() {
        assert_eq!(
            parse_recovery_cli(&args(&["doctor", "--json"])).unwrap(),
            Some(RecoveryCliCommand::Doctor { json: true })
        );
        assert_eq!(
            parse_recovery_cli(&args(&["safe-mode"])).unwrap(),
            Some(RecoveryCliCommand::SafeMode { json: false })
        );
        assert_eq!(
            parse_recovery_cli(&args(&["restore", "manual-1"])).unwrap(),
            Some(RecoveryCliCommand::Restore {
                backup_id: "manual-1".to_owned(),
                confirmed: false,
                json: false,
            })
        );
        assert_eq!(
            parse_recovery_cli(&args(&["safe-export", "/tmp/recovery.json", "--force", "--json"])).unwrap(),
            Some(RecoveryCliCommand::SafeExport {
                destination: PathBuf::from("/tmp/recovery.json"),
                overwrite: true,
                json: true,
            })
        );
        assert!(parse_recovery_cli(&args(&["backup", "--unknown"])).is_err());
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("p2pKanban startup failed: {error}");
        std::process::exit(1);
    }
}
