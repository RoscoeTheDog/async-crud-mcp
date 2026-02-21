#!/usr/bin/env python3
"""Bootstrap uv package manager - stdlib-only cross-platform installer."""

import json
import platform
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request


def get_uv_install_dir():
    """Get platform-specific uv installation directory."""
    system = platform.system()

    if system == "Windows":
        import os
        localappdata = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return Path(localappdata) / "async-crud-mcp" / "bin"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "async-crud-mcp" / "bin"
    else:  # Linux
        import os
        xdg_data_home = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        return Path(xdg_data_home) / "async-crud-mcp" / "bin"


def detect_platform():
    """Detect platform and architecture for uv binary selection."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        if "amd64" in machine or "x86_64" in machine:
            return "x86_64-pc-windows-msvc"
        else:
            raise RuntimeError(f"Unsupported Windows architecture: {machine}")
    elif system == "Darwin":
        if "arm64" in machine or "aarch64" in machine:
            return "aarch64-apple-darwin"
        elif "x86_64" in machine:
            return "x86_64-apple-darwin"
        else:
            raise RuntimeError(f"Unsupported macOS architecture: {machine}")
    elif system == "Linux":
        if "x86_64" in machine or "amd64" in machine:
            return "x86_64-unknown-linux-gnu"
        elif "aarch64" in machine or "arm64" in machine:
            return "aarch64-unknown-linux-gnu"
        else:
            raise RuntimeError(f"Unsupported Linux architecture: {machine}")
    else:
        raise RuntimeError(f"Unsupported operating system: {system}")


def get_latest_uv_release():
    """Fetch latest uv release info from GitHub API."""
    print("[INFO] Fetching latest uv release from GitHub...")

    api_url = "https://api.github.com/repos/astral-sh/uv/releases/latest"

    try:
        req = Request(api_url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "async-crud-mcp-installer")

        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        version = data.get("tag_name", "").lstrip("v")
        print(f"[OK] Latest uv version: {version}")

        return version, data.get("assets", [])
    except Exception as e:
        raise RuntimeError(f"Failed to fetch uv release info: {e}")


def download_uv_binary(version, platform_triple):
    """Download uv binary for the detected platform."""
    print(f"[DOWNLOAD] Downloading uv for {platform_triple}...")

    # Construct download URL
    if platform_triple.endswith("windows-msvc"):
        filename = f"uv-{platform_triple}.zip"
    else:
        filename = f"uv-{platform_triple}.tar.gz"

    download_url = f"https://github.com/astral-sh/uv/releases/download/{version}/{filename}"

    try:
        req = Request(download_url)
        req.add_header("User-Agent", "async-crud-mcp-installer")

        with urlopen(req, timeout=30) as response:
            data = response.read()

        print(f"[OK] Downloaded {len(data)} bytes")
        return data, filename
    except Exception as e:
        raise RuntimeError(f"Failed to download uv: {e}")


def extract_uv_binary(archive_data, filename, install_dir):
    """Extract uv binary from downloaded archive."""
    print(f"[EXTRACT] Extracting uv to {install_dir}...")

    # Create install directory
    install_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        archive_path = tmpdir_path / filename

        # Write archive to temp file
        with open(archive_path, 'wb') as f:
            f.write(archive_data)

        # Extract archive
        if filename.endswith(".zip"):
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(tmpdir_path)
        else:
            with tarfile.open(archive_path, 'r:gz') as tf:
                tf.extractall(tmpdir_path)

        # Find uv binary in extracted files
        system = platform.system()
        uv_binary_name = "uv.exe" if system == "Windows" else "uv"

        # Look for binary in extracted directory
        for root, _, files in tmpdir_path.walk():
            if uv_binary_name in files:
                src_binary = root / uv_binary_name
                dst_binary = install_dir / uv_binary_name

                # Copy binary to install directory
                shutil.copy2(src_binary, dst_binary)

                # Make executable on Unix
                if system != "Windows":
                    import os
                    os.chmod(dst_binary, 0o755)

                print(f"[OK] uv installed to {dst_binary}")
                return dst_binary

        raise RuntimeError(f"Could not find {uv_binary_name} in archive")


def add_to_path(install_dir):
    """Add uv install directory to PATH (informational only)."""
    system = platform.system()

    print("\n" + "="*60)
    print("[INFO] uv installed successfully!")
    print("="*60)
    print(f"Installation directory: {install_dir}")
    print("\nTo use uv, add it to your PATH:")

    if system == "Windows":
        print(f"\n  setx PATH \"%PATH%;{install_dir}\"")
        print("\nor add manually via System Properties > Environment Variables")
    else:
        shell_config = "~/.bashrc" if Path.home() / ".bashrc" else "~/.zshrc"
        print(f"\n  echo 'export PATH=\"{install_dir}:$PATH\"' >> {shell_config}")
        print(f"  source {shell_config}")

    print("="*60 + "\n")


def main():
    """Main entry point."""
    print("\n" + "="*60)
    print("uv Package Manager Bootstrap")
    print("="*60 + "\n")

    # Check if uv is already installed
    existing_uv = shutil.which("uv")
    if existing_uv:
        print(f"[OK] uv already installed at {existing_uv}")
        return 0

    try:
        # Detect platform
        platform_triple = detect_platform()
        print(f"[DETECT] Platform: {platform_triple}")

        # Get installation directory
        install_dir = get_uv_install_dir()

        # Get latest release
        version, _ = get_latest_uv_release()

        # Download binary
        archive_data, filename = download_uv_binary(version, platform_triple)

        # Extract and install
        uv_binary = extract_uv_binary(archive_data, filename, install_dir)

        # Show PATH instructions
        add_to_path(install_dir)

        print(f"[SUCCESS] uv {version} installed successfully!")
        print(f"Binary location: {uv_binary}\n")

        return 0

    except Exception as e:
        print(f"[ERROR] Bootstrap failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
