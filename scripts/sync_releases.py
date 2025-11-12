#!/usr/bin/env python3
"""同步指定仓库的最新发布资产。"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_ROOT = "https://api.github.com"
TARGET_ROOT = Path("artifacts")
REPOSITORIES: List[Tuple[str, str]] = [
    ("zhaochengcube", "augment-token-mng"),
    ("zhaochengcube", "augment-code-auto"),
    ("Zheng-up", "augment-code-z"),
    ("Zheng-up", "zAugment"),
    ("wuqi-y", "auto-cursor-releases"),
]


def fetch_json(url: str, token: str) -> Dict[str, object]:
    """调用 GitHub API 并返回 JSON 数据。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "release-sync-bot",
    }
    request = Request(url, headers=headers)
    with urlopen(request) as response:  # type: ignore[arg-type]
        return json.loads(response.read().decode("utf-8"))


def download_asset(asset: Dict[str, object], token: str, destination: Path) -> None:
    """下载发布资产到指定路径。"""
    asset_url = str(asset.get("url"))
    if not asset_url:
        raise RuntimeError("发布资产缺少下载地址")
    headers = {
        "Accept": "application/octet-stream",
        "Authorization": f"token {token}",
        "User-Agent": "release-sync-bot",
    }
    request = Request(asset_url, headers=headers)
    with urlopen(request) as response:  # type: ignore[arg-type]
        with destination.open("wb") as file_handle:
            shutil.copyfileobj(response, file_handle)


def sync_repository(owner: str, name: str, token: str) -> bool:
    """同步单个仓库的最新发布，返回是否产生变更。"""
    metadata_url = f"{API_ROOT}/repos/{owner}/{name}/releases/latest"
    try:
        release = fetch_json(metadata_url, token)
    except HTTPError as error:
        raise RuntimeError(f"请求 {owner}/{name} 发布信息失败，状态码: {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"请求 {owner}/{name} 发布信息失败: {error.reason}") from error

    tag_name = str(release.get("tag_name") or "").strip()
    assets = release.get("assets")

    if not tag_name:
        raise RuntimeError(f"{owner}/{name} 的最新发布缺少 tag_name 字段")
    if not isinstance(assets, list):
        assets = []

    project_dir = TARGET_ROOT / name
    version_file = project_dir / "version.txt"

    current_version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    if current_version == tag_name:
        print(f"{owner}/{name} 已是最新版本 {tag_name}")
        return False

    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    if assets:
        for asset in assets:
            asset_name = str(asset.get("name") or "").strip()
            if not asset_name:
                continue
            destination = project_dir / asset_name
            print(f"下载 {owner}/{name} 的资产 {asset_name}")
            download_asset(asset, token, destination)
    else:
        print(f"{owner}/{name} 的最新发布没有资产，跳过下载")

    version_file.write_text(tag_name, encoding="utf-8")
    metadata_file = project_dir / "metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "repository": f"{owner}/{name}",
                "tag": tag_name,
                "release_id": release.get("id"),
                "html_url": release.get("html_url"),
                "published_at": release.get("published_at"),
                "fetched_at": os.environ.get("GITHUB_RUN_DATETIME"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return True


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("缺少 GITHUB_TOKEN 环境变量")

    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    changed: List[str] = []

    for owner, name in REPOSITORIES:
        changed_flag = sync_repository(owner, name, token)
        if changed_flag:
            changed.append(f"{owner}/{name}")

    if changed:
        summary = "\n".join(changed)
        print("以下仓库已更新:\n" + summary)
    else:
        print("所有仓库均为最新版本")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(f"同步过程中发生错误: {exc}", file=sys.stderr)
        sys.exit(1)
