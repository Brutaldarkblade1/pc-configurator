import os
import smtplib
from email.message import EmailMessage


def send_verification_email(recipient: str, verify_url: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM") or user

    if not host or not sender:
        raise RuntimeError("SMTP není nakonfigurované (SMTP_HOST/SMTP_FROM/SMTP_USER)")

    msg = EmailMessage()
    msg["Subject"] = "Ověření účtu"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(
        "Ahoj,\n\n"
        "pro ověření účtu klikni na odkaz:\n"
        f"{verify_url}\n\n"
        "Pokud jsi účet nezakládal, email ignoruj.\n"
    )

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()
        if port == 587:
            server.starttls()
        if user and password:
            server.login(user, password)
        server.send_message(msg)
