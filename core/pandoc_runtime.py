"""Pandoc discovery and controlled installation for source and bundled runs."""

import os
from pathlib import Path
import re
import sys
import tempfile
import threading

from core.paths import get_app_paths, resource_path


MIN_PANDOC_VERSION = (3, 1, 7)
MIN_PANDOC_VERSION_TEXT = ".".join(str(part) for part in MIN_PANDOC_VERSION)
_DOWNLOAD_LOCK = threading.Lock()


class PandocUnavailableError(RuntimeError):
    """Raised when a suitable Pandoc cannot be used without an unsafe fallback."""


class PandocDownloadRequired(PandocUnavailableError):
    """Raised when a source run needs explicit consent before downloading Pandoc."""


def is_frozen_app():
    """Return whether the current process is a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def pandoc_executable_name():
    return "pandoc.exe" if sys.platform == "win32" else "pandoc"


def bundled_pandoc_path():
    """Return the Pandoc path expected inside a PyInstaller bundle."""
    return Path(resource_path(os.path.join("pandoc", pandoc_executable_name())))


def _version_tuple(version):
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", str(version))
    if not match:
        raise PandocUnavailableError(f"Versão do Pandoc não reconhecida: {version}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def _prepare_pypandoc():
    configured_path = None
    if is_frozen_app():
        binary = bundled_pandoc_path()
        if not binary.is_file():
            raise PandocUnavailableError(
                "O executável foi publicado sem o Pandoc incorporado. "
                "Reinstale a aplicação a partir de uma release íntegra."
            )
        configured_path = binary
    elif not os.environ.get("PYPANDOC_PANDOC"):
        downloaded_binary = (
            get_app_paths().data_dir / "pandoc" / pandoc_executable_name()
        )
        if downloaded_binary.is_file():
            configured_path = downloaded_binary

    if configured_path is not None:
        os.environ["PYPANDOC_PANDOC"] = str(configured_path)

    import pypandoc

    if configured_path is not None:
        pypandoc.clean_pandocpath_cache()
        pypandoc.clean_version_cache()
    return pypandoc


def _installed_version(pypandoc):
    try:
        return _version_tuple(pypandoc.get_pandoc_version())
    except OSError:
        return None


def pandoc_download_requirement():
    """Describe a needed source-only download, or return ``None``.

    Bundled applications never offer a download. Their embedded binary is checked
    by :func:`load_pandoc` and an incomplete bundle fails explicitly.
    """
    if is_frozen_app():
        return None

    pypandoc = _prepare_pypandoc()
    version = _installed_version(pypandoc)
    if version is None:
        return f"Pandoc {MIN_PANDOC_VERSION_TEXT} ou superior não foi encontrado."
    if version < MIN_PANDOC_VERSION:
        current = ".".join(str(part) for part in version)
        return (
            f"O Pandoc instalado é {current}, mas a exportação requer "
            f"{MIN_PANDOC_VERSION_TEXT} ou superior."
        )
    return None


def _download_source_pandoc(pypandoc, log_callback):
    app_paths = get_app_paths()
    target_dir = app_paths.ensure_data_dir() / "pandoc"
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(target_dir, 0o700)
    except OSError:
        pass

    log_callback(
        f"Baixando Pandoc {MIN_PANDOC_VERSION_TEXT}+ para o diretório de dados...",
        "warning",
    )
    with tempfile.TemporaryDirectory(prefix="auditoria_zabbix_pandoc_") as download_dir:
        pypandoc.download_pandoc(
            targetfolder=str(target_dir),
            delete_installer=True,
            download_folder=download_dir,
        )

    binary = target_dir / pandoc_executable_name()
    if not binary.is_file():
        raise PandocUnavailableError(
            "O download terminou sem produzir o executável esperado do Pandoc."
        )

    os.environ["PYPANDOC_PANDOC"] = str(binary)
    pypandoc.clean_pandocpath_cache()
    pypandoc.clean_version_cache()


def load_pandoc(*, allow_download=False, log_callback=None):
    """Return configured ``pypandoc`` while enforcing offline bundle behavior."""
    log_callback = log_callback or (lambda _message, _style="info": None)
    pypandoc = _prepare_pypandoc()
    version = _installed_version(pypandoc)
    if version is not None and version >= MIN_PANDOC_VERSION:
        return pypandoc

    if is_frozen_app():
        found = "não pôde ser executado" if version is None else ".".join(map(str, version))
        raise PandocUnavailableError(
            "O Pandoc incorporado ao executável está ausente, inválido ou é antigo "
            f"(detectado: {found}; requerido: {MIN_PANDOC_VERSION_TEXT}+). "
            "Nenhum download foi tentado. Reinstale a release."
        )

    if not allow_download:
        reason = pandoc_download_requirement() or "Pandoc compatível não disponível."
        raise PandocDownloadRequired(
            f"{reason} Confirme o download na interface antes de continuar."
        )

    with _DOWNLOAD_LOCK:
        version = _installed_version(pypandoc)
        if version is None or version < MIN_PANDOC_VERSION:
            _download_source_pandoc(pypandoc, log_callback)

        version = _installed_version(pypandoc)
        if version is None or version < MIN_PANDOC_VERSION:
            raise PandocUnavailableError(
                f"Não foi possível disponibilizar Pandoc {MIN_PANDOC_VERSION_TEXT}+."
            )
    return pypandoc
