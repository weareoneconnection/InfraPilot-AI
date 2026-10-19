#!/usr/bin/env python3
"""Build the single InfraPilot AI competition delivery with UTF-8-safe ZIP names."""

from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VERSION = "V2.1.0"
REPORT_SOURCE_DIR = ROOT / "submission" / "final"
FINAL_DIR = REPORT_SOURCE_DIR / VERSION
REPORT_DOCX = FINAL_DIR / "InfraPilot_AI_交通全场景智能应用设计报告.docx"
REPORT_PDF = FINAL_DIR / "InfraPilot_AI_交通全场景智能应用设计报告.pdf"
VIDEO = FINAL_DIR / "video" / f"InfraPilot-AI-{VERSION}-参赛演示.mp4"
SOURCE_ZIP = FINAL_DIR / f"InfraPilot-AI-{VERSION}-源代码.zip"
PACKAGE_ZIP = FINAL_DIR / f"InfraPilot-AI-{VERSION}_交通全场景智能应用赛道_最终提交包.zip"
OUTER_SUMS = FINAL_DIR / "SHA256SUMS.txt"


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_path(archive: zipfile.ZipFile, source: Path, arcname: str) -> None:
    archive.write(source, arcname)


def add_text(archive: zipfile.ZipFile, arcname: str, text: str) -> None:
    archive.writestr(arcname, text.encode("utf-8"))


def verify_utf8_names(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"CRC verification failed: {corrupt}")
        missing_flags = [
            item.filename
            for item in archive.infolist()
            if any(ord(char) > 127 for char in item.filename)
            and not item.flag_bits & 0x800
        ]
        if missing_flags:
            raise RuntimeError(f"UTF-8 filename flag missing: {missing_flags}")


def source_files() -> list[Path]:
    tracked = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z"]
    ).decode("utf-8").split("\0")
    result: list[Path] = []
    for name in tracked:
        if not name or name.startswith("submission/final/"):
            continue
        if name.endswith(".DS_Store"):
            continue
        path = ROOT / name
        if path.is_file():
            result.append(path)
    return sorted(result)


def build_source_zip(source_commit: str) -> None:
    root_name = f"InfraPilot-AI-{VERSION}"
    with zipfile.ZipFile(SOURCE_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in source_files():
            relative = path.relative_to(ROOT).as_posix()
            add_path(archive, path, f"{root_name}/{relative}")
        add_text(archive, f"{root_name}/SOURCE_COMMIT.txt", source_commit)
    verify_utf8_names(SOURCE_ZIP)


def build_submission_zip(source_commit: str) -> None:
    root_name = f"InfraPilot-AI-{VERSION}_交通全场景智能应用赛道_最终提交"
    files = [
        (REPORT_DOCX, "01_设计报告/InfraPilot_AI_交通全场景智能应用设计报告.docx"),
        (REPORT_PDF, "01_设计报告/InfraPilot_AI_交通全场景智能应用设计报告.pdf"),
        (VIDEO, f"02_演示/InfraPilot-AI-{VERSION}-参赛演示.mp4"),
        (ROOT / "submission" / "01_四分钟最终演示脚本与分镜.md", "02_演示/01_四分钟最终演示脚本与分镜.md"),
        (ROOT / "submission" / "02_证据与数据边界.md", "03_证据与边界/02_证据与数据边界.md"),
        (ROOT / "submission" / "03_评测说明.md", "03_证据与边界/03_评测说明.md"),
        (ROOT / "submission" / "04_授权脱敏样例与专家验证记录模板.md", "03_证据与边界/04_授权脱敏样例与专家验证记录模板.md"),
        (SOURCE_ZIP, f"04_源代码/{SOURCE_ZIP.name}"),
        (ROOT / "submission" / "README.md", "README.md"),
    ]
    missing = [str(path) for path, _ in files if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing final inputs: " + ", ".join(missing))

    inner_sums = "".join(
        f"{sha256(path)}  ./{arcname}\n" for path, arcname in files
    )
    with zipfile.ZipFile(PACKAGE_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, arcname in files:
            add_path(archive, path, f"{root_name}/{arcname}")
        add_text(archive, f"{root_name}/SOURCE_COMMIT.txt", source_commit)
        add_text(archive, f"{root_name}/SHA256SUMS.txt", inner_sums)
    verify_utf8_names(PACKAGE_ZIP)


def main() -> None:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO.parent.mkdir(parents=True, exist_ok=True)
    for name in (REPORT_DOCX.name, REPORT_PDF.name):
        source = REPORT_SOURCE_DIR / name
        target = FINAL_DIR / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing report input: {source}")
        target.write_bytes(source.read_bytes())
    commit = git("rev-parse", "HEAD")
    source_commit = (
        "项目：InfraPilot-AI\n"
        f"版本：{VERSION}\n"
        f"Git 提交：{commit}\n"
        "公开仓库：https://github.com/weareoneconnection/InfraPilot-AI\n"
        "在线演示：https://infrapilot-ai-production-cd4c.up.railway.app\n"
        "生成日期：2026-10-19\n"
    )
    build_source_zip(source_commit)
    build_submission_zip(source_commit)

    deliverables = [SOURCE_ZIP, PACKAGE_ZIP, REPORT_DOCX, REPORT_PDF, VIDEO]
    OUTER_SUMS.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in deliverables),
        encoding="utf-8",
    )
    print(f"Built {PACKAGE_ZIP}")
    print(f"Source commit {commit}")


if __name__ == "__main__":
    main()
