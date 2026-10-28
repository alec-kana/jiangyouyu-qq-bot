"""酱油鱼自用的早柚核心插件：在机器人登记过账号（登录过）的人，每天自动在社区领签到奖励。

- 鸣潮（RoverSign）、终末地（EndUID）自带「全部开启签到」SigninMaster：启动时打开，有登录的账号都签；
- 米哈游系（原神 / 星铁 / 绝区零 / 崩坏3）的插件只签订阅了「[游戏] 自动签到」的 UID：
  每小时给有 Cookie 的 UID 补上订阅（按私聊记、不往群里发），新登录的人当晚就能签上。
- 各插件的定时签到打开、私聊签到报告关掉：SnowLuma 主动私聊没加好友的人发不出去，静默领取就好，
  想看结果的人自己发「gs签到」等。

一键部署把本目录拷进核心的 plugins；本目录按 GPL-3.0 发布（运行在 GPL-3.0 的早柚核心里），见 LICENSE。
"""

from __future__ import annotations

import sys
from typing import Any, Dict

from gsuid_core.aps import scheduler
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.server import on_core_start_before
from gsuid_core.subscribe import gs_subscribe
from gsuid_core.utils.database.models import GsUser
from gsuid_core.utils.plugins_config.gs_config import all_config_list

# 插件配置名 -> 要设的值；插件没装就跳过
CONFIGS: Dict[str, Dict[str, Any]] = {
    "GenshinUID": {"SchedSignin": True, "PrivateSignReport": False},
    "StarRailUID": {"SchedSignin": True, "PrivateSignReport": False},
    "ZZZeroUID": {"SchedSignin": True, "PrivateSignReport": False},
    "BBBUID": {"SchedSignin": True, "PrivateSignReport": False},
    "RoverSign": {"SigninMaster": True, "SchedSignin": True, "PrivateSignReport": False},
    "EndUID": {"SigninMaster": True, "SchedSignin": True, "PrivateSignReport": False},
}
# 米哈游系：GsUser 上的 UID 字段 -> 插件签到用的订阅名
MIHOYO_SIGN = {
    "uid": "[原神] 自动签到",
    "sr_uid": "[星铁] 自动签到",
    "zzz_uid": "[绝区零] 自动签到",
    "bbb_uid": "[崩坏3] 自动签到",
}


def apply_configs() -> list[str]:
    changed = []
    for name, values in CONFIGS.items():
        config = all_config_list.get(name)
        if config is None:
            continue
        for key, value in values.items():
            try:
                if config.get_config(key).data != value and config.set_config(key, value):
                    changed.append(f"{name}.{key}={value}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[酱油鱼·自动签到] 设置 {name}.{key} 失败：{exc}")
    return changed


def patch_loaded_report_flags() -> None:
    """米哈游系插件在导入时就把 PrivateSignReport 读进模块变量，改配置要重启才生效；
    刚装好的第一晚（崩坏3 默认开）会私聊每个人，所以把已加载模块里的值也改掉。"""
    for module in list(sys.modules.values()):
        # 核心按 plugins.BBBUID.BBBUID.bbb_sign 这样的名字导入插件
        parts = (getattr(module, "__name__", "") or "").split(".")
        package = next((p for p in parts if p in CONFIGS), "")
        if CONFIGS.get(package, {}).get("PrivateSignReport") is not False:
            continue
        for attr in ("IS_REPORT", "IS_REPORT_PRIVATE"):
            if getattr(module, attr, False) is True:
                setattr(module, attr, False)
                logger.info(f"[酱油鱼·自动签到] 已关掉 {module.__name__}.{attr}")


def ensure_end_job() -> None:
    """终末地导入时 SchedSignin 还没开就不注册定时签到，刚装好要补注册一次。"""
    if scheduler.get_job("end_sign_0") is not None:
        return
    for name, module in list(sys.modules.items()):
        if name.endswith("EndUID.end_sign") and hasattr(module, "setup_scheduler"):
            module.setup_scheduler()
            return


async def ensure_mihoyo_subscriptions() -> int:
    """给每个有 Cookie 的米哈游系 UID 补上自动签到订阅，返回新加的条数。"""
    added = 0
    for user in await GsUser.get_all_user():
        for field, task in MIHOYO_SIGN.items():
            uid = getattr(user, field, None)
            if not uid or await gs_subscribe.get_subscribe(task, uid=uid):
                continue
            # 按私聊记：签到不看订阅里的会话，私聊报告又关了，所以不会往哪里发消息
            event = Event(bot_id=user.bot_id, user_id=user.user_id, user_type="direct")
            await gs_subscribe.add_subscribe("single", task, event, uid=uid)
            added += 1
    return added


async def sync() -> None:
    try:
        changed = apply_configs()
        patch_loaded_report_flags()
        ensure_end_job()
        added = await ensure_mihoyo_subscriptions()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[酱油鱼·自动签到] 同步失败：{exc}")
        return
    if changed or added:
        logger.info(f"[酱油鱼·自动签到] 配置 {'、'.join(changed) or '无变化'}；新开自动签到 {added} 个 UID")


# 放在「启动前」：普通启动钩子按优先级排队，前面的资源下载慢或报错会把这里拖晚甚至跳过
@on_core_start_before(priority=90)
async def _on_start() -> None:
    await sync()


@scheduler.scheduled_job("cron", minute=7, id="jiangyouyu_auto_sign_sync")
async def _hourly() -> None:
    await sync()
