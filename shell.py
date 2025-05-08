#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import shlex
import subprocess
import sys
import tempfile
from contextlib import AsyncExitStack, ExitStack
from pathlib import Path
from typing import (
    Awaitable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    TextIO,
    TypedDict,
    Tuple,
    Union,
)

import yaml


def add_gitconfig_env(config: Mapping[str, str]) -> None:
    i = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    for key, value in config.items():
        os.environ[f"GIT_CONFIG_KEY_{i}"] = key
        os.environ[f"GIT_CONFIG_VALUE_{i}"] = value
        i += 1
    os.environ["GIT_CONFIG_COUNT"] = str(i)


CommandList = List[
    Union[
        str,
        "CommandList",
        TypedDict("SilentCommandList", {"silent": "CommandList"}),
    ]
]


def flatten(xs: CommandList, silent: bool = False) -> Iterator[Tuple[bool, str]]:
    for x in xs:
        if isinstance(x, str):
            yield (silent, x)
        elif isinstance(x, dict):
            yield from flatten(x["silent"], silent=True)
        else:
            yield from flatten(x, silent=silent)


async def pandoc(fp, blocks) -> None:
    p = await asyncio.create_subprocess_exec(
        "pandoc",
        "-f",
        "json",
        "-t",
        "markdown",
        stdin=subprocess.PIPE,
        stdout=fp,
    )
    doc = json.dumps(
        {
            "pandoc-api-version": (1, 23, 1),
            "meta": {},
            "blocks": blocks,
        },
        separators=(",", ":"),
    )
    await p.communicate(doc.encode("utf-8", "surrogateescape"))
    assert await p.wait() == 0


# https://github.com/vim/vim/blob/master/src/xxd/xxd.c#L247-L251
xxd_colors = [
    (r"\x1b\[1;32m", ""),  # printable
    (r"\x1b\[1;31m", "\x1b[1;33m"),  # other non-printable
    (r"\x1b\[1;33m", "\x1b[1;33m"),  # \t, \n, \r
    (r"\x1b\[1;34m", "\x1b[1;31m"),  # 0xFF
    (r"\x1b\[1;37m", "\x1b[1;31m"),  # 0x00
]
xxd_func = (
    'xxd() { command xxd -R always "$@" | sed '
    + " ".join("-e " + shlex.quote(f"s/{old}/{new}/g") for old, new in xxd_colors)
    + "; }"
)


