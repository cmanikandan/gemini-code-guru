"""
Gemini Managed Agents (Public Preview) platform compatibility guardrails & pre-flight checks.

Prevents teams from discovering sandbox/platform limitations the hard way (after burning
millions of tokens) by checking repository metadata, source sizes, network rules, file trees,
and GitHub issue descriptions BEFORE provisioning a remote sandbox.

Official Documentation (Public Preview — subject to change):
  - Managed Agents Overview: https://ai.google.dev/gemini-api/docs/agents
  - Antigravity Agent:       https://ai.google.dev/gemini-api/docs/antigravity-agent
  - Environments & Limits:   https://ai.google.dev/gemini-api/docs/agent-environment#limitations
  - Hooks:                   https://ai.google.dev/gemini-api/docs/agent-hooks
"""
from __future__ import annotations

import pathlib
import re

DOCS_LIMITS_URL = "https://ai.google.dev/gemini-api/docs/agent-environment#limitations"
DOCS_AGENTS_URL = "https://ai.google.dev/gemini-api/docs/agents"

PLATFORM_LIMITS = {
    "release_stage": "Public Preview (subject to change; see https://ai.google.dev/gemini-api/docs/agents)",
    "base_agent": "antigravity-preview-05-2026",
    "default_model": "gemini-3.8-flash",
    "sandbox_os": "Ubuntu Linux (OS-isolated VM)",
    "cpu_cores": 4,
    "memory_gb": 16,
    "gpu_or_tpu": False,
    "preinstalled_runtimes": ["Python 3.12", "Node.js 22", "Ubuntu UNIX & Cloud CLI tools"],
    "max_git_repo_mb": 500,
    "max_gcs_source_mb": 2048,
    "max_inline_file_bytes": 1_000_000,   # 1 MB per inline file
    "max_inline_total_bytes": 2_000_000,  # 2 MB total across all inline files
    "environment_ttl_days": 7,
    "max_managed_agents_per_project": 1000,
    "reserved_agent_id_prefixes": [
        "antigravity-", "veo-", "omni-", "lyria-", "imagen-", "gemma-", "gemini-", "google-",
        "youtube-", "android-", "chrome-", "pixel-", "waze-", "fitbit-", "nest-", "kaggle-",
    ],
    "native_file_modalities": ["text", "image"],
    "docs_url": DOCS_LIMITS_URL,
}

# Deterministic issue-level rules for workloads that cannot be built or verified in the Ubuntu sandbox.
UNSUPPORTED_ISSUE_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "native_windows",
        re.compile(
            r"\b(winforms|windows\s+forms|wpf\b|win32\b|uwp\b|winui\b|activex\b|com\s+interop|"
            r"regedit|hklm\\|hkcu\\|windows\s+registry|iis\s+app|\.net\s*framework\s*[1-4](\.\d+)?|"
            r"net4[0-8]\b|vcxproj\b|wixproj\b|msi\s+installer|windows\s+service|"
            r"native\s+windows\s+(app|application|desktop|migration|client))\b",
            re.IGNORECASE,
        ),
        "Gemini Managed Agents runs inside an Ubuntu Linux sandbox (4 vCPU, 16 GB RAM) and cannot "
        "compile or test native Windows workloads (Win32, WPF, WinForms, UWP, COM, Windows Registry, "
        "IIS, or legacy .NET Framework 3.5-4.8). Cross-platform .NET 8+ targeting Linux is supported, "
        "but native Windows desktop/OS migrations require a Windows runner.",
    ),
    (
        "native_apple",
        re.compile(
            r"\b(xcode\b|xcodebuild\b|xcrun\b|cocoapods\b|uikit\b|appkit\b|swiftui\s+(ios|macos|watchos|visionos)|"
            r"ios\s+simulator|\.xcodeproj\b|\.xcworkspace\b|native\s+(ios|macos|watchos|tvos|visionos)\s+app)\b",
            re.IGNORECASE,
        ),
        "Gemini Managed Agents runs on Ubuntu Linux and cannot execute Xcode, Darwin SDKs, "
        "CocoaPods, SwiftUI/UIKit/AppKit builds, or iOS/macOS simulators.",
    ),
    (
        "gpu_hardware",
        re.compile(
            r"\b(cuda\s+kernel|nvcc\b|cudnn\b|tensorrt\b|nccl\b|rocm\b|tpu\s+pod|"
            r"gpu\s+cluster|directx\s*1[12]?|hlsl\s+shader|metal\s+shader|vulkan\s+swapchain|"
            r"requires\s+(nvidia|a100|h100|gpu|tpu)\s+hardware)\b",
            re.IGNORECASE,
        ),
        "Gemini Managed Agent sandboxes have a fixed 4 vCPU / 16 GB RAM allocation with no GPU or TPU "
        "attached. Workloads requiring CUDA kernel execution, GPU device training, or hardware graphics "
        "APIs cannot be verified in the sandbox.",
    ),
    (
        "kernel_privileged",
        re.compile(
            r"\b(insmod\b|modprobe\b|rmmod\b|linux\s+kernel\s+module|dkms\b|kbuild\b|"
            r"docker\s+run\s+[^\n]*--privileged|nested\s+virtualization|kvm\s+hypervisor)\b",
            re.IGNORECASE,
        ),
        "The OS-isolated Ubuntu sandbox does not permit loading custom Linux kernel modules "
        "(insmod/modprobe), privileged containers (--privileged), or nested hypervisors.",
    ),
    (
        "airgapped_network",
        re.compile(
            r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
            r"[a-z0-9.-]+\.(corp|internal|local|lan)\b|air[- ]?gapped\s+network)\b",
            re.IGNORECASE,
        ),
        "Gemini Managed Agent sandboxes run in Google's managed environment and connect via the public "
        "HTTPS egress proxy allowlist. They cannot reach private RFC1918 IPs or internal corporate "
        "(.corp / .internal / .local) networks without a public HTTPS endpoint.",
    ),
    (
        "hardware_iot",
        re.compile(
            r"\b(jtag\b|st-link\b|openocd\b|usb\s+passthrough|serial\s+port\s+/dev/tty\w+|"
            r"hardware[- ]in[- ]the[- ]loop)\b",
            re.IGNORECASE,
        ),
        "The cloud sandbox has no physical USB, serial (/dev/tty*), JTAG, or BLE hardware passthrough.",
    ),
]

