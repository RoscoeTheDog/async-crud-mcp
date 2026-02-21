#!/usr/bin/env python3
"""Build Python Embedded Bundle for Windows self-contained distribution."""

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request


def download_python_embeddable(version, build_dir):
    """Download Python embeddable package from python.org."""
    print(f"[DOWNLOAD] Fetching Python {version} embeddable package...")

    # Construct download URL for Windows x64 embeddable
    url = f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"

    build_dir.mkdir(parents=True, exist_ok=True)
    zip_path = build_dir / f"python-{version}-embed.zip"

    try:
        req = Request(url)
        req.add_header("User-Agent", "async-crud-mcp-builder")

        with urlopen(req, timeout=60) as response:
            data = response.read()

        with open(zip_path, 'wb') as f:
            f.write(data)

        print(f"[OK] Downloaded {len(data)} bytes to {zip_path}")
        return zip_path

    except Exception as e:
        raise RuntimeError(f"Failed to download Python embeddable: {e}")


def extract_embeddable(zip_path, extract_dir):
    """Extract Python embeddable package."""
    print(f"[EXTRACT] Extracting to {extract_dir}...")

    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_dir)

    print(f"[OK] Extracted to {extract_dir}")
    return extract_dir


def create_pth_file(extract_dir, package_name):
    """Create _pth file to configure import paths."""
    print("[CONFIG] Creating ._pth file...")

    # Find existing ._pth file
    pth_files = list(extract_dir.glob("python*._pth"))
    if not pth_files:
        raise RuntimeError("No ._pth file found in embeddable package")

    pth_file = pth_files[0]

    # Read existing content
    with open(pth_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Uncomment import site if commented
    new_lines = []
    for line in lines:
        if line.strip().startswith("#import site"):
            new_lines.append("import site\n")
        else:
            new_lines.append(line)

    # Add package paths
    new_lines.append(f"Lib\\site-packages\n")
    new_lines.append(f"{package_name}\n")

    # Write back
    with open(pth_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"[OK] Updated {pth_file.name}")


def install_package_into_bundle(extract_dir, project_root):
    """Install the package and dependencies into the embedded Python."""
    print("[INSTALL] Installing package into bundle...")

    python_exe = extract_dir / "python.exe"

    # First, install pip into the embedded Python
    print("[INFO] Installing pip...")
    try:
        subprocess.run(
            [str(python_exe), "-m", "ensurepip", "--default-pip"],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"[WARN] ensurepip failed, trying get-pip.py: {e.stderr}")

        # Fallback: download and run get-pip.py
        get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
        req = Request(get_pip_url)
        with urlopen(req, timeout=30) as response:
            get_pip = response.read()

        get_pip_path = extract_dir / "get-pip.py"
        with open(get_pip_path, 'wb') as f:
            f.write(get_pip)

        subprocess.run([str(python_exe), str(get_pip_path)], check=True)

    # Install the package
    print(f"[INFO] Installing package from {project_root}...")
    subprocess.run(
        [str(python_exe), "-m", "pip", "install", str(project_root)],
        check=True,
        capture_output=True,
        text=True
    )

    print("[OK] Package installed into bundle")


def create_launcher_script(output_dir):
    """Create launcher batch script."""
    print("[LAUNCHER] Creating launcher script...")

    launcher_content = """@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PYTHON_EXE=%SCRIPT_DIR%python.exe

"%PYTHON_EXE%" -m async_crud_mcp.server %*

endlocal
"""

    launcher_path = output_dir / "start-async-crud-mcp.bat"
    with open(launcher_path, 'w', encoding='utf-8') as f:
        f.write(launcher_content)

    print(f"[OK] Launcher created at {launcher_path}")


def bundle_distribution(extract_dir, output_dir, version):
    """Create final distribution bundle."""
    print("[BUNDLE] Creating distribution archive...")

    bundle_name = f"async-crud-mcp-{version}-windows-x64"
    bundle_dir = output_dir / bundle_name

    # Copy embedded Python to bundle directory
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)

    shutil.copytree(extract_dir, bundle_dir)

    # Create launcher in bundle
    launcher_content = """@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PYTHON_EXE=%SCRIPT_DIR%python.exe

"%PYTHON_EXE%" -m async_crud_mcp.server %*

endlocal
"""

    launcher_path = bundle_dir / "start-async-crud-mcp.bat"
    with open(launcher_path, 'w', encoding='utf-8') as f:
        f.write(launcher_content)

    # Create zip archive
    archive_path = output_dir / f"{bundle_name}.zip"
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in bundle_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(bundle_dir.parent)
                zf.write(file, arcname)

    print(f"[OK] Distribution bundle created: {archive_path}")
    print(f"     Size: {archive_path.stat().st_size / 1024 / 1024:.1f} MB")

    return archive_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build Python Embedded Bundle for async-crud-mcp",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--python-version",
        default="3.12.0",
        help="Python version to embed (default: 3.12.0)"
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "dist",
        help="Output directory for bundle (default: ./dist)"
    )

    parser.add_argument(
        "--build-dir",
        type=Path,
        default=Path.cwd() / "build",
        help="Build directory for intermediate files (default: ./build)"
    )

    parser.add_argument(
        "--package-version",
        default="0.1.0",
        help="Package version for bundle name (default: 0.1.0)"
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("Python Embedded Bundle Builder")
    print("="*60 + "\n")

    try:
        # Get project root
        project_root = Path(__file__).parent.parent
        print(f"[INFO] Project root: {project_root}")

        # Download Python embeddable
        zip_path = download_python_embeddable(args.python_version, args.build_dir)

        # Extract
        extract_dir = args.build_dir / "python-embedded"
        extract_embeddable(zip_path, extract_dir)

        # Configure ._pth
        create_pth_file(extract_dir, "async-crud-mcp")

        # Install package
        install_package_into_bundle(extract_dir, project_root)

        # Create launcher
        create_launcher_script(args.output_dir)

        # Bundle distribution
        archive_path = bundle_distribution(extract_dir, args.output_dir, args.package_version)

        print("\n" + "="*60)
        print("[SUCCESS] Bundle build complete!")
        print("="*60)
        print(f"Distribution: {archive_path}")
        print(f"Extract and run: start-async-crud-mcp.bat")
        print("="*60 + "\n")

        return 0

    except Exception as e:
        print(f"\n[ERROR] Build failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