async def run_job(md: TextIO, texpath: str, commands):
    with open(texpath, "w+", encoding="utf-8") as tex:
        # https://tex.stackexchange.com/a/99871
        tex.write(r"\begin{SaveVerbatim}[commandchars=\\\{\}]{VerbCode}")
        # tex.write(rb"\begin{Verbatim}")
        tex.write("\n")
        tex.flush()
        async with AsyncExitStack() as exit:
            temp = exit.enter_context(
                tempfile.TemporaryDirectory(dir="/tmp", prefix="tmp.")
            )
            work = os.path.join(temp, "d")
            os.mkdir(work)
            r_shell_sed, w_shell_sed = os.pipe()
            try:
                with ExitStack() as close:
                    close.callback(os.close, r_shell_sed)

                    r_sed_ansi, w_sed_ansi = os.pipe()
                    close.callback(os.close, r_sed_ansi)
                    close.callback(os.close, w_sed_ansi)

                    sed = await asyncio.create_subprocess_exec(
                        "sed",
                        # bold only not supported by ansi2html
                        "-e",
                        "s/\\x1b\\[1m//g",
                        # \ in fancyvrb
                        "-e",
                        r"s/\\/\\textbackslash/g",
                        # {} in fancyvrb
                        "-e",
                        r"s/[{}]/{\\&}/g",
                        # wrap \textbackslash in brackets so it does not absorb
                        # whitespaces or joins with the next word
                        "-e",
                        r"s/\\textbackslash/{&}/g",
                        stdin=r_shell_sed,
                        stdout=w_sed_ansi,
                    )
                    exit.push_async_callback(sed.wait)

                    ansi2html = await asyncio.create_subprocess_exec(
                        "ansi2html",
                        "--inline",
                        "--latex",
                        stdin=r_sed_ansi,
                        stdout=tex,
                    )
                    # this way the wait is after os.close(w)
                    exit.push_async_callback(ansi2html.wait)

                for silent, cmd in flatten(commands):
                    # do not pipe silent commands and their output to the pipe
                    out = sys.stdout.fileno() if silent else w_shell_sed

                    lines = cmd.splitlines()
                    lines = ["", "$ " + lines[0]] + ["  " + x for x in lines[1:]]
                    for line in lines:
                        os.write(out, f"\033[1;32m{line}\033[22;39m\n".encode("utf-8"))

                    bash = await asyncio.create_subprocess_exec(
                        "bash",
                        "-euo",
                        "pipefail",
                        cwd=work,
                        stdin=subprocess.PIPE,
                        stdout=out,
                        stderr=out,
                    )
                    try:
                        await bash.communicate(
                            "; ".join(
                                [
                                    'ls() { command ls --color=always "$@"; }',
                                    xxd_func,
                                    "shopt -s dotglob",
                                    'find-ls() { find * -exec ls --color=always "$@" -d -- {} +; }',
                                    cmd,
                                ]
                            ).encode("utf-8")
                        )
                    except BaseException:
                        bash.terminate()
                        raise
                    finally:
                        await bash.wait()
                        # assert await bash.wait() == 0, f"{cmd!r} failed"
            finally:
                os.close(w_shell_sed)
        # tex.write(rb"\end{Verbatim}")
        tex.write(r"\end{SaveVerbatim}")
        tex.write("\n")
        tex.write(
            # r"\adjustbox{max width=\linewidth,max totalheight=\textheight -2em}{\BUseVerbatim{VerbCode}}"
            r"\scalebox{.75}{\BUseVerbatim{VerbCode}}"
        )
        tex.write("\n")

        tex.flush()
        tex.seek(0)

        md.flush()
        await pandoc(
            md,
            [
                # inline LaTeX
                {"t": "RawBlock", "c": ("latex", tex.read())},
            ],
        )


async def do_part(dest: Path, part) -> None:
    with open(dest, "w", encoding="utf-8") as out:
        title = part.get("title")
        await pandoc(
            out,
            [
                # Create an H1 with the .fragile attribute, this creates a
                # [fragile] frame for us, which fancyvrb needs.
                {
                    "t": "Header",
                    "c": (
                        part.get("level", 2),  # allows to create <h1>
                        ("", ["fragile", "unnumbered"], []),
                        (
                            []
                            if title is None
                            else [
                                {"t": "Str", "c": title},
                            ]
                        ),
                    ),
                },
            ],
        )

        async def do_subpart(subpart):
            if "run" in subpart:
                texpath = str(dest)[: -len(dest.suffix)] + ".tex"
                await run_job(out, texpath, subpart["run"])
            elif "markdown" in subpart:
                out.write(subpart["markdown"])

        if "multi" in part:
            for subpart in part["multi"]:
                await do_subpart(subpart)
        else:
            await do_subpart(part)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("-i", "--input", type=Path, required=True)
    args = p.parse_args()

    add_gitconfig_env(
        {
            "user.name": "schnusch",
            "user.email": "schnusch@users.noreply.github.com",
            "gc.auto": "0",
            "init.defaultBranch": "main",
            "color.ui": "always",
            "log.decorate": "short",
            "core.pager": "",
        }
    )
    os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = (
        "1980-01-01T01:00:00+01:00"
    )
    os.environ["LC_ALL"] = "en_US.UTF-8"
    os.environ["PATH"] = os.getcwd() + ":" + os.environ["PATH"]

    with open(args.input, "r", encoding="utf-8") as fp:
        all_commands = yaml.safe_load(fp)

    args.output.mkdir(parents=True, exist_ok=True)
    intlen = len(str(len(all_commands) + 1))

    async def coro_gather():
        await asyncio.gather(
            *(
                do_part(
                    args.output / (str(i).rjust(intlen, "0") + ".md"),
                    part,
                )
                for i, part in enumerate(all_commands, start=2)
            )
        )

    asyncio.run(coro_gather())
