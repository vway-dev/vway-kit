"""저장소 상태와 프레임워크 탐지 — greenfield 인가 brownfield 인가.

vendored 디렉터리는 소스로 세지 않음. 같은 프레임워크를 두 매니페스트가 말하면
한 번만 셈 — 중복은 하네스가 같은 규칙을 두 번 쓰게 만듦.
"""

import json

import scripts.harness_scaffold as hs
from tests.harness._helpers import (
    _write_component,
)


def test_detect_state_greenfield(tmp_path):
    (tmp_path / "README.md").write_text("# hi", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert hs.detect_state(tmp_path) == "greenfield"


def test_detect_state_brownfield_when_source_present(tmp_path):
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    assert hs.detect_state(tmp_path) == "brownfield"


def test_detect_state_ignores_vendored_dirs(tmp_path):
    nm = tmp_path / "node_modules" / "x"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("//x", encoding="utf-8")
    (tmp_path / "README.md").write_text("# hi", encoding="utf-8")
    assert hs.detect_state(tmp_path) == "greenfield"


def test_detect_frameworks_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15.0.1", "react": "19.0.0"}}),
        encoding="utf-8",
    )
    found = {f["name"]: f["version"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("next.js") == "15.0.1"


def test_detect_frameworks_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi==0.118.0", "uvicorn"]\n', encoding="utf-8"
    )
    found = {f["name"]: f["version"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("fastapi") == "0.118.0"


def test_detect_frameworks_pyproject_poetry(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry.dependencies]\nfastapi = "^0.118.0"\ndjango = "^5.0"\n',
        encoding="utf-8",
    )
    found = {f["name"]: f["version"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("fastapi") == "0.118.0"
    assert found.get("django") == "5.0"


def test_detect_frameworks_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\nflask==3.0.0\nrequests>=2.0\n", encoding="utf-8"
    )
    found = {f["name"]: f["version"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("flask") == "3.0.0"


def test_detect_frameworks_requirements_dedup_with_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["flask==3.0.0"]\n', encoding="utf-8"
    )
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\n", encoding="utf-8")
    names = [f["name"] for f in hs.detect_frameworks(tmp_path)]
    assert names.count("flask") == 1  # 매니페스트 둘에 걸쳐도 name 기준 dedup


def test_detect_frameworks_dedup_same_label(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {"dependencies": {"nestjs": "10.0.0", "@nestjs/core": "10.0.0", "next": "15.0.1"}}
        ),
        encoding="utf-8",
    )
    names = [f["name"] for f in hs.detect_frameworks(tmp_path)]
    assert names.count("nestjs") == 1
    assert len(names) == len(set(names))


def test_detect_frameworks_cargo(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n', encoding="utf-8")
    names = [f["name"] for f in hs.detect_frameworks(tmp_path)]
    assert names == ["rust"]


def test_detect_frameworks_maven(tmp_path):
    (tmp_path / "pom.xml").write_text("<project></project>", encoding="utf-8")
    found = {f["name"]: f["manifest"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("java") == "pom.xml"


def test_detect_frameworks_gradle_kotlin(tmp_path):
    (tmp_path / "build.gradle.kts").write_text("plugins {}\n", encoding="utf-8")
    found = {f["name"]: f["manifest"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("kotlin") == "build.gradle.kts"


def test_detect_frameworks_gradle_java(tmp_path):
    (tmp_path / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
    found = {f["name"]: f["manifest"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("java") == "build.gradle"


def test_detect_frameworks_ruby(tmp_path):
    (tmp_path / "Gemfile").write_text('source "https://rubygems.org"\n', encoding="utf-8")
    names = [f["name"] for f in hs.detect_frameworks(tmp_path)]
    assert names == ["ruby"]


def test_detect_frameworks_php(tmp_path):
    (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
    names = [f["name"] for f in hs.detect_frameworks(tmp_path)]
    assert names == ["php"]


def test_detect_frameworks_swift(tmp_path):
    (tmp_path / "Package.swift").write_text("// swift-tools-version:5.9\n", encoding="utf-8")
    names = [f["name"] for f in hs.detect_frameworks(tmp_path)]
    assert names == ["swift"]


def test_detect_frameworks_dotnet_csproj(tmp_path):
    (tmp_path / "App.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"></Project>', encoding="utf-8"
    )
    found = {f["name"]: f["manifest"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("dotnet") == "App.csproj"


def test_detect_frameworks_dotnet_sln_preferred_over_csproj(tmp_path):
    (tmp_path / "App.csproj").write_text("<Project></Project>", encoding="utf-8")
    (tmp_path / "App.sln").write_text("Microsoft Visual Studio Solution File\n", encoding="utf-8")
    found = {f["name"]: f["manifest"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("dotnet") == "App.sln"


def test_detect_frameworks_cpp_cmake(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8"
    )
    found = {f["name"]: f["manifest"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("cpp") == "CMakeLists.txt"


def test_detect_frameworks_cpp_vcpkg(tmp_path):
    (tmp_path / "vcpkg.json").write_text('{"name": "x", "version": "1.0.0"}', encoding="utf-8")
    found = {f["name"]: f["manifest"] for f in hs.detect_frameworks(tmp_path)}
    assert found.get("cpp") == "vcpkg.json"


def test_detect_state_brownfield_for_cpp_and_csharp(tmp_path):
    (tmp_path / "main.cpp").write_text("int main(){}\n", encoding="utf-8")
    assert hs.detect_state(tmp_path) == "brownfield"
    (tmp_path / "main.cpp").unlink()
    (tmp_path / "App.cs").write_text("class App {}\n", encoding="utf-8")
    assert hs.detect_state(tmp_path) == "brownfield"


def test_scan_components_reads_name_and_description(tmp_path):
    cdir = tmp_path / ".claude"
    _write_component(cdir / "commands" / "deploy.md", "deploy", "Deploy the app")
    _write_component(cdir / "agents" / "reviewer.md", "reviewer", "Reviews code")
    _write_component(cdir / "skills" / "lint" / "SKILL.md", "lint", "Lint sources")
    result = hs.scan_components(cdir)
    expected = {
        "name": "deploy",
        "description": "Deploy the app",
        "path": str(cdir / "commands" / "deploy.md"),
    }
    assert expected in result["commands"]
    assert result["agents"][0]["name"] == "reviewer"
    assert result["skills"][0]["description"] == "Lint sources"


def test_scan_components_missing_dirs_returns_empty(tmp_path):
    result = hs.scan_components(tmp_path / ".claude")
    assert result == {"skills": [], "commands": [], "agents": []}
