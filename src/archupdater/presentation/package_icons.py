from __future__ import annotations

from pathlib import Path

from archupdater.domain.package_metadata import (
    AurPackageMetadata,
    FirmwarePackageMetadata,
    FlatpakPackageMetadata,
    PlasmaWidgetPackageMetadata,
)
from archupdater.domain.packages import PackageUpdate


class PackageIconResolver:
    APPSTREAM_ICON_ROOTS = (
        Path("/usr/share/swcatalog/icons"),
        Path("/usr/share/app-info/icons"),
    )
    APPSTREAM_REPOS = (
        "archlinux-arch-extra",
        "archlinux-arch-core",
        "archlinux-arch-multilib",
    )
    ICON_THEME_ROOTS = (
        Path.home() / ".local" / "share" / "icons",
        Path("/usr/local/share/icons"),
        Path("/usr/share/icons"),
        Path("/usr/share/pixmaps"),
    )
    DESKTOP_ENTRY_ROOTS = (
        Path.home() / ".local" / "share" / "applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    )
    FLATPAK_APPSTREAM_ROOTS = (
        Path.home() / ".local" / "share" / "flatpak" / "appstream",
        Path("/var/lib/flatpak/appstream"),
    )
    ICON_SIZES = ("128x128", "96x96", "64x64", "48x48", "32x32", "256x256", "scalable")
    THEME_SIZE_DIRS = (
        *ICON_SIZES,
        "16x16",
        "22x22",
        "24x24",
        "16",
        "22",
        "24",
        "32",
        "48",
        "64",
        "96",
        "128",
        "256",
    )
    ICON_CONTEXTS = ("apps", "devices", "mimetypes", "places", "status")
    ICON_EXTENSIONS = ("png", "svg", "xpm")
    EXACT_ICON_ALIASES = {
        "alacritty": ("Alacritty", "alacritty", "utilities-terminal"),
        "alsa-lib": ("audio-card", "audio-volume-high", "preferences-desktop-sound"),
        "alsa-utils": ("audio-card", "audio-volume-high", "preferences-desktop-sound"),
        "archlinux-keyring": ("archlinux-logo", "arch", "security-high"),
        "avahi": ("network-workgroup", "preferences-system-network"),
        "bash": ("utilities-terminal", "terminal", "application-x-shellscript"),
        "bluez": ("bluetooth", "preferences-system-bluetooth"),
        "bpf": ("linux", "tux", "computer"),
        "bubblewrap": ("package-x-generic", "application-x-executable", "system-run"),
        "bzip2": ("package-x-generic", "application-x-archive"),
        "ca-certificates": ("security-high", "certificate", "application-certificate"),
        "cargo": ("rust", "cargo"),
        "clang": ("llvm", "applications-development"),
        "cmake": ("cmake", "applications-development"),
        "composer": ("php", "composer", "applications-development"),
        "curl": ("applications-internet", "network-workgroup"),
        "dbus": ("preferences-system", "system-run"),
        "docker": ("docker", "package-x-generic"),
        "emacs": ("emacs", "accessories-text-editor"),
        "exfatprogs": ("drive-harddisk", "drive-removable-media"),
        "ffmpeg": ("multimedia-video-player", "applications-multimedia"),
        "fish": ("utilities-terminal", "terminal", "application-x-shellscript"),
        "flatpak": ("flatpak", "application-x-flatpak", "package-x-generic"),
        "fwupd": ("drive-removable-media", "preferences-system"),
        "gcc": ("gcc", "applications-development"),
        "git": ("git", "applications-development"),
        "glibc": ("package-x-generic", "applications-system"),
        "gnupg": ("security-high", "dialog-password"),
        "go": ("go", "golang", "applications-development"),
        "gradle": ("gradle", "java", "applications-development"),
        "gtk": ("gtk", "preferences-desktop-theme"),
        "java": ("java", "openjdk", "applications-java"),
        "kde": ("kde", "preferences-desktop-plasma"),
        "kf5": ("kde", "preferences-desktop-plasma"),
        "kf6": ("kde", "preferences-desktop-plasma"),
        "plasma": ("kde", "preferences-desktop-plasma"),
        "linux": ("linux", "tux", "computer"),
        "llvm": ("llvm", "applications-development"),
        "lua": ("lua", "applications-development"),
        "make": ("applications-development", "system-run"),
        "mariadb": ("database", "server-database"),
        "mesa": ("video-display", "preferences-desktop-display"),
        "meson": ("applications-development", "system-run"),
        "nano": ("accessories-text-editor", "text-editor"),
        "neovim": ("nvim", "neovim", "vim", "accessories-text-editor"),
        "networkmanager": ("network-workgroup", "preferences-system-network"),
        "ninja": ("applications-development", "system-run"),
        "nodejs": ("nodejs", "node", "npm"),
        "npm": ("npm", "nodejs", "node"),
        "noto-fonts": ("font-x-generic", "preferences-desktop-font"),
        "openssh": ("network-server", "security-high", "utilities-terminal"),
        "openssl": ("security-high", "dialog-password"),
        "pacman": ("package-x-generic", "system-software-update"),
        "perl": ("perl", "applications-development"),
        "php": ("php", "applications-development"),
        "pipewire": ("audio-card", "preferences-desktop-sound"),
        "podman": ("podman", "docker", "package-x-generic"),
        "postgresql": ("database", "server-database"),
        "pulseaudio": ("audio-card", "preferences-desktop-sound"),
        "python": ("python", "python3", "applications-python"),
        "python2": ("python", "python3", "applications-python"),
        "python3": ("python", "python3", "applications-python"),
        "qt": ("qt", "qtcreator"),
        "qt5": ("qt", "qtcreator"),
        "qt6": ("qt", "qtcreator"),
        "redis": ("database", "server-database"),
        "ruby": ("ruby", "applications-development"),
        "rust": ("rust", "cargo"),
        "sqlite": ("database", "server-database"),
        "systemd": ("preferences-system", "applications-system"),
        "vim": ("vim", "accessories-text-editor"),
        "vulkan-headers": ("video-display", "preferences-desktop-display"),
        "wget": ("applications-internet", "network-workgroup"),
        "xfsprogs": ("drive-harddisk", "drive-removable-media"),
        "xz": ("package-x-generic", "application-x-archive"),
        "zlib": ("package-x-generic", "application-x-archive"),
        "zsh": ("utilities-terminal", "terminal", "application-x-shellscript"),
        "zstd": ("package-x-generic", "application-x-archive"),
    }
    PREFIX_ICON_ALIASES = (
        ("adobe-source-", ("font-x-generic", "preferences-desktop-font")),
        ("alsa-", ("audio-card", "preferences-desktop-sound")),
        ("android-", ("android", "phone", "applications-development")),
        ("ansible-", ("applications-system", "utilities-terminal")),
        ("apache-", ("network-server", "applications-internet")),
        ("appstream-", ("system-software-update", "package-x-generic")),
        ("archlinux-", ("archlinux-logo", "arch", "package-x-generic")),
        ("avahi-", ("network-workgroup", "preferences-system-network")),
        ("bash-", ("utilities-terminal", "application-x-shellscript")),
        ("bluetooth-", ("bluetooth", "preferences-system-bluetooth")),
        ("boost-", ("applications-development", "package-x-generic")),
        ("breeze-", ("kde", "preferences-desktop-plasma")),
        ("btrfs-", ("drive-harddisk", "drive-removable-media")),
        ("ca-certificates-", ("security-high", "certificate", "application-certificate")),
        ("cargo-", ("rust", "cargo")),
        ("clang-", ("llvm", "applications-development")),
        ("cmake-", ("cmake", "applications-development")),
        ("containerd-", ("package-x-generic", "application-x-executable")),
        ("cuda-", ("nvidia-settings", "video-display", "preferences-desktop-display")),
        ("cups-", ("printer", "preferences-devices-printer")),
        ("curl-", ("applications-internet", "network-workgroup")),
        ("dbus-", ("preferences-system", "system-run")),
        ("docker-", ("docker", "package-x-generic")),
        ("dotnet-", ("applications-development", "package-x-generic")),
        ("e2fsprogs", ("drive-harddisk", "drive-removable-media")),
        ("electron", ("electron", "applications-development")),
        ("exfat", ("drive-harddisk", "drive-removable-media")),
        ("ffmpeg-", ("multimedia-video-player", "applications-multimedia")),
        ("firefox-", ("firefox", "web-browser", "applications-internet")),
        ("font-", ("font-x-generic", "preferences-desktop-font")),
        ("fwupd-", ("drive-removable-media", "preferences-system")),
        ("gcc-", ("gcc", "applications-development")),
        ("gdk-pixbuf", ("image-x-generic", "applications-graphics")),
        ("git-", ("git", "applications-development")),
        ("glib-", ("package-x-generic", "applications-development")),
        ("gnome-", ("gnome", "preferences-desktop-theme")),
        ("gnupg-", ("security-high", "dialog-password")),
        ("go-", ("go", "golang", "applications-development")),
        ("golang-", ("go", "golang", "applications-development")),
        ("gstreamer", ("applications-multimedia", "multimedia-video-player")),
        ("gtk", ("gtk", "preferences-desktop-theme")),
        ("haskell-", ("haskell", "applications-development")),
        ("intel-", ("video-display", "preferences-desktop-display")),
        ("jdk", ("java", "openjdk", "applications-java")),
        ("jre", ("java", "openjdk", "applications-java")),
        ("kde-", ("kde", "preferences-desktop-plasma")),
        ("kf5-", ("kde", "preferences-desktop-plasma")),
        ("kf6-", ("kde", "preferences-desktop-plasma")),
        ("kio-", ("kde", "preferences-desktop-plasma")),
        ("lib32-", ("package-x-generic", "applications-system")),
        ("libreoffice-", ("libreoffice", "x-office-document")),
        ("linux-", ("linux", "tux", "computer")),
        ("llvm-", ("llvm", "applications-development")),
        ("lua-", ("lua", "applications-development")),
        ("mariadb-", ("database", "server-database")),
        ("mesa-", ("video-display", "preferences-desktop-display")),
        ("mono-", ("applications-development", "package-x-generic")),
        ("nodejs-", ("nodejs", "node", "npm")),
        ("noto-fonts", ("font-x-generic", "preferences-desktop-font")),
        ("npm-", ("npm", "nodejs", "node")),
        ("ntfs-", ("drive-harddisk", "drive-removable-media")),
        ("nvidia-", ("nvidia-settings", "video-display", "preferences-desktop-display")),
        ("openjdk", ("java", "openjdk", "applications-java")),
        ("openssh-", ("network-server", "security-high", "utilities-terminal")),
        ("openssl-", ("security-high", "dialog-password")),
        ("otf-", ("font-x-generic", "preferences-desktop-font")),
        ("pacman-", ("package-x-generic", "system-software-update")),
        ("perl-", ("perl", "applications-development")),
        ("php-", ("php", "applications-development")),
        ("pipewire-", ("audio-card", "preferences-desktop-sound")),
        ("plasma-", ("kde", "preferences-desktop-plasma")),
        ("podman-", ("podman", "docker", "package-x-generic")),
        ("postgresql-", ("database", "server-database")),
        ("pulseaudio-", ("audio-card", "preferences-desktop-sound")),
        ("python-", ("python", "python3", "applications-python")),
        ("python2-", ("python", "python3", "applications-python")),
        ("python3-", ("python", "python3", "applications-python")),
        ("qt-", ("qt", "qtcreator")),
        ("qt5-", ("qt", "qtcreator")),
        ("qt6-", ("qt", "qtcreator")),
        ("redis-", ("database", "server-database")),
        ("ruby-", ("ruby", "applications-development")),
        ("rust-", ("rust", "cargo")),
        ("sdl", ("applications-games", "package-x-generic")),
        ("sqlite-", ("database", "server-database")),
        ("systemd-", ("preferences-system", "applications-system")),
        ("ttf-", ("font-x-generic", "preferences-desktop-font")),
        ("vulkan-", ("video-display", "preferences-desktop-display")),
        ("wayland-", ("video-display", "preferences-desktop-display")),
        ("webkit", ("web-browser", "applications-internet")),
        ("wine-", ("wine", "applications-games")),
        ("xcb-", ("video-display", "preferences-desktop-display")),
        ("xf86-", ("video-display", "preferences-desktop-display")),
        ("xorg-", ("video-display", "preferences-desktop-display")),
    )
    SUBSTRING_ICON_ALIASES = (
        ("bluetooth", ("bluetooth", "preferences-system-bluetooth")),
        ("certificate", ("security-high", "certificate", "application-certificate")),
        ("codec", ("applications-multimedia", "multimedia-video-player")),
        ("cursor", ("preferences-desktop-mouse", "preferences-desktop-theme")),
        ("database", ("database", "server-database")),
        ("driver", ("preferences-system", "video-display")),
        ("firmware", ("drive-removable-media", "preferences-system")),
        ("font", ("font-x-generic", "preferences-desktop-font")),
        ("gtk", ("gtk", "preferences-desktop-theme")),
        ("icon-theme", ("preferences-desktop-icons", "preferences-desktop-theme")),
        ("kernel", ("linux", "tux", "computer")),
        ("kde", ("kde", "preferences-desktop-plasma")),
        ("linux", ("linux", "tux", "computer")),
        ("network", ("network-workgroup", "preferences-system-network")),
        ("plasma", ("kde", "preferences-desktop-plasma")),
        ("printer", ("printer", "preferences-devices-printer")),
        ("sound", ("audio-card", "preferences-desktop-sound")),
        ("theme", ("preferences-desktop-theme", "preferences-desktop-icons")),
        ("vulkan", ("video-display", "preferences-desktop-display")),
        ("wayland", ("video-display", "preferences-desktop-display")),
        ("xorg", ("video-display", "preferences-desktop-display")),
    )
    SOURCE_METADATA_ICON_ALIASES = (
        (FirmwarePackageMetadata, ("drive-removable-media", "preferences-system", "computer")),
        (PlasmaWidgetPackageMetadata, ("kde", "preferences-desktop-plasma")),
        (AurPackageMetadata, ("package-x-generic", "applications-system")),
    )

    def __init__(
        self,
        *,
        appstream_icon_roots: tuple[Path, ...] | None = None,
        icon_theme_roots: tuple[Path, ...] | None = None,
        desktop_entry_roots: tuple[Path, ...] | None = None,
        flatpak_appstream_roots: tuple[Path, ...] | None = None,
    ) -> None:
        self._appstream_icon_roots = appstream_icon_roots or self.APPSTREAM_ICON_ROOTS
        self._icon_theme_roots = icon_theme_roots or self.ICON_THEME_ROOTS
        self._desktop_entry_roots = desktop_entry_roots or self.DESKTOP_ENTRY_ROOTS
        self._flatpak_appstream_roots = flatpak_appstream_roots or self.FLATPAK_APPSTREAM_ROOTS
        self._cache: dict[str, Path | None] = {}
        self._theme_dirs_cache: dict[Path, list[Path]] = {}
        self._theme_icon_cache: dict[str, Path | None] = {}

    def icon_path_for(self, package: PackageUpdate) -> Path | None:
        cache_key = package.id
        if cache_key in self._cache:
            return self._cache[cache_key]

        resolved = self._resolve_icon_path(package)
        self._cache[cache_key] = resolved
        return resolved

    def _resolve_icon_path(self, package: PackageUpdate) -> Path | None:
        if isinstance(package.source_metadata, FlatpakPackageMetadata):
            flatpak_icon = self._flatpak_icon_path(package)
            if flatpak_icon is not None:
                return flatpak_icon

        for name in self._candidate_names(package):
            direct_path = self._direct_icon_path(name)
            if direct_path is not None:
                return direct_path

        for name in self._candidate_names(package):
            appstream_icon = self._appstream_icon_path(name)
            if appstream_icon is not None:
                return appstream_icon

        for name in self._candidate_names(package):
            desktop_icon = self._desktop_entry_icon_path(name)
            if desktop_icon is not None:
                return desktop_icon

        for name in self._candidate_names(package):
            theme_icon = self._theme_icon_path(name)
            if theme_icon is not None:
                return theme_icon

        return None

    def _candidate_names(self, package: PackageUpdate) -> list[str]:
        plugin_id = (
            package.source_metadata.plugin_id
            if isinstance(package.source_metadata, PlasmaWidgetPackageMetadata)
            else ""
        )
        raw_names = [
            package.name,
            package.backend_id or "",
            plugin_id or "",
            package.icon_name or "",
        ]
        names: list[str] = []
        for raw_name in raw_names:
            for name in self._expanded_name_candidates(raw_name):
                if name and name not in names:
                    names.append(name)
        for name in self._semantic_icon_names(package):
            if name not in names:
                names.append(name)
        return names

    def _expanded_name_candidates(self, raw_name: str) -> list[str]:
        name = raw_name.strip()
        if not name:
            return []
        candidates = [name]
        normalized = name.lower()
        if normalized != name:
            candidates.append(normalized)
        if "/" in name:
            parts = [part for part in name.split("/") if part]
            candidates.extend(parts)
            if len(parts) >= 2:
                candidates.append(parts[1])
        if "." in name:
            candidates.append(name.rsplit(".", 1)[-1])
        return candidates

    def _semantic_icon_names(self, package: PackageUpdate) -> list[str]:
        normalized = package.name.strip().lower()
        if not normalized:
            return []
        aliases = list(self.EXACT_ICON_ALIASES.get(normalized, ()))
        for prefix, icon_names in self.PREFIX_ICON_ALIASES:
            if normalized.startswith(prefix):
                aliases.extend(icon_names)

        tokens = set(normalized.replace("_", "-").replace(".", "-").split("-"))
        for token in tokens:
            aliases.extend(self.EXACT_ICON_ALIASES.get(token, ()))

        for token, icon_names in self.SUBSTRING_ICON_ALIASES:
            if token in normalized:
                aliases.extend(icon_names)

        metadata = package.source_metadata
        if isinstance(metadata, FlatpakPackageMetadata):
            if metadata.ref_kind is not None and metadata.ref_kind.value == "runtime":
                aliases.extend(("package-x-generic", "application-x-sharedlib"))
            aliases.extend(("flatpak", "application-x-flatpak", "package-x-generic"))
        else:
            for metadata_type, icon_names in self.SOURCE_METADATA_ICON_ALIASES:
                if isinstance(metadata, metadata_type):
                    aliases.extend(icon_names)
                    break

        unique_aliases: list[str] = []
        for alias in aliases:
            if alias and alias not in unique_aliases:
                unique_aliases.append(alias)
        return unique_aliases

    def _direct_icon_path(self, value: str) -> Path | None:
        path = Path(value).expanduser()
        if path.is_absolute() and path.exists() and path.suffix.lower().lstrip(".") in self.ICON_EXTENSIONS:
            return path
        return None

    def _appstream_icon_path(self, package_name: str) -> Path | None:
        for root in self._appstream_icon_roots:
            if not root.exists():
                continue
            for repo in self.APPSTREAM_REPOS:
                for size in self.ICON_SIZES:
                    icon = self._first_matching_icon(root / repo / size, package_name)
                    if icon is not None:
                        return icon
        return None

    def _desktop_entry_icon_path(self, package_name: str) -> Path | None:
        for root in self._desktop_entry_roots:
            desktop_entry = root / f"{package_name}.desktop"
            if not desktop_entry.exists():
                continue
            icon_name = self._read_desktop_icon_name(desktop_entry)
            if not icon_name:
                continue
            direct_path = self._direct_icon_path(icon_name)
            if direct_path is not None:
                return direct_path
            theme_icon = self._theme_icon_path(icon_name)
            if theme_icon is not None:
                return theme_icon
        return None

    def _read_desktop_icon_name(self, desktop_entry: Path) -> str | None:
        try:
            lines = desktop_entry.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        for line in lines:
            if line.startswith("Icon="):
                return line.split("=", 1)[1].strip() or None
        return None

    def _theme_icon_path(self, icon_name: str) -> Path | None:
        cache_key = icon_name.strip()
        if cache_key in self._theme_icon_cache:
            return self._theme_icon_cache[cache_key]

        resolved: Path | None = None
        for root in self._icon_theme_roots:
            if not root.exists():
                continue
            if root.name == "pixmaps":
                icon = self._first_matching_icon(root, icon_name)
                if icon is not None:
                    resolved = icon
                    break
                continue
            for icon_dir in self._theme_icon_dirs(root):
                icon = self._first_matching_icon(icon_dir, icon_name)
                if icon is not None:
                    resolved = icon
                    break
            if resolved is not None:
                break
        self._theme_icon_cache[cache_key] = resolved
        return resolved

    def _theme_icon_dirs(self, root: Path) -> list[Path]:
        if root in self._theme_dirs_cache:
            return self._theme_dirs_cache[root]

        dirs: list[Path] = []
        try:
            theme_dirs = list(root.iterdir())
        except OSError:
            self._theme_dirs_cache[root] = []
            return []

        for theme_dir in theme_dirs:
            if not theme_dir.is_dir():
                continue
            for size in self.THEME_SIZE_DIRS:
                for category in self.ICON_CONTEXTS:
                    dirs.append(theme_dir / size / category)
                    dirs.append(theme_dir / category / size)
            for category in self.ICON_CONTEXTS:
                dirs.append(theme_dir / category / "symbolic")
            dirs.append(theme_dir)
        self._theme_dirs_cache[root] = dirs
        return dirs

    def _first_matching_icon(self, icon_dir: Path, icon_name: str) -> Path | None:
        if not icon_dir.exists():
            return None
        for suffix in self.ICON_EXTENSIONS:
            exact = icon_dir / f"{icon_name}.{suffix}"
            if exact.exists():
                return exact
            for path in icon_dir.glob(f"{icon_name}_*.{suffix}"):
                return path
        return None

    def _flatpak_icon_path(self, package: PackageUpdate) -> Path | None:
        app_id = self._flatpak_app_id(package)
        remote = self._flatpak_remote(package)
        if not app_id or not remote:
            return None

        for base_path in self._flatpak_appstream_roots:
            for size in self.ICON_SIZES:
                path = (
                    base_path
                    / remote
                    / "x86_64"
                    / "active"
                    / "icons"
                    / size
                    / f"{app_id}.png"
                )
                if path.exists():
                    return path
        return None

    def _flatpak_app_id(self, package: PackageUpdate) -> str:
        value = package.backend_id or package.name
        parts = [part for part in value.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"app", "runtime"}:
            return parts[1]
        return value.strip()

    def _flatpak_remote(self, package: PackageUpdate) -> str:
        metadata = package.source_metadata
        if not isinstance(metadata, FlatpakPackageMetadata):
            return ""
        repository = metadata.repository or ""
        if "(" in repository:
            repository = repository.split("(", 1)[0]
        return repository.strip()
