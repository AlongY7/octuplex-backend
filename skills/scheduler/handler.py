"""
定时任务技能处理器
功能：Cron表达式校验、定时任务增删改查
"""
import re
from datetime import datetime


class SchedulerSkill:
    """定时任务管理技能"""

    @staticmethod
    def validate_cron(expression: str) -> dict:
        """校验Cron表达式格式"""
        parts = expression.strip().split()
        if len(parts) != 5:
            return {"valid": False, "error": "Cron表达式需要5个字段: 分 时 日 月 周"}

        ranges = [
            (0, 59, "分钟"),
            (0, 23, "小时"),
            (1, 31, "日"),
            (1, 12, "月"),
            (0, 7, "周")
        ]

        for i, (part, (min_val, max_val, name)) in enumerate(zip(parts, ranges)):
            if part == "*":
                continue
            # 支持 */N 格式
            if re.match(r'^\*/\d+$', part):
                continue
            # 支持逗号分隔
            for item in part.split(","):
                # 支持范围格式
                if "-" in item:
                    try:
                        a, b = item.split("-")
                        a, b = int(a), int(b)
                        if a < min_val or b > max_val:
                            return {"valid": False, "error": f"{name}范围超出 [{min_val},{max_val}]"}
                    except ValueError:
                        return {"valid": False, "error": f"{name}值格式错误: {item}"}
                else:
                    try:
                        val = int(item)
                        if val < min_val or val > max_val:
                            return {"valid": False, "error": f"{name}值 {val} 超出范围 [{min_val},{max_val}]"}
                    except ValueError:
                        return {"valid": False, "error": f"{name}值格式错误: {item}"}

        return {"valid": True, "expression": expression}

    @staticmethod
    def explain_cron(expression: str) -> dict:
        """解释Cron表达式的含义"""
        parts = expression.strip().split()
        if len(parts) != 5:
            return {"error": "无效的Cron表达式"}

        minute, hour, day, month, weekday = parts

        explanations = []

        if minute == "*" and hour == "*" and day == "*" and month == "*" and weekday == "*":
            explanations.append("每分钟执行")
        else:
            if minute != "*":
                explanations.append(f"在分钟 {minute} 时")
            if hour != "*":
                explanations.append(f"在 {hour} 点")
            if day != "*":
                explanations.append(f"每月 {day} 号")
            if month != "*":
                explanations.append(f"在 {month} 月")
            if weekday != "*":
                week_names = ["日", "一", "二", "三", "四", "五", "六"]
                try:
                    w = int(weekday)
                    if 0 <= w <= 6:
                        explanations.append(f"每周{week_names[w]}")
                except ValueError:
                    explanations.append(f"星期 {weekday}")

        return {
            "expression": expression,
            "explanation": "，".join(explanations) if explanations else "复杂表达式",
            "parts": {
                "minute": minute, "hour": hour, "day": day,
                "month": month, "weekday": weekday
            }
        }

    @staticmethod
    def generate_examples() -> dict:
        """生成常用Cron示例"""
        return {
            "examples": [
                {"expression": "0 8 * * *", "description": "每天早上8点"},
                {"expression": "0 9 * * 1-5", "description": "工作日早上9点"},
                {"expression": "*/30 * * * *", "description": "每30分钟"},
                {"expression": "0 0 1 * *", "description": "每月1号凌晨"},
                {"expression": "0 20 * * 0", "description": "每周日晚8点"},
                {"expression": "0 */6 * * *", "description": "每6小时"},
            ]
        }


# 技能入口函数
def execute(action: str, params: dict) -> dict:
    """技能执行入口"""
    skill = SchedulerSkill()

    if action == "validate":
        return skill.validate_cron(params.get("expression", ""))
    elif action == "explain":
        return skill.explain_cron(params.get("expression", ""))
    elif action == "examples":
        return skill.generate_examples()
    else:
        return {"error": f"不支持的操作: {action}"}