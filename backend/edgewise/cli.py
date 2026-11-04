"""Command line: `edgewise <command>`. Run on the server, e.g.

docker compose exec api edgewise create-owner
"""

from __future__ import annotations

import argparse
import getpass
import io
import logging
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import qrcode
from sqlalchemy.orm import Session, sessionmaker

from edgewise.auth import totp
from edgewise.config import get_settings
from edgewise.db.models import LedgerKind
from edgewise.db.session import make_engine, make_session_factory, transaction
from edgewise.services import auth as auth_service
from edgewise.services import portfolio

Prompt = Callable[[str], str]


def _now() -> datetime:
    return datetime.now(UTC)


def _factory() -> sessionmaker[Session]:
    return make_session_factory(make_engine(get_settings().database_url))


def _ask_password(secret_prompt: Prompt, out: io.TextIOBase | None = None) -> str:
    for _ in range(3):
        first = secret_prompt("New password (at least 12 characters): ")
        second = secret_prompt("Type it again: ")
        if first != second:
            print("Those didn't match. Try again.", file=out or sys.stdout)
            continue
        return first
    raise SystemExit("Gave up after three tries.")


def _qr_text(data: str) -> str:
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    buffer = io.StringIO()
    qr.print_ascii(out=buffer, invert=True)
    return buffer.getvalue()


def _enrol_authenticator(username: str, prompt: Prompt) -> str:
    """Show a QR code, then make the owner type a code to prove the app is set up."""
    secret = totp.new_secret()
    uri = totp.provisioning_uri(secret, username)
    print("\nScan this with your authenticator app (Google Authenticator, Microsoft")
    print("Authenticator, 1Password, ...). On a phone, a large terminal window helps.\n")
    print(_qr_text(uri))
    print(f"Can't scan it? Add an account by hand with this key:\n  {secret}\n")
    for _ in range(3):
        code = prompt("Type the 6-digit code the app shows now: ")
        if totp.verify(secret, code, now=_now(), last_step=None) is not None:
            return secret
        print("That code didn't match. Wait for the next one and try again.")
    raise SystemExit("Couldn't confirm the authenticator app. Nothing was saved.")


def cmd_create_owner(args: argparse.Namespace, prompt: Prompt, secret_prompt: Prompt) -> int:
    settings = get_settings()
    factory = _factory()
    with factory() as session:
        if auth_service.owner_exists(session):
            print("An owner account already exists. Use reset-2fa or set-password instead.")
            return 1
    username = args.username or os.environ.get("OWNER_EMAIL") or prompt("Your email: ")
    password = _ask_password(secret_prompt)
    secret = _enrol_authenticator(username, prompt)
    with transaction(factory) as session:
        auth_service.create_owner(
            session,
            settings,
            username=username,
            password=password,
            totp_secret=secret,
            now=_now(),
        )
    print(f"\nDone. Sign in as {auth_service.normalise_username(username)} with your password")
    print("and a code from the app.")
    return 0


def cmd_reset_2fa(args: argparse.Namespace, prompt: Prompt, secret_prompt: Prompt) -> int:
    settings = get_settings()
    factory = _factory()
    with factory() as session:
        owner = auth_service.get_owner(session, args.username)
        username = owner.username
    secret = _enrol_authenticator(username, prompt)
    with transaction(factory) as session:
        owner = auth_service.get_owner(session, username)
        auth_service.set_totp_secret(session, settings, owner, secret, now=_now())
    print("Authenticator reset. All devices were signed out.")
    return 0


def cmd_set_password(args: argparse.Namespace, prompt: Prompt, secret_prompt: Prompt) -> int:
    factory = _factory()
    password = _ask_password(secret_prompt)
    with transaction(factory) as session:
        owner = auth_service.get_owner(session, args.username)
        auth_service.set_password(session, owner, password, now=_now())
    print("Password changed. All devices were signed out.")
    return 0


def _amount(text: str) -> Decimal:
    try:
        value = Decimal(text.replace("$", "").replace(",", ""))
    except InvalidOperation as exc:
        raise SystemExit(f"Not an amount: {text}") from exc
    if value <= 0:
        raise SystemExit("Enter an amount above $0.")
    return value


def cmd_deposit(args: argparse.Namespace, prompt: Prompt, secret_prompt: Prompt) -> int:
    with transaction(_factory()) as session:
        entry = portfolio.add_ledger_entry(
            session,
            kind=LedgerKind.DEPOSIT,
            amount=_amount(args.amount),
            now=_now(),
            actor="owner",
            note=args.note,
        )
    print(f"Bankroll is now ${entry.balance_after:,.2f}.")
    return 0


def cmd_withdraw(args: argparse.Namespace, prompt: Prompt, secret_prompt: Prompt) -> int:
    with transaction(_factory()) as session:
        entry = portfolio.add_ledger_entry(
            session,
            kind=LedgerKind.WITHDRAWAL,
            amount=-_amount(args.amount),
            now=_now(),
            actor="owner",
            note=args.note,
        )
    print(f"Bankroll is now ${entry.balance_after:,.2f}.")
    return 0


def cmd_worker(args: argparse.Namespace, prompt: Prompt, secret_prompt: Prompt) -> int:
    from edgewise.worker.main import run_worker

    run_worker()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edgewise", description="Edgewise server commands")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-owner", help="create the owner login (once)")
    p.add_argument("--username", help="email or username (default: OWNER_EMAIL)")
    p.set_defaults(func=cmd_create_owner)

    p = sub.add_parser("reset-2fa", help="set up the authenticator app again")
    p.add_argument("--username", required=True)
    p.set_defaults(func=cmd_reset_2fa)

    p = sub.add_parser("set-password", help="change the owner password")
    p.add_argument("--username", required=True)
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("deposit", help="add money to the bankroll record")
    p.add_argument("amount")
    p.add_argument("--note")
    p.set_defaults(func=cmd_deposit)

    p = sub.add_parser("withdraw", help="take money out of the bankroll record")
    p.add_argument("amount")
    p.add_argument("--note")
    p.set_defaults(func=cmd_withdraw)

    p = sub.add_parser("worker", help="run the background worker")
    p.set_defaults(func=cmd_worker)
    return parser


def main(
    argv: list[str] | None = None,
    prompt: Prompt = input,
    secret_prompt: Prompt = getpass.getpass,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args, prompt, secret_prompt)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
