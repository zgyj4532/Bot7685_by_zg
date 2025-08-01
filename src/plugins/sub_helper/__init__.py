from collections.abc import AsyncGenerator

import anyio
import paramiko
from nonebot import logger, require
from nonebot.adapters import Bot, Event
from nonebot.exception import MatcherException
from nonebot.params import Depends
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import (
    Alconna,
    CommandMeta,
    MsgTarget,
    Subcommand,
    UniMessage,
    on_alconna,
)

require("src.plugins.trusted")
from src.plugins.trusted import TrustedUser

from .ali.client import AliClient
from .config import Config, plugin_config
from .ssh import SSHClient
from .sub import generate
from .tencent.client import TencentClient

__plugin_meta__ = PluginMetadata(
    name="sub_helper",
    description="A helper for sub",
    usage="sub -h",
    type="application",
    config=Config,
)


check_sub = on_alconna(
    Alconna(
        "sub",
        Subcommand("check", help_text="check status"),
        Subcommand("get", help_text="get sub"),
        Subcommand("create", help_text="[superuser] create instance"),
        Subcommand("setup", help_text="[superuser] setup instance"),
        meta=CommandMeta(
            description="sub helper",
            usage="sub -h",
        ),
    ),
    use_cmd_start=True,
    permission=TrustedUser(),
)


@check_sub.assign("check")
async def assign_check() -> None:
    status = (
        "online"
        if await AliClient().find_instance_by_name(plugin_config.ali.instance_name)
        else "offline"
    )
    await UniMessage.text(f"Instance {status}").finish()


@check_sub.assign("get")
async def assign_get(target: MsgTarget) -> None:
    if not target.private:
        await check_sub.finish()

    await UniMessage.text(generate()).finish()


async def do_setup(host: str) -> None:
    retry = 0
    while retry < 6:
        await anyio.sleep(10)
        try:
            await SSHClient.setup_server(host)
            break
        except paramiko.SSHException as err:
            retry += 1
            logger.warning(f"Error setting up server: {err}")
    else:
        await UniMessage.text("Error setting up server").finish()


async def do_create() -> None:
    ali_client = AliClient()

    if await ali_client.find_instance_by_name(plugin_config.ali.instance_name):
        await UniMessage.text("Instance already exists").finish()

    inst_id = await ali_client.create_instance_from_template()
    await UniMessage.text(f"Instance created with id {inst_id}").send()

    info = await anext(ali_client.describe_instances(inst_id))
    host = info.PublicIpAddress.IpAddress[0]

    await TencentClient().update_record(host)
    await UniMessage.text(f"Instance public ip: {host}").send()

    await do_setup(host)
    await UniMessage.text("Instance setup completed").finish()


def queued() -> object:
    sem = anyio.Semaphore(1)

    async def _() -> AsyncGenerator[None]:
        async with sem:
            yield

    return Depends(_)


queued_parameterless = queued()


@check_sub.assign("create", parameterless=[queued_parameterless])
async def assign_create(bot: Bot, event: Event) -> None:
    if not await SUPERUSER(bot, event):
        await UniMessage.text("Permission denied").finish()

    try:
        await do_create()
    except MatcherException:
        raise
    except Exception as err:
        await UniMessage.text(f"Error creating instance: {err}").finish()


@check_sub.assign("setup", parameterless=[queued_parameterless])
async def assign_setup(bot: Bot, event: Event) -> None:
    if not await SUPERUSER(bot, event):
        await UniMessage.text("Permission denied").finish()

    host = f"{plugin_config.tencent.sub_domain}.{plugin_config.tencent.domain}"

    try:
        await do_setup(host)
    except MatcherException:
        raise
    except Exception as err:
        await UniMessage.text(f"Error setting up instance: {err}").finish()
