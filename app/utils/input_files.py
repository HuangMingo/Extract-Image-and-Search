from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tempfile


def preserve_uploaded_input(
    source: str | Path,
    storage_root: str | Path,
) -> Path:
    """Return the real source path, or persist a temporary Gradio upload.

    Browsers do not expose the user's original local path. Gradio therefore
    gives the server a temporary copy, which may disappear after the request.
    A content-addressed copy makes ``input_file`` stable and avoids duplicate
    files when the same image is queried repeatedly.
    """
    source_path = Path(source).resolve()
    gradio_temp_root = (Path(tempfile.gettempdir()) / "gradio").resolve()
    if not source_path.is_relative_to(gradio_temp_root):
        return source_path

    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
    target = Path(storage_root).resolve() / "input_files" / digest / source_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source_path, target)
    return target
