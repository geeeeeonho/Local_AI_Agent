"""menu — run.py 메인 메뉴 루프."""
from __future__ import annotations

from pathlib import Path

from . import ui, handlers, settings_store
from .i18n import t


def main_loop(env: Path):
    cfg = settings_store.load()

    while True:
        ui.header(
            t("menu.title"),
            t("menu.install_path", path=str(env)),
        )

        last = cfg.last_menu_choice
        last_hint = f"  {ui.C.DIM}{t('menu.last_choice', choice=last)}{ui.C.E}" if last else ""

        print(f"  {ui.C.BD}[1]{ui.C.E} {t('menu.opt1')}")
        print(f"      {ui.C.DIM}{t('menu.opt1_desc')}{ui.C.E}")
        print()
        print(f"  {ui.C.BD}[2]{ui.C.E} {t('menu.opt2')} "
              f"{ui.C.G}*{t('menu.opt2_recommended')}*{ui.C.E}")
        print(f"      {ui.C.DIM}{t('menu.opt2_desc')}{ui.C.E}")
        print()
        print(f"  {ui.C.BD}[3]{ui.C.E} {t('menu.opt3')} "
              f"{ui.C.R}!! {t('menu.opt3_dangerous')}{ui.C.E}")
        print(f"      {ui.C.DIM}{t('menu.opt3_desc')}{ui.C.E}")
        print()
        ui.hr(color=ui.C.DIM)
        print()
        print(f"  {ui.C.BD}[4]{ui.C.E} {t('menu.opt4')}")
        print(f"  {ui.C.BD}[5]{ui.C.E} {t('menu.opt5')}")
        print(f"  {ui.C.BD}[6]{ui.C.E} {t('menu.opt6')}")
        print(f"  {ui.C.BD}[7]{ui.C.E} {t('menu.opt7')}")
        print(f"  {ui.C.BD}[8]{ui.C.E} {t('menu.opt8')}")
        print()
        print(f"  {ui.C.BD}[Q]{ui.C.E} {t('menu.optq')}{last_hint}")
        print()

        choice = ui.prompt("> ").lower()

        if choice == "1":
            handlers.start_chat(env)
        elif choice == "2":
            handlers.start_agent_sandbox(env)
        elif choice == "3":
            handlers.start_agent_direct(env)
        elif choice == "4":
            handlers.start_ollama(env)
        elif choice == "5":
            handlers.show_model_info(env)
        elif choice == "6":
            handlers.rebuild_sandbox_image(env)
        elif choice == "7":
            handlers.manage_searxng(env)
        elif choice == "8":
            handlers.manage_settings(env)
            cfg = settings_store.load()
        elif choice in ("q", "quit", "exit"):
            print()
            print(t("menu.exiting"))
            return
        else:
            continue

        if choice in {"1", "2", "3", "4", "5", "6", "7", "8"}:
            settings_store.update_last_menu_choice(cfg, choice)
            settings_store.save(cfg)
