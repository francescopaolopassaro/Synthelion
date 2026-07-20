# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from synthelion.devtools.crew_service import _extract_symbols
from synthelion.nlp.text_rank import TextRankSummarizer

_IGNORE_DIR_NAMES = frozenset({
    ".git", ".svn", ".hg", "node_modules", "bin", "obj", "dist", "build",
    ".vs", ".idea", "__pycache__", "packages", ".nuget",
})
# Only genuinely disposable build artifacts are dropped outright — everything else
# (images, PDFs, archives, ...) is still catalogued as a binary asset, just not read.
_IGNORE_FILE_SUFFIXES = (".pdb", ".min.js", ".map", ".lock")

_INCLUDE_EXTENSIONS = frozenset({
    ".cs", ".csproj", ".sln", ".vb", ".fs",
    ".py", ".txt", ".json", ".xml", ".config", ".yml", ".yaml",
    ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".md", ".sh", ".bat", ".ps1", ".sql", ".proto", ".graphql",
    ".ini", ".toml", ".csv", ".rs", ".go", ".java", ".kt", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".swift", ".r", ".jl", ".lua", ".dart",
})

_LANGUAGE_HINTS = {
    ".cs": "csharp", ".vb": "vbnet", ".fs": "fsharp", ".py": "python",
    ".js": "javascript", ".ts": "typescript", ".jsx": "jsx", ".tsx": "tsx",
    ".json": "json", ".xml": "xml", ".yml": "yaml", ".yaml": "yaml",
    ".html": "html", ".css": "css", ".scss": "scss", ".sql": "sql",
    ".sh": "bash", ".bat": "powershell", ".ps1": "powershell", ".md": "markdown",
    ".csproj": "xml", ".sln": "xml", ".rs": "rust", ".go": "go", ".java": "java",
    ".kt": "kotlin", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".swift": "swift", ".r": "r", ".jl": "julia",
    ".lua": "lua", ".dart": "dart", ".toml": "toml", ".ini": "ini", ".csv": "csv",
}

# Non-text file categories: catalogued (path, size, category) but never read as
# text — a project can be a photo/PDF/media archive just as validly as a codebase.
_BINARY_CATEGORY_EXTENSIONS: dict[str, str] = {
    **{e: "image" for e in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico", ".heic", ".raw", ".psd", ".ai")},
    **{e: "document" for e in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf")},
    **{e: "archive" for e in (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso")},
    **{e: "audio" for e in (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma")},
    **{e: "video" for e in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv")},
    **{e: "font" for e in (".ttf", ".otf", ".woff", ".woff2")},
    **{e: "binary" for e in (".dll", ".exe", ".so", ".dylib", ".bin", ".dat", ".db", ".sqlite")},
    ".svg": "image",  # text-based but treated as a media asset, not source code
}


@dataclass
class Dependency:
    name: str
    version: str | None = None
    source: str = ""


@dataclass
class FileEntry:
    relative_path: str
    size: int
    extension: str
    line_count: int = 0
    is_binary: bool = False
    category: str = "text"
    symbols: list = field(default_factory=list)  # CavecrewSymbol, for code files only

# Extensions worth symbol-extracting for the "Key Components" synthesis — a subset of
# _INCLUDE_EXTENSIONS: actual programming languages, not markup/data/config files.
_CODE_EXTENSIONS = frozenset({
    ".cs", ".vb", ".fs", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".rs", ".go", ".java", ".kt", ".rb", ".php", ".c", ".h", ".cpp", ".hpp",
    ".swift", ".r", ".jl", ".lua", ".dart",
})


@dataclass
class ProjectInfo:
    name: str = "Unknown"
    root_path: str = ""
    type: str = "Unknown"
    description: str | None = None
    version: str | None = None
    dependencies: list[Dependency] = field(default_factory=list)
    engines: dict[str, str] = field(default_factory=dict)  # e.g. {"node": ">=18", "npm": ">=9"}


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for suffix in ("B", "KB", "MB", "GB"):
        if size < 1024 or suffix == "GB":
            return f"{size:.2g} {suffix}" if suffix != "B" else f"{int(size)} {suffix}"
        size /= 1024
    return f"{size:.2g} GB"


def _should_ignore(path: str, filename: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if any(p in _IGNORE_DIR_NAMES for p in parts):
        return True
    low = filename.lower()
    return any(low.endswith(suf) for suf in _IGNORE_FILE_SUFFIXES)


class ProjectWiki:
    """Generates an AI-authored synthesis of a project — the kind of overview a person
    (or an AI assistant) would write documenting a repo, not a mechanical file dump.

    Works for any project, not just source code: a photo archive, a PDF/document
    collection, or a mix of the two. Recursively scans a folder and produces a
    Markdown document with:
      - an Overview paragraph (summarized from README if present, else synthesized
        from the file/type breakdown)
      - dependencies (for recognized code-project manifests)
      - the file tree
      - Key Components: per-file class/function symbols for code files, capped and
        ranked — not every file's full contents
      - Media & Binary Assets: images/PDFs/archives/etc. grouped by category with
        counts and sizes, not enumerated file-by-file

    Extends CavemanWiki (C# CavemanWiki was code-project-only and dumped compressed
    file contents verbatim); this port is content-agnostic and synthesis-first.
    """

    def generate(
        self,
        project_folder_path: str,
        max_file_size_bytes: int = 200 * 1024,
        include_contents: bool = True,
    ) -> str:
        if not os.path.isdir(project_folder_path):
            raise NotADirectoryError(f"Directory not found: {project_folder_path}")

        info = self._analyze_project(project_folder_path)
        files = self._scan_files(project_folder_path, max_file_size_bytes)
        readme_summary = self._summarize_readme(project_folder_path) if include_contents else None

        parts = [
            self._write_header(project_folder_path, info),
            self._write_overview(info, files, readme_summary),
            self._write_dependencies(info.dependencies),
            self._write_structure(files),
        ]
        if include_contents:
            parts.append(self._write_assets(files))
            parts.append(self._write_key_components(files))
        parts.append(self._write_summary(files))
        return "".join(p for p in parts if p)

    # ------------------------------------------------------------------

    def _analyze_project(self, root_path: str) -> ProjectInfo:
        info = ProjectInfo(name=os.path.basename(root_path.rstrip("/\\")) or "UnknownProject", root_path=root_path)

        try:
            entries = os.listdir(root_path)
        except OSError:
            entries = []

        for fname in entries:
            full = os.path.join(root_path, fname)
            if not os.path.isfile(full):
                continue
            low = fname.lower()

            if low.endswith(".sln"):
                info.type = "VisualStudio"
            elif low.endswith(".csproj"):
                info.type = "CSharp"
                self._parse_csproj(full, info)
            elif low == "requirements.txt":
                info.type = "Python"
                self._parse_requirements(full, info)
            elif low == "package.json":
                info.type = "NodeJs"
                self._parse_package_json(full, info)
            elif low in ("pyproject.toml", "setup.py"):
                info.type = "Python"
            elif low == "pom.xml":
                info.type = "Java"
            elif low == "cargo.toml":
                info.type = "Rust"

        if any(f.lower() == "tsconfig.json" for f in entries):
            info.type = "NodeJs/TypeScript" if info.type == "NodeJs" else (info.type if info.type != "Unknown" else "TypeScript")

        if info.type == "Unknown":
            info.type = self._detect_type_by_extensions(root_path)

        return info

    def _scan_files(self, root_path: str, max_size: int) -> list[FileEntry]:
        files: list[FileEntry] = []
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIR_NAMES]
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, root_path)
                if _should_ignore(rel, fname):
                    continue

                ext = os.path.splitext(fname)[1].lower()

                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue

                category = _BINARY_CATEGORY_EXTENSIONS.get(ext)
                if category is not None:
                    # Binary/media asset: catalogued regardless of size, never read as text —
                    # a photo/PDF/audio archive is a legitimate project, not noise to skip.
                    files.append(FileEntry(relative_path=rel, size=size, extension=ext, is_binary=True, category=category))
                    continue

                if ext not in _INCLUDE_EXTENSIONS and ext != "":
                    # Unrecognized extension, not a known binary type either: catalogue as a
                    # generic "other" asset rather than silently dropping it.
                    files.append(FileEntry(relative_path=rel, size=size, extension=ext, is_binary=True, category="other"))
                    continue

                if size > max_size:
                    # Too large to read cheaply for symbol extraction — still catalogued in
                    # the tree, just without a Key Components entry.
                    files.append(FileEntry(relative_path=rel, size=size, extension=ext))
                    continue

                symbols = []
                line_count = 0
                if ext in _CODE_EXTENSIONS:
                    try:
                        with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                            content = fh.read()
                        line_count = content.count("\n") + 1 if content else 0
                        symbols = _extract_symbols(content)
                    except OSError:
                        pass

                files.append(FileEntry(relative_path=rel, size=size, extension=ext, line_count=line_count, symbols=symbols))

        return sorted(files, key=lambda f: f.relative_path)

    def _summarize_readme(self, root_path: str) -> str | None:
        try:
            entries = os.listdir(root_path)
        except OSError:
            return None

        readme_name = next((f for f in entries if f.lower().startswith("readme")), None)
        if not readme_name:
            return None

        full = os.path.join(root_path, readme_name)
        if not os.path.isfile(full):
            return None

        try:
            with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            return None

        clean = re.sub(r"[#*`_]|!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)", r"\1", text).strip()
        if not clean:
            return None

        try:
            summary = TextRankSummarizer().summarize(clean, sentence_count=4)
            if summary and summary.strip():
                return summary.strip()
        except Exception:
            pass
        return clean[:600].strip()

    # ------------------------------------------------------------------

    def _write_header(self, root_path: str, info: ProjectInfo) -> str:
        lines = [
            f"# 🪨 Project Wiki: {info.name}", "",
            "```yaml", "project:",
            f"  name: {info.name}",
            f"  type: {info.type}",
            f"  path: {root_path}",
            f"  generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        ]
        if info.description:
            lines.append(f"  description: {info.description}")
        if info.version:
            lines.append(f"  version: {info.version}")
        if info.engines:
            lines.append("  engines:")
            for name, version in info.engines.items():
                lines.append(f"    {name}: {version}")
        lines += ["```", ""]
        return "\n".join(lines) + "\n"

    def _write_dependencies(self, dependencies: list[Dependency]) -> str:
        if not dependencies:
            return ""
        lines = ["## 📦 Dependencies", "", "```yaml", "dependencies:"]
        by_source: dict[str, list[Dependency]] = {}
        for d in dependencies:
            by_source.setdefault(d.source, []).append(d)
        for source, deps in by_source.items():
            lines.append(f"  {source}:")
            for d in deps:
                version = f" @ {d.version}" if d.version else ""
                lines.append(f"    - {d.name}{version}")
        lines += ["```", ""]
        return "\n".join(lines) + "\n"

    def _write_overview(self, info: ProjectInfo, files: list[FileEntry], readme_summary: str | None) -> str:
        lines = ["## 🧭 Overview", ""]
        lines.append(readme_summary if readme_summary else self._synthesize_overview(info, files))
        lines += [""]
        return "\n".join(lines) + "\n"

    def _synthesize_overview(self, info: ProjectInfo, files: list[FileEntry]) -> str:
        if not files:
            return f"This is an empty {info.type} project — no cataloguable files were found."

        text_files = [f for f in files if not f.is_binary]
        binary_files = [f for f in files if f.is_binary]
        dirs = {os.path.dirname(f.relative_path) for f in files if os.path.dirname(f.relative_path)}

        binary_share = len(binary_files) / len(files)

        sentences = [
            f"This {info.type} project contains {len(files)} files across {len(dirs) or 1} directories."
        ]

        if binary_share >= 0.6 and binary_files:
            by_cat: dict[str, int] = {}
            for f in binary_files:
                by_cat[f.category] = by_cat.get(f.category, 0) + 1
            top_cats = sorted(by_cat.items(), key=lambda kv: -kv[1])[:3]
            cat_desc = ", ".join(f"{count} {cat}" for cat, count in top_cats)
            sentences.append(f"It is primarily a media/document archive: {cat_desc}.")
            if text_files:
                sentences.append(f"It also includes {len(text_files)} supporting text/code file(s).")
        elif text_files:
            ext_count: dict[str, int] = {}
            for f in text_files:
                ext_count[f.extension or "(no ext)"] = ext_count.get(f.extension or "(no ext)", 0) + 1
            top_ext = sorted(ext_count.items(), key=lambda kv: -kv[1])[:3]
            ext_desc = ", ".join(f"{count} {_LANGUAGE_HINTS.get(ext, ext.lstrip('.') or 'plain')} file(s)" for ext, count in top_ext)
            sentences.append(f"The dominant content is code/text: {ext_desc}.")
            if binary_files:
                sentences.append(f"It also carries {len(binary_files)} binary/media asset(s).")

        return " ".join(sentences)

    def _write_structure(self, files: list[FileEntry]) -> str:
        lines = ["## 📁 File Structure", "", "```", _build_tree(files), "```", ""]
        return "\n".join(lines) + "\n"

    def _write_assets(self, files: list[FileEntry]) -> str:
        binaries = [f for f in files if f.is_binary]
        if not binaries:
            return ""

        by_cat: dict[str, list[FileEntry]] = {}
        for f in binaries:
            by_cat.setdefault(f.category, []).append(f)

        lines = ["## 🗂️ Media & Binary Assets", ""]
        for cat, items in sorted(by_cat.items(), key=lambda kv: -sum(i.size for i in kv[1])):
            total = sum(i.size for i in items)
            lines.append(f"- **{cat}** — {len(items)} file(s), {_format_size(total)}")
            examples = ", ".join(f"`{i.relative_path}`" for i in items[:3])
            more = f", … +{len(items) - 3} more" if len(items) > 3 else ""
            lines.append(f"  e.g. {examples}{more}")
        lines.append("")
        return "\n".join(lines) + "\n"

    def _write_key_components(self, files: list[FileEntry]) -> str:
        code_files = [f for f in files if f.symbols]
        if not code_files:
            return ""

        top_k = 25
        ranked = sorted(code_files, key=lambda f: -len(f.symbols))
        lines = ["## 🔑 Key Components", ""]
        for f in ranked[:top_k]:
            top_syms = ", ".join(f"{s.kind} `{s.name}`" for s in f.symbols[:5])
            more = f" (+{len(f.symbols) - 5} more)" if len(f.symbols) > 5 else ""
            lines.append(f"- **`{f.relative_path}`** — {top_syms}{more}")
        if len(ranked) > top_k:
            lines.append(f"- … and {len(ranked) - top_k} more file(s) with code symbols")
        lines.append("")
        return "\n".join(lines) + "\n"

    def _write_summary(self, files: list[FileEntry]) -> str:
        total_size = sum(f.size for f in files)
        lines = [
            "## 📊 Summary", "",
            f"- **Total Files:** {len(files)}",
            f"- **Total Size:** {_format_size(total_size)}",
            "",
            "> 💡 *This wiki is a synthesis, not a raw dump: the overview is summarized from "
            "the README (or inferred from file composition), and only the most relevant code "
            "symbols and asset categories are listed.*",
        ]
        return "\n".join(lines) + "\n"

    def _detect_type_by_extensions(self, root_path: str) -> str:
        ext_count: dict[str, int] = {}
        count = 0
        for _dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIR_NAMES]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext:
                    ext_count[ext] = ext_count.get(ext, 0) + 1
                count += 1
                if count >= 100:
                    break
            if count >= 100:
                break

        if ".cs" in ext_count or ".csproj" in ext_count:
            return "CSharp"
        if ".py" in ext_count:
            return "Python"
        if ".js" in ext_count or ".ts" in ext_count:
            return "NodeJs"
        if ".java" in ext_count:
            return "Java"
        if ".rs" in ext_count:
            return "Rust"
        return "Generic"

    # ------------------------------------------------------------------

    def _parse_csproj(self, csproj_path: str, info: ProjectInfo) -> None:
        try:
            tree = ET.parse(csproj_path)
        except ET.ParseError:
            return
        root = tree.getroot()

        for node in root.iter():
            tag = node.tag.split("}")[-1]
            if tag == "PackageReference":
                name = node.attrib.get("Include") or node.attrib.get("Update")
                version = node.attrib.get("Version")
                if name:
                    info.dependencies.append(Dependency(name=name, version=version, source="NuGet"))
            elif tag == "ProjectReference":
                include = node.attrib.get("Include")
                if include:
                    name = os.path.splitext(os.path.basename(include))[0]
                    info.dependencies.append(Dependency(name=name, source="ProjectReference"))
            elif tag == "AssemblyName" and node.text:
                info.name = node.text
            elif tag == "Version" and node.text:
                info.version = node.text

    def _parse_requirements(self, req_path: str, info: ProjectInfo) -> None:
        try:
            with open(req_path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except OSError:
            return
        for line in lines:
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#"):
                continue
            m = re.match(r"^([a-zA-Z0-9_-]+)\s*([=<>!]+)\s*([\d.]+)", trimmed)
            if m:
                info.dependencies.append(Dependency(name=m.group(1), version=m.group(3), source="PyPI"))
            else:
                info.dependencies.append(Dependency(name=trimmed, source="PyPI"))

    # Every npm dependency section worth surfacing, mapped to a Dependency.source label.
    _NPM_DEPENDENCY_SECTIONS = (
        ("dependencies", "npm"),
        ("devDependencies", "npm:dev"),
        ("peerDependencies", "npm:peer"),
        ("optionalDependencies", "npm:optional"),
    )

    def _parse_package_json(self, pkg_path: str, info: ProjectInfo) -> None:
        try:
            with open(pkg_path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            return

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._parse_package_json_fallback(text, info)
            return

        if isinstance(data.get("name"), str):
            info.name = data["name"]
        if isinstance(data.get("version"), str):
            info.version = data["version"]
        if isinstance(data.get("description"), str):
            info.description = data["description"]

        engines = data.get("engines")
        if isinstance(engines, dict):
            for k, v in engines.items():
                if isinstance(v, str):
                    info.engines[k] = v  # e.g. node, npm, pnpm, yarn version ranges

        package_manager = data.get("packageManager")
        if isinstance(package_manager, str) and "@" in package_manager:
            pm_name, pm_version = package_manager.split("@", 1)
            info.engines.setdefault(pm_name, pm_version)

        for section, source in self._NPM_DEPENDENCY_SECTIONS:
            deps = data.get(section)
            if not isinstance(deps, dict):
                continue
            for dep_name, dep_version in deps.items():
                info.dependencies.append(Dependency(name=dep_name, version=str(dep_version), source=source))

    def _parse_package_json_fallback(self, text: str, info: ProjectInfo) -> None:
        """Regex-based extraction for malformed/JSON5-style package.json that json.loads rejects."""
        m = re.search(r'"name"\s*:\s*"([^"]+)"', text)
        if m:
            info.name = m.group(1)
        m = re.search(r'"version"\s*:\s*"([^"]+)"', text)
        if m:
            info.version = m.group(1)
        m = re.search(r'"description"\s*:\s*"([^"]+)"', text)
        if m:
            info.description = m.group(1)

        for section, source in self._NPM_DEPENDENCY_SECTIONS:
            sm = re.search(r'"%s"\s*:\s*\{([^}]+)\}' % re.escape(section), text)
            if not sm:
                continue
            for pm in re.finditer(r'"([^"]+)"\s*:\s*"([^"]+)"', sm.group(1)):
                info.dependencies.append(Dependency(name=pm.group(1), version=pm.group(2), source=source))


class _TreeNode:
    __slots__ = ("name", "is_file", "size", "children")

    def __init__(self, name: str) -> None:
        self.name = name
        self.is_file = False
        self.size = 0
        self.children: dict[str, "_TreeNode"] = {}


def _build_tree(files: list[FileEntry]) -> str:
    root = _TreeNode("root")
    for f in files:
        parts = f.relative_path.replace("\\", "/").split("/")
        node = root
        for part in parts:
            node = node.children.setdefault(part, _TreeNode(part))
        node.is_file = True
        node.size = f.size

    return _render_tree(root, "", True).rstrip("\n")


def _render_tree(node: _TreeNode, prefix: str, is_last: bool) -> str:
    out = []
    if node.name != "root":
        out.append(prefix)
        out.append("└── " if is_last else "├── ")
        out.append(node.name)
        if node.is_file:
            out.append(f" [{_format_size(node.size)}]")
        out.append("\n")

    children = list(node.children.values())
    for i, child in enumerate(children):
        new_prefix = prefix + ("    " if is_last else "│   ")
        out.append(_render_tree(child, new_prefix, i == len(children) - 1))

    return "".join(out)
