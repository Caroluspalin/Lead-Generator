"""SMTP-diagnostiikka: yhdistää ja kirjautuu, kertoo missä vaiheessa yhteys katkeaa.

Ei tulosta salasanaa eikä tunnuksia (AUTH-vaihe piilotetaan debug-tulosteesta, osoitteet maskataan).
Ei lähetä viestiä ilman --send-test-lippua; silloinkin vain omaan osoitteeseen (SMTP_FROM).

Aja backend/-kansiosta:  python scripts/smtp_check.py [--quiet] [--send-test]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.smtp_client import (  # noqa: E402
    SmtpConfig, SmtpFailure, Stage, _close_quietly, build_message, classify, open_smtp,
)


def mask(address: str) -> str:
    if "@" not in address:
        return "<set>" if address else "<missing>"
    local, domain = address.split("@", 1)
    return f"{local[:1]}***@{domain}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiet", action="store_true", help="ei SMTP-protokollan debug-tulostetta")
    parser.add_argument("--send-test", action="store_true", help="lähetä yksi testiviesti osoitteeseen SMTP_FROM")
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    cfg = SmtpConfig(
        host=os.getenv("SMTP_HOST", ""),
        port=int(os.getenv("SMTP_PORT", "587")),
        user=os.getenv("SMTP_USER", ""),
        password=os.getenv("SMTP_PASSWORD", ""),
        from_addr=os.getenv("SMTP_FROM", ""),
    )

    print(f"Host: {cfg.host or '<missing>'}  Port: {cfg.port}  Mode: {'SSL (465)' if cfg.port == 465 else 'STARTTLS'}")
    print(f"SMTP_USER: {mask(cfg.user)}  SMTP_FROM: {mask(cfg.from_addr)}  same address: {cfg.user.lower() == cfg.from_addr.lower()}")
    # Vain muotoa koskevat tarkistukset, ei arvoa (Applen salasana: 19 merkkiä muodossa xxxx-xxxx-xxxx-xxxx)
    pw = cfg.password
    quoted = len(pw) > 1 and pw[0] == pw[-1] and pw[0] in ("'", '"')
    print(f"SMTP_PASSWORD: {'set' if pw else 'missing'}, length {len(pw)}, "
          f"contains spaces: {' ' in pw}, leading/trailing whitespace: {pw != pw.strip()}, "
          f"quotes around value: {quoted}")
    missing = cfg.missing()
    if missing:
        print(f"FAIL: missing {', '.join(missing)}")
        return 2

    def on_stage(stage: Stage) -> None:
        print(f"--> stage: {stage}")

    try:
        server = open_smtp(cfg, debug=None if args.quiet else (lambda line: print(f"    {line}")), on_stage=on_stage)
    except SmtpFailure as f:
        print(f"\nFAIL at stage '{f.stage}' ({f.kind}): {f.user_message()}")
        return 1
    print("\nOK: connected, TLS and login succeeded.")

    try:
        if args.send_test:
            # Sama viestin rakennus kuin /send-email-endpointissa
            msg = build_message(
                cfg.from_addr, cfg.from_addr, "Agency Hunter SMTP test",
                "Agency Hunter SMTP test. If you can read this, sending works.",
            )
            print("--> stage: send (test message to SMTP_FROM)")
            try:
                server.send_message(msg)
            except Exception as exc:
                failure = classify(exc, "send")
                print(f"\nFAIL at stage 'send' ({failure.kind}): {failure.user_message()}")
                return 1
            print(f"OK: test message sent to {mask(cfg.from_addr)}")
    finally:
        _close_quietly(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