# File-path patterns used when scanning a repository tree during pre-flight checks.
REPO_FILE_RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "native_windows_project",
        re.compile(r"\.(vcxproj|wixproj|vdproj)$", re.IGNORECASE),
        "blocker",
        "Contains native Windows C++/WiX/Installer project files (.vcxproj/.wixproj) that require Windows MSBuild.",
    ),
    (
        "native_apple_project",
        re.compile(r"(\.xcodeproj|\.xcworkspace)(/|$)|(^|/)Podfile$", re.IGNORECASE),
        "blocker",
        "Contains macOS/iOS Xcode or CocoaPods project files (.xcodeproj/.xcworkspace/Podfile) requiring macOS/Xcode.",
    ),
    (
        "cuda_sources",
        re.compile(r"\.(cu|cuh)$", re.IGNORECASE),
        "warning",
        "Contains CUDA source files (.cu/.cuh); note that the sandbox has 4 CPU cores / 16 GB RAM and no GPU.",
    ),
    (
        "kernel_module_build",
        re.compile(r"(^|/)Kbuild$", re.IGNORECASE),
        "blocker",
        "Contains Linux kernel module Kbuild file; loading kernel modules (insmod/modprobe) is blocked in the sandbox.",
    ),
    (
        "binary_assets",
        re.compile(r"\.(dll|exe|msi|dmg|ipa|apk|so|dylib|uasset|umap)$", re.IGNORECASE),
        "warning",
        "Contains compiled binary artifacts; note that native file tools only read text and image files.",
    ),
]


def check_issue_compatibility(title: str, body: str = "") -> dict:
    """
    Evaluate a GitHub issue's title and body against Gemini Managed Agents platform limits.
    Returns {"compatible": bool, "category": str | None, "reason": str | None, "docs_url": str}.
    """
    text = f"{title or ''}\n{body or ''}"
    for category, pattern, reason in UNSUPPORTED_ISSUE_RULES:
        m = pattern.search(text)
        if m:
            matched = m.group(0)
            return {
                "compatible": False,
                "category": category,
                "matched": matched,
                "reason": f"{reason} (Matched: `{matched}`)",
                "docs_url": DOCS_LIMITS_URL,
            }
    return {"compatible": True, "category": None, "matched": None, "reason": None, "docs_url": DOCS_LIMITS_URL}


def check_dotnet_csproj_content(content: str, path: str = ".csproj") -> str | None:
    """Detect legacy Windows-only .NET Framework or WPF/WinForms targets inside a .csproj file."""
    if re.search(r"<TargetFrameworkVersion>\s*v[1-4]\.", content, re.IGNORECASE) or re.search(
        r"<TargetFrameworks?>\s*net4[0-8]", content, re.IGNORECASE
    ):
        return f"{path} targets legacy Windows-only .NET Framework 1.x-4.x (Ubuntu sandbox supports .NET 8+ Linux only)."
    if re.search(r"<Use(WPF|WindowsForms)>\s*true\s*</Use(WPF|WindowsForms)>", content, re.IGNORECASE):
        return f"{path} enables Windows desktop UI (<UseWPF> or <UseWindowsForms>), which cannot run on Ubuntu Linux."
    return None


