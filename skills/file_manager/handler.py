"""
文件管理技能处理器
功能：批量归类、重命名、筛选、压缩、格式转换、目录遍历
"""
import os
import shutil
import zipfile
import json
from pathlib import Path
from datetime import datetime


class FileManagerSkill:
    """文件管理技能"""

    @staticmethod
    def list_files(directory: str, pattern: str = "*", recursive: bool = False) -> list:
        """列出目录中的文件"""
        path = Path(directory)
        if not path.exists():
            return {"error": f"目录不存在: {directory}"}

        files = []
        if recursive:
            for f in path.rglob(pattern):
                if f.is_file():
                    files.append({
                        "name": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                    })
        else:
            for f in path.glob(pattern):
                if f.is_file():
                    files.append({
                        "name": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
                    })

        return {"success": True, "files": files, "count": len(files)}

    @staticmethod
    def rename_file(filepath: str, new_name: str) -> dict:
        """重命名文件"""
        path = Path(filepath)
        if not path.exists():
            return {"error": f"文件不存在: {filepath}"}

        new_path = path.parent / new_name
        path.rename(new_path)
        return {"success": True, "old": str(path), "new": str(new_path)}

    @staticmethod
    def compress_files(filepaths: list, output_path: str, format: str = "zip") -> dict:
        """压缩文件"""
        output = Path(output_path)
        if format == "zip":
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fp in filepaths:
                    p = Path(fp)
                    if p.exists():
                        zf.write(p, p.name)
            return {"success": True, "output": str(output), "size": output.stat().st_size}
        return {"error": f"不支持的压缩格式: {format}"}

    @staticmethod
    def organize_files(directory: str, by: str = "extension") -> dict:
        """按规则归类整理文件"""
        path = Path(directory)
        if not path.exists():
            return {"error": f"目录不存在: {directory}"}

        moved = []
        for f in path.iterdir():
            if f.is_file():
                if by == "extension":
                    ext = f.suffix.lower().lstrip('.') or "other"
                    target_dir = path / ext
                elif by == "date":
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    target_dir = path / mtime.strftime("%Y-%m")
                else:
                    continue

                target_dir.mkdir(exist_ok=True)
                new_path = target_dir / f.name
                shutil.move(str(f), str(new_path))
                moved.append({"from": str(f), "to": str(new_path)})

        return {"success": True, "moved": moved, "count": len(moved)}


# 技能入口函数
def execute(action: str, params: dict) -> dict:
    """技能执行入口"""
    skill = FileManagerSkill()

    actions = {
        "list": skill.list_files,
        "rename": skill.rename_file,
        "compress": skill.compress_files,
        "organize": skill.organize_files,
    }

    if action not in actions:
        return {"error": f"不支持的操作: {action}"}

    return actions[action](**params)