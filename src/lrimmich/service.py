import platform
import shutil
from pathlib import Path
from typing import Annotated

import typer

from lrimmich.app import DryRunOption, app

LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.lrimmich.sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>{exe}</string>
    <string>sync</string>
  </array>
  <key>StartInterval</key>
  <integer>{interval}</integer>
  <key>StandardOutPath</key>
  <string>{log_dir}/lrimmich.log</string>
  <key>StandardErrorPath</key>
  <string>{log_dir}/lrimmich.err</string>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
"""

SYSTEMD_UNIT_SERVICE = """\
[Unit]
Description=lrimmich sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={exe} sync

[Install]
WantedBy=default.target
"""

SYSTEMD_UNIT_TIMER = """\
[Unit]
Description=lrimmich sync timer

[Timer]
OnBootSec=60
OnUnitActiveSec={interval}
Persistent=true

[Install]
WantedBy=timers.target
"""


def _service_spec(interval: int) -> tuple[str, dict[Path, str]]:
    exe = shutil.which("lrimmich") or "lrimmich"
    if platform.system() == "Darwin":
        log_dir = str(Path("~/Library/Logs/lrimmich").expanduser())
        plist = Path("~/Library/LaunchAgents/com.lrimmich.sync.plist").expanduser()
        return "launchd", {
            plist: LAUNCHD_PLIST.format(exe=exe, interval=interval, log_dir=log_dir),
        }
    base = Path("~/.config/systemd/user").expanduser()
    return "systemd", {
        base / "lrimmich.service": SYSTEMD_UNIT_SERVICE.format(exe=exe),
        base / "lrimmich.timer": SYSTEMD_UNIT_TIMER.format(interval=interval),
    }


def service_paths() -> tuple[str, list[Path]]:
    kind, files = _service_spec(interval=0)
    return kind, list(files)


def generate_service(interval: int = 300) -> tuple[str, dict[str, str]]:
    kind, files = _service_spec(interval)
    return kind, {str(p): c for p, c in files.items()}


@app.command(name="install-service")
def install_service(
    interval: Annotated[int, typer.Option(help="Sync interval in seconds.")] = 300,
    dry_run: DryRunOption = False,
) -> None:
    kind, files = generate_service(interval)
    for path, content in files.items():
        if dry_run:
            typer.echo(f"Would write {path}:")
            typer.echo(content)
        else:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            typer.echo(f"Wrote {path}")
    if not dry_run:
        if kind == "launchd":
            plist = next(iter(files))
            typer.echo(f"Run: launchctl load {plist}")
        else:
            typer.echo(
                "Run: systemctl --user daemon-reload"
                " && systemctl --user enable --now lrimmich.timer"
            )


@app.command(name="uninstall-service")
def uninstall_service(
    dry_run: DryRunOption = False,
) -> None:
    kind, paths = service_paths()
    removed = False
    for path in paths:
        if path.exists():
            if dry_run:
                typer.echo(f"Would remove {path}")
            else:
                path.unlink()
                typer.echo(f"Removed {path}")
            removed = True
    if not removed:
        typer.echo("No service files found.")
        return
    if not dry_run:
        if kind == "launchd":
            typer.echo(f"Run: launchctl unload {paths[0]}")
        else:
            typer.echo(
                "Run: systemctl --user disable --now lrimmich.timer"
                " && systemctl --user daemon-reload"
            )
