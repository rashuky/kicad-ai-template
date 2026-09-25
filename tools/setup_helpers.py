"""Helpers for setup.ps1. Plain Python 3.10+, no packages.

usage:
  python tools/setup_helpers.py konnect [--version latest|0.12.1] [--force]
      Download the Konnect KiCad plugin (PCM package) from GitHub and install it the way
      KiCad's Plugin and Content Manager "Install from File" does. KiCad must be closed.
  python tools/setup_helpers.py mcp
      Write .mcp.json (konnect + kschlint servers) with absolute paths for this machine.
  python tools/setup_helpers.py konnect-exe
      Print the installed konnect.exe path (exit 1 when missing).
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KONNECT_REPO = "mixelpixx/Konnect"
KONNECT_ID = "com.github.mixelpixx.konnect"
KICAD_VER = "10.0"


def documents_dir():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL, follows OneDrive redirection
        return buf.value
    return os.path.expanduser("~/Documents")


def third_party_dir():
    env = os.environ.get("KICAD10_3RD_PARTY")
    if env:
        return env
    # KiCad Preferences > Configure Paths can override it, stored in kicad_common.json
    common = os.path.join(config_dir(), "kicad_common.json")
    if os.path.exists(common):
        try:
            v = (json.load(open(common, encoding="utf-8")).get("environment", {}).get("vars") or {}).get("KICAD10_3RD_PARTY")
            if v:
                return os.path.expandvars(v)
        except ValueError:
            pass
    return os.path.join(documents_dir(), "KiCad", KICAD_VER, "3rdparty")


def config_dir():
    base = os.environ.get("KICAD_CONFIG_HOME")
    if base:
        return os.path.join(base, KICAD_VER)
    if os.name == "nt":
        return os.path.join(os.environ["APPDATA"], "kicad", KICAD_VER)
    return os.path.expanduser(f"~/.config/kicad/{KICAD_VER}")


def konnect_dir():
    return os.path.join(third_party_dir(), "plugins", KONNECT_ID.replace(".", "_"))


def konnect_exe():
    return os.path.join(konnect_dir(), "bin", "konnect.exe" if os.name == "nt" else "konnect")


def kicad_running():
    if os.name != "nt":
        return False
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout.lower()
    # konnect: a running MCP server (Claude Code open) locks konnect.exe
    return any(f'"{p}.exe"' in out for p in ("kicad", "eeschema", "pcbnew", "konnect"))


def github_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "kicad-ai-template"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def installed_version(packages_file):
    if not os.path.exists(packages_file):
        return None
    data = json.load(open(packages_file, encoding="utf-8"))
    return next((p.get("current_version") for p in data.get("packages", []) if p["package"]["identifier"] == KONNECT_ID), None)


def install_konnect(version, force):
    if kicad_running():
        sys.exit("KiCad or konnect.exe is running. Close KiCad and Claude Code (it keeps the Konnect server open) and run again.")
    version = version.lstrip("v")
    plat = {"nt": "windows", "posix": "macos" if sys.platform == "darwin" else "linux"}[os.name]
    rel = github_json(f"https://api.github.com/repos/{KONNECT_REPO}/releases/" + ("latest" if version == "latest" else f"tags/v{version}"))
    asset = next((a for a in rel["assets"] if a["name"].startswith("konnect-pcm-") and a["name"].endswith(f"-{plat}.zip")), None)
    if not asset:
        sys.exit(f"no konnect-pcm-*-{plat}.zip in release {rel['tag_name']}")
    ver = rel["tag_name"].lstrip("v")
    pkg_file = os.path.join(config_dir(), "installed_packages.json")
    if not force and installed_version(pkg_file) == ver and os.path.exists(konnect_exe()):
        print(f"Konnect {ver} already installed: {konnect_exe()}")
        return
    with tempfile.TemporaryDirectory() as tmp:
        zpath = os.path.join(tmp, asset["name"])
        print(f"downloading {asset['browser_download_url']}")
        req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "kicad-ai-template"})
        with urllib.request.urlopen(req, timeout=300) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(os.path.join(tmp, "pkg"))
        pkg = os.path.join(tmp, "pkg")
        meta = json.load(open(os.path.join(pkg, "metadata.json"), encoding="utf-8"))
        # same layout as KiCad PCM: <3rdparty>/<type>s/<id with _>/..., resources/<id with _>/...
        dirname = KONNECT_ID.replace(".", "_")
        for sub in ("plugins", "resources"):
            src, dst = os.path.join(pkg, sub), os.path.join(third_party_dir(), sub, dirname)
            if os.path.isdir(src):
                try:
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                except OSError as e:
                    sys.exit(f"cannot replace {dst}: {e}\nA file is in use. Close KiCad and Claude Code, then run again.")
    meta.pop("$schema", None)
    meta["versions"] = [v for v in meta.get("versions", []) if v.get("version") == ver] or meta.get("versions", [])
    os.makedirs(config_dir(), exist_ok=True)
    data = json.load(open(pkg_file, encoding="utf-8")) if os.path.exists(pkg_file) else {"packages": []}
    data["packages"] = [p for p in data.get("packages", []) if p["package"]["identifier"] != KONNECT_ID]
    data["packages"].append({"current_version": ver, "install_timestamp": int(time.time()), "package": meta,
                             "pinned": False, "repository_id": "", "repository_name": "Local file"})
    with open(pkg_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"Konnect {ver} installed: {konnect_exe()}")


def write_mcp():
    path = os.path.join(ROOT, ".mcp.json")
    cfg = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    servers = cfg.setdefault("mcpServers", {})
    servers["kschlint"] = {"command": sys.executable.replace("\\", "/"), "args": ["-m", "kschlint", "mcp"],
                           "env": {"PYTHONPATH": os.path.join(ROOT, "tools", "kicad-sch-lint").replace("\\", "/")}}
    if os.path.exists(konnect_exe()):
        servers["konnect"] = {"command": konnect_exe().replace("\\", "/")}
    else:
        print(f"konnect.exe not found at {konnect_exe()}, konnect server left out")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"wrote {path}: {', '.join(servers)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("konnect"); k.add_argument("--version", default="latest"); k.add_argument("--force", action="store_true")
    sub.add_parser("mcp")
    sub.add_parser("konnect-exe")
    a = ap.parse_args()
    if a.cmd == "konnect":
        install_konnect(a.version, a.force)
    elif a.cmd == "mcp":
        write_mcp()
    else:
        print(konnect_exe())
        sys.exit(0 if os.path.exists(konnect_exe()) else 1)


if __name__ == "__main__":
    main()
