"""Adapt daemon-service templates to async-crud-mcp."""
import re
from pathlib import Path

TEMPLATE_DIR = Path("C:/Users/Admin/Documents/GitHub/claude-code-tooling/claude-mcp/daemon-service/resources/snippets/common")
OUTPUT_DIR = Path("C:/Users/Admin/Documents/GitHub/async-crud-mcp/src/async_crud_mcp/daemon")

# Replacement mapping
REPLACEMENTS = {
    '[APP_NAME]': 'async-crud-mcp',
    '[PACKAGE_NAME]': 'async_crud_mcp',
    '[DEFAULT_PORT]': '8720',
}

# Files to adapt
FILES_TO_ADAPT = [
    'config_init.py',
    'config_watcher.py',
    'health.py',
    'installer.py',
    'bootstrap_daemon.py',
]

def adapt_file(template_file: Path, output_file: Path):
    """Apply replacements to template and write to output."""
    content = template_file.read_text(encoding='utf-8')
    
    # Apply all replacements
    for placeholder, value in REPLACEMENTS.items():
        content = content.replace(placeholder, value)
    
    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding='utf-8')
    print(f"Created: {output_file}")

def main():
    for filename in FILES_TO_ADAPT:
        template_path = TEMPLATE_DIR / filename
        output_path = OUTPUT_DIR / filename
        
        if not template_path.exists():
            print(f"SKIP: Template not found: {template_path}")
            continue
        
        adapt_file(template_path, output_path)
    
    print("\nAll daemon modules adapted successfully!")

if __name__ == '__main__':
    main()