def check_repo_compatibility(
    *,
    repo_url: str | None = None,
    repo_size_kb: int | None = None,
    file_paths: list[str] | None = None,
    local_dir: str | pathlib.Path | None = None,
    inline_sources: list[dict] | None = None,
    allowlist: list[dict] | None = None,
) -> dict:
    """
    Comprehensive pre-flight check for a target repository and environment config.
    Returns {"compatible": bool, "blockers": list[str], "warnings": list[str], "limits": dict}.
    """
    blockers: list[str] = []
    warnings: list[str] = []

    # 1. Repository URL protocol & target mount validation
    if repo_url:
        if repo_url.startswith("git@") or repo_url.startswith("ssh://"):
            blockers.append(
                f"Repository URL `{repo_url}` uses SSH. Gemini Managed Agents egress proxy header "
                "transforms require HTTPS (`https://github.com/<owner>/<repo>`)."
            )
        elif not repo_url.startswith("https://"):
            blockers.append(f"Repository URL `{repo_url}` must start with `https://`.")

    # 2. GitHub Repository Size Limit (500 MB = 512,000 KB)
    if repo_size_kb is not None:
        size_mb = round(repo_size_kb / 1024, 1)
        if size_mb > PLATFORM_LIMITS["max_git_repo_mb"]:
            blockers.append(
                f"Repository size is {size_mb} MB, which exceeds the Gemini Managed Agents "
                f"500 MB Git RepositorySource limit ({DOCS_LIMITS_URL})."
            )
        elif size_mb > 350:
            warnings.append(
                f"Repository size is {size_mb} MB (approaching the 500 MB limit); cold start may exceed 5s."
            )

    # 3. Inline Sources Size Limit (1 MB per file, 2 MB total) and root mount check
    if inline_sources:
        total_bytes = 0
        for src in inline_sources:
            target = src.get("target", "")
            if target.strip() == "/":
                blockers.append("Custom sources cannot mount at root (`/`); specify a subdirectory.")
            if src.get("type") == "inline":
                size_b = len((src.get("content") or "").encode("utf-8"))
                total_bytes += size_b
                if size_b > PLATFORM_LIMITS["max_inline_file_bytes"]:
                    blockers.append(
                        f"Inline source `{target}` is {size_b:,} bytes, exceeding the 1 MB per-file limit."
                    )
        if total_bytes > PLATFORM_LIMITS["max_inline_total_bytes"]:
            blockers.append(
                f"Total inline sources size is {total_bytes:,} bytes, exceeding the 2 MB total limit."
            )

    # 4. Network Allowlist validation (no private RFC1918 IPs or URLs with paths)
    if allowlist:
        for entry in allowlist:
            dom = entry.get("domain", "")
            if "/" in dom or ":" in dom:
                blockers.append(
                    f"Allowlist domain `{dom}` must be a bare hostname (no protocol, port, or path)."
                )
            if re.match(
                r"^(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|localhost|127\.)",
                dom,
            ) or dom.endswith((".internal", ".corp", ".local")):
                blockers.append(
                    f"Allowlist domain `{dom}` is a private/internal address. The cloud sandbox cannot "
                    "reach RFC1918 or internal corporate hosts."
                )

    # 5. File tree inspection (either passed explicitly or scanned from local_dir)
    paths_to_check = list(file_paths or [])
    root_path = pathlib.Path(local_dir) if local_dir else None
    if root_path and root_path.exists():
        for p in root_path.rglob("*"):
            if ".git" in p.parts or "node_modules" in p.parts or ".venv" in p.parts:
                continue
            if p.is_file():
                rel = str(p.relative_to(root_path))
                paths_to_check.append(rel)
                if p.suffix.lower() == ".csproj":
                    try:
                        err = check_dotnet_csproj_content(p.read_text(errors="ignore"), rel)
                        if err:
                            blockers.append(err)
                    except OSError:
                        pass

    seen_rules: set[str] = set()
    for rel_path in paths_to_check:
        for rule_id, pattern, severity, message in REPO_FILE_RULES:
            if rule_id not in seen_rules and pattern.search(rel_path):
                seen_rules.add(rule_id)
                msg = f"{message} (Found: `{rel_path}`)"
                if severity == "blocker":
                    blockers.append(msg)
                else:
                    warnings.append(msg)

    return {
        "compatible": len(blockers) == 0,
        "blockers": blockers,
        "warnings": warnings,
        "limits": PLATFORM_LIMITS,
    }
