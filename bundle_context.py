import os
import zipfile

# Configuration: Add folders or files you want to IGNORE
IGNORE_LIST = {
    '.git', '.idea', '.venv', '__pycache__', 'node_modules',
    'agents.zip', 'Cod.zip', '.env', 'mcp_demo.db',
    'AGENT_README.md', 'AGENTS.md', 'bundle_context.py', "debug_http.py", "requirements.txt", "test.py",
    'Doc' # Excludes the entire Doc folder
}

# Subpaths to ignore specifically (like static/uploads)
IGNORE_SUBPATHS = {
    os.path.join('static', 'uploads')
}

MAX_SIZE_MB = 1  # Set threshold for max file size in MB

def create_context_zip(output_filename="context_for_gemini.zip"):
    current_dir = os.getcwd()

    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(current_dir):
            # Calculate relative path from the root directory
            rel_root = os.path.relpath(root, current_dir)

            # Filter out ignored top-level directories
            dirs[:] = [d for d in dirs if d not in IGNORE_LIST]

            # Specifically filter out 'static/uploads' or other nested paths
            dirs[:] = [d for d in dirs if os.path.join(rel_root, d).strip(".\\") not in IGNORE_SUBPATHS]

            for file in files:
                # Basic file ignore logic
                if file in IGNORE_LIST or file == output_filename or file == __file__:
                    continue

                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, current_dir)

                print(f"Adding: {arcname}")
                zipf.write(file_path, arcname)

        # Size Verification logic
        size_bytes = os.path.getsize(output_filename)
        size_mb = size_bytes / (1024 * 1024)

        print("-" * 30)
        print(f"✅ Success! Created: {output_filename}")
        print(f"📦 Final Size: {size_mb:.2f} MB")

        if size_mb > MAX_SIZE_MB:
            print(f"⚠️  WARNING: File exceeds {MAX_SIZE_MB}MB. It might be too large for some prompts.")
        print("-" * 30)


if __name__ == "__main__":
    create_context_zip()