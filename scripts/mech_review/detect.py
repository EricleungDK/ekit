"""Setup detection (#23): the projects no built-in stack and no repo adapter file covers, for ci-doctor's setup mode.

A project is a folder holding a manifest of a kind in KINDS that no known adapter lists (`known`: the manifest names
the built-ins and the repo's adapter files list), outside fixture, vendored and build folders (resolve.SKIP_DIRS); the
shallowest such folders count, as in resolve.candidates. For each: its language (the kind's language with the most
source files under the folder), build tool, test framework (the first of the kind's needles found in a manifest of
that build under the folder, any depth: a solution's test project too) and target OS (OS_RULES, else linux), with the
reason. Git only: names and blobs at one commit, nothing run.
"""
import fnmatch
import re
from collections import namedtuple

from . import gitio
from .resolve import SKIP_DIRS

# pattern: a manifest's file name (fnmatch, case-sensitive; `<dir>/<file>`: a dir holding that file is the manifest);
# languages: (language, source extension), the first wins a tie; frameworks: (needle, name), the first needle a manifest
# of the build holds (lowercase, matched against the lowercased text) names it
Kind = namedtuple("Kind", "pattern build languages frameworks")
JVM_LANGUAGES = (("java", ".java"), ("kotlin", ".kt"))
JVM_TESTS = (("junit-jupiter", "junit5"), ("testng", "testng"), ("junit", "junit4"))
DOTNET_LANGUAGES = (("csharp", ".cs"), ("fsharp", ".fs"))
DOTNET_TESTS = (("xunit", "xunit"), ("nunit", "nunit"), ("mstest", "mstest"))
KINDS = (
    Kind("pom.xml", "maven", JVM_LANGUAGES, JVM_TESTS),
    Kind("build.gradle", "gradle", JVM_LANGUAGES, JVM_TESTS),
    Kind("build.gradle.kts", "gradle", JVM_LANGUAGES, JVM_TESTS),
    Kind("*.sln", "dotnet", DOTNET_LANGUAGES, DOTNET_TESTS),
    Kind("*.csproj", "dotnet", DOTNET_LANGUAGES, DOTNET_TESTS),
    Kind("Package.swift", "swiftpm", (("swift", ".swift"),), ()),
    Kind("go.mod", "go", (("go", ".go"),), (("", "testing"),)),  # go's own: every module tests with `go test`
    Kind("*.xcodeproj/project.pbxproj", "xcode", (("swift", ".swift"), ("objective-c", ".m")), ()),
)
# the target OS a project's tests need (#23): the first rule whose pattern a manifest of its build holds, else linux.
# why names that file: {file}
OsRule = namedtuple("OsRule", "build pattern os why")
OS_RULES = (
    OsRule("dotnet", re.compile(r"<UseWPF>\s*true\s*</UseWPF>", re.I), "windows",
           "`{file}` sets UseWPF: a WPF app builds and runs on Windows only"),
    OsRule("xcode", re.compile(""), "macos", "`{file}`: an Xcode project (an iOS or macOS app) builds on macOS only"),
    OsRule("swiftpm", re.compile(r"\.iOS\s*\("), "macos",
           "`{file}` names an iOS platform: an iOS app's tests run on macOS only"),
)
EVIDENCE_SKIP = SKIP_DIRS - {"tests", "test"}  # a test project's manifest names the test framework
LINUX = "no Windows- or Apple-only project file"


def _manifest(path):
    """(kind, folder, manifest name) of a manifest path, or None."""
    parts = path.split("/")
    for k in KINDS:
        n = k.pattern.count("/") + 1
        if len(parts) >= n and fnmatch.fnmatchcase("/".join(parts[-n:]), k.pattern):
            return k, "/".join(parts[:-n]) or ".", parts[-n]
    return None


def _under(path, folder):
    return folder == "." or path.startswith(folder + "/")


def projects(repo, head, paths, known, project_dir=None):
    """[{project_dir, manifests, language, build, test_framework, target_os, target_os_why}], sorted by folder: the
    shallowest projects no known adapter covers, or with project_dir only the ones in that folder (any depth)."""
    found = {}
    for path in paths:
        m = _manifest(path)
        if m is None or m[2] in known or SKIP_DIRS & set(m[1].split("/")):
            continue
        found.setdefault((m[1], m[0].build), []).append(m[2])
    if project_dir:
        found = {k: v for k, v in found.items() if k[0] == project_dir}
    elif found:
        top = min(depth(folder) for folder, _ in found)
        found = {k: v for k, v in found.items() if depth(k[0]) == top}
    return [_describe(repo, head, paths, folder, build, manifests)
            for (folder, build), manifests in sorted(found.items())]


def depth(folder):
    """a folder's depth: `.` is 0, `a` is 1, `a/b` is 2."""
    return folder.count("/") + (folder != ".")


def _describe(repo, head, paths, folder, build, manifests):
    kinds = [k for k in KINDS if k.build == build]
    mine = [p for p in paths if _under(p, folder)]
    counts = [(sum(p.endswith(ext) for p in mine), lang) for lang, ext in kinds[0].languages]
    language = max(counts, key=lambda c: c[0])[1]
    evidence = [p for p in mine
                if (_manifest(p) or (None,))[0] in kinds and not EVIDENCE_SKIP & set(p.split("/")[:-1])]
    texts = {p: gitio.blob(repo, head, p) for p in evidence}
    framework = next((name for needle, name in kinds[0].frameworks
                      if any(needle in t.lower() for t in texts.values())), None)
    target_os, why = next(((r.os, r.why.format(file=f)) for r in OS_RULES if r.build == build
                           for f, t in sorted(texts.items()) if r.pattern.search(t)), ("linux", LINUX))
    return {"project_dir": folder, "manifests": sorted(manifests), "language": language,
            "build": build, "test_framework": framework, "target_os": target_os, "target_os_why": why}
