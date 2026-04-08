"""
Cross-platform binary analysis using lief.
Handles PE (Windows .exe/.dll), ELF (Linux), and Mach-O (macOS) formats.
Also retains pefile for Windows-specific metadata (version strings, resources).

Supported formats:
  PE    — .exe, .dll, .sys, .scr, .com, .ocx  (Windows)
  ELF   — no extension, .so, .so.*, .o, .ko   (Linux)
  MachO — no extension, .dylib, .bundle       (macOS)
  DEX   — .dex, .apk                          (Android — parsed via lief too)
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

import lief

_OS = platform.system()  # "Windows", "Linux", "Darwin"


def analyze_binary(path: str) -> dict[str, Any]:
    """
    Auto-detect binary format and extract all available attributes.
    Returns a flat dict suitable for merging into a File node's props.
    """
    props: dict[str, Any] = {}

    binary = lief.parse(path)
    if binary is None:
        return {"binary_parse_error": "unrecognized format"}

    fmt = binary.format
    props["binary_format"] = str(fmt).split(".")[-1]  # PE / ELF / MACHO

    if isinstance(binary, lief.PE.Binary):
        props.update(_analyze_pe(binary, path))
    elif isinstance(binary, lief.ELF.Binary):
        props.update(_analyze_elf(binary, path))
    elif isinstance(binary, lief.MachO.FatBinary):
        # Fat binary — analyze first slice
        props.update(_analyze_macho(binary[0], path))
        props["is_universal"] = True
        props["architectures"] = ",".join(
            str(b.header.cpu_type).split(".")[-1] for b in binary
        )
    elif isinstance(binary, lief.MachO.Binary):
        props.update(_analyze_macho(binary, path))

    # Code signing (platform-specific)
    props.update(_check_signature(path, props.get("binary_format", "")))

    return {k: v for k, v in props.items() if v is not None}


# ── PE (Windows) ──────────────────────────────────────────────────────────────

def _analyze_pe(binary: "lief.PE.Binary", path: str) -> dict[str, Any]:
    props: dict[str, Any] = {}
    header = binary.header
    opt = binary.optional_header

    # Architecture
    machine = str(header.machine).split(".")[-1]
    props["architecture"] = {
        "AMD64": "x64", "I386": "x86", "ARM64": "arm64",
        "ARM": "arm32"
    }.get(machine, machine)

    # Characteristics
    props["is_dll"]    = binary.is_dll
    props["is_exe"]    = binary.is_exe
    props["is_driver"] = binary.is_driver

    # Subsystem
    props["subsystem"] = str(opt.subsystem).split(".")[-1]

    # Imports
    if binary.has_imports:
        import_libs = [imp.name.lower() for imp in binary.imports]
        props["imports_count"] = len(import_libs)
        # Interesting imports hint at capability
        props["has_network"]  = any("ws2_" in l or "winhttp" in l or "wininet" in l for l in import_libs)
        props["has_crypto"]   = any("crypt" in l or "bcrypt" in l for l in import_libs)
        props["has_registry"] = any("advapi" in l for l in import_libs)

    # Exports (DLLs)
    if binary.has_exports:
        props["exports_count"] = len(list(binary.exported_functions))

    # Sections entropy
    entropies = [s.entropy for s in binary.sections]
    if entropies:
        props["entropy"] = round(max(entropies), 3)
        props["is_packed"] = props["entropy"] > 7.0

    # Debug info
    if binary.has_debug:
        for dbg in binary.debug:
            if hasattr(dbg, "pdb_filename") and dbg.pdb_filename:
                props["pdb_path"] = dbg.pdb_filename
                break

    # Rich header (compiler fingerprint)
    if binary.has_rich_header:
        tools = []
        for entry in binary.rich_header.entries:
            tools.append(f"{entry.id}:{entry.build_id}x{entry.count}")
        props["rich_header"] = ",".join(tools[:5])

    # TLS (anti-debug indicator)
    props["has_tls"] = binary.has_tls

    # Resources version info via pefile (more reliable for strings)
    try:
        import pefile
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
        )
        if hasattr(pe, "VS_VERSIONINFO"):
            for vi in pe.VS_VERSIONINFO:
                if hasattr(vi, "StringFileInfo"):
                    for sfi in vi.StringFileInfo:
                        for st in sfi.StringTable:
                            for k, v in st.entries.items():
                                ks = k.decode(errors="replace").lower()
                                vs = v.decode(errors="replace").strip()
                                if "productname" in ks:    props["product_name"]   = vs
                                elif "companyname" in ks:  props["company_name"]   = vs
                                elif "filedescription" in ks: props["file_description"] = vs
                                elif "fileversion" in ks:  props["file_version"]   = vs
                                elif "productversion" in ks: props["product_version"] = vs
                                elif "legalcopyright" in ks: props["copyright"]    = vs
        pe.close()
    except Exception:
        pass

    return props


# ── ELF (Linux) ───────────────────────────────────────────────────────────────

def _analyze_elf(binary: "lief.ELF.Binary", path: str) -> dict[str, Any]:
    props: dict[str, Any] = {}
    header = binary.header

    # Architecture
    machine = str(header.machine_type).split(".")[-1]
    props["architecture"] = {
        "X86_64": "x64", "i386": "x86", "AARCH64": "arm64",
        "ARM": "arm32", "MIPS": "mips", "RISCV": "riscv"
    }.get(machine, machine)

    props["elf_type"]      = str(header.file_type).split(".")[-1]   # EXEC/DYN/REL
    props["is_pie"]        = binary.is_pie
    props["is_stripped"]   = not binary.has_debug_info
    props["nx_enabled"]    = binary.has_nx

    # Interpreter (dynamic linker)
    try:
        props["interpreter"] = binary.interpreter
    except Exception:
        pass

    # Libraries
    libs = list(binary.libraries)
    props["imports_count"] = len(libs)
    props["has_network"]   = any("libc.so" in l or "libssl" in l or "libcurl" in l for l in libs)
    props["has_crypto"]    = any("libssl" in l or "libcrypto" in l for l in libs)

    # Sections entropy
    entropies = [s.entropy for s in binary.sections if s.size > 0]
    if entropies:
        props["entropy"]   = round(max(entropies), 3)
        props["is_packed"] = props["entropy"] > 7.0

    # Symbols
    try:
        syms = [s.name for s in binary.exported_functions if s.name]
        props["exports_count"] = len(syms)
    except Exception:
        pass

    # RPATH / RUNPATH (supply chain indicator)
    try:
        rpath = binary.get(lief.ELF.DynamicEntry.TAG.RPATH)
        if rpath:
            props["rpath"] = rpath.name
    except Exception:
        pass

    return props


# ── Mach-O (macOS) ───────────────────────────────────────────────────────────

def _analyze_macho(binary: "lief.MachO.Binary", path: str) -> dict[str, Any]:
    props: dict[str, Any] = {}
    header = binary.header

    cpu = str(header.cpu_type).split(".")[-1]
    props["architecture"] = {
        "X86_64": "x64", "ARM64": "arm64", "ARM64E": "arm64e",
        "x86": "x86"
    }.get(cpu, cpu)

    props["macho_type"]  = str(header.file_type).split(".")[-1]
    props["is_pie"]      = binary.is_pie
    props["is_stripped"] = not binary.has_debug_info

    # Libraries
    libs = [lib.name for lib in binary.libraries]
    props["imports_count"] = len(libs)
    props["has_network"]   = any("Network" in l or "CFNetwork" in l for l in libs)
    props["has_crypto"]    = any("Security" in l or "CommonCrypto" in l for l in libs)

    # Code signature presence (detail checked separately)
    props["has_code_signature"] = binary.has_code_signature

    # Entitlements
    if binary.has_entitlements:
        props["has_entitlements"] = True

    # Min OS version
    try:
        for cmd in binary.commands:
            if hasattr(cmd, "sdk"):
                props["min_os_version"] = str(cmd.sdk)
                break
    except Exception:
        pass

    # Sections entropy
    entropies = [s.entropy for s in binary.sections if s.size > 0]
    if entropies:
        props["entropy"]   = round(max(entropies), 3)
        props["is_packed"] = props["entropy"] > 7.0

    return props


# ── Code signing (platform-aware) ─────────────────────────────────────────────

def _check_signature(path: str, binary_format: str) -> dict[str, Any]:
    props: dict[str, Any] = {}

    if _OS == "Windows" and binary_format == "PE":
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-AuthenticodeSignature '{path}').Status"],
                capture_output=True, text=True, timeout=10
            )
            status = result.stdout.strip()
            props["signed"]           = status in ("Valid", "UnknownError", "NotSupportedFileFormat")
            props["signature_valid"]  = status == "Valid"
            props["signature_status"] = status
        except Exception:
            pass

    elif _OS == "Darwin" and binary_format in ("PE", "MACHO"):
        try:
            result = subprocess.run(
                ["codesign", "--verify", "--verbose=2", path],
                capture_output=True, text=True, timeout=10
            )
            props["signed"]          = result.returncode == 0
            props["signature_valid"] = result.returncode == 0
        except Exception:
            pass

    elif _OS == "Linux":
        # Check for GPG signature on package or ELF note
        try:
            result = subprocess.run(
                ["readelf", "-n", path],
                capture_output=True, text=True, timeout=5
            )
            props["has_elf_notes"] = result.returncode == 0 and bool(result.stdout)
        except Exception:
            pass

    return props


# ── Format detection helpers ──────────────────────────────────────────────────

def is_binary_file(path: str) -> bool:
    """Quick check if a file is a known binary format."""
    ext = Path(path).suffix.lower()
    binary_exts = {
        # Windows
        ".exe", ".dll", ".sys", ".scr", ".com", ".ocx",
        # Linux
        ".so", ".ko", ".o", ".elf",
        # macOS
        ".dylib", ".bundle", ".macho",
        # Android
        ".dex", ".apk",
        # No extension — try lief
    }
    if ext in binary_exts:
        return True
    if not ext:
        # Could be a Linux/macOS executable — check magic bytes
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
            return magic in (
                b"\x7fELF",           # ELF
                b"\xfe\xed\xfa\xce",  # Mach-O 32
                b"\xfe\xed\xfa\xcf",  # Mach-O 64
                b"\xca\xfe\xba\xbe",  # Mach-O Fat
                b"MZ\x90\x00",        # PE
            )
        except Exception:
            return False
    return False
