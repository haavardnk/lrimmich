import platform
import shutil
from pathlib import Path

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


def service_paths() -> tuple[str, list[Path]]:
    system = platform.system()
    if system == "Darwin":
        return "launchd", [
            Path("~/Library/LaunchAgents/com.lrimmich.sync.plist").expanduser(),
        ]
    return "systemd", [
        Path("~/.config/systemd/user/lrimmich.service").expanduser(),
        Path("~/.config/systemd/user/lrimmich.timer").expanduser(),
    ]


def generate_service(interval: int = 300) -> tuple[str, dict[str, str]]:
    exe = shutil.which("lrimmich") or "lrimmich"
    system = platform.system()

    if system == "Darwin":
        log_dir = str(Path("~/Library/Logs/lrimmich").expanduser())
        content = LAUNCHD_PLIST.format(exe=exe, interval=interval, log_dir=log_dir)
        target = str(
            Path("~/Library/LaunchAgents/com.lrimmich.sync.plist").expanduser()
        )
        return "launchd", {target: content}

    service = SYSTEMD_UNIT_SERVICE.format(exe=exe)
    timer = SYSTEMD_UNIT_TIMER.format(interval=interval)
    base = Path("~/.config/systemd/user").expanduser()
    return "systemd", {
        str(base / "lrimmich.service"): service,
        str(base / "lrimmich.timer"): timer,
    }
