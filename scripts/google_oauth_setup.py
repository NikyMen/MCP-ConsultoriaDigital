"""Helper one-shot para obtener el GOOGLE_CALENDAR_REFRESH_TOKEN.

Uso:
    1. Tener listo el client_id y client_secret del OAuth 2.0 Desktop Client
       (creado en Google Cloud Console, ver plan o README).
    2. Correr desde la raíz del repo, en tu máquina LOCAL (no en el VPS,
       porque necesita abrir un browser):
           python scripts/google_oauth_setup.py
    3. Pegar client_id y client_secret cuando los pida.
    4. Se abre el browser. Logueate con la cuenta de Google del comercial
       donde van a caer los eventos. Aprobá los permisos.
    5. El script imprime el `refresh_token`. Copialo y pegalo en el .env del
       VPS como GOOGLE_CALENDAR_REFRESH_TOKEN=...

Requisitos: `pip install google-auth-oauthlib` (ya incluido en requirements.txt).
"""
from __future__ import annotations

import json
import sys
from getpass import getpass

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def main() -> int:
    print("=== Google Calendar OAuth Setup ===\n")
    client_id = input("client_id: ").strip()
    client_secret = getpass("client_secret (oculto): ").strip()
    if not client_id or not client_secret:
        print("Faltan client_id y/o client_secret. Abortando.", file=sys.stderr)
        return 1

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print("\nAbriendo browser para autorizar...")
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print(
            "\n⚠️  No se recibió refresh_token. Probá revocando el acceso en "
            "https://myaccount.google.com/permissions y corré el script de nuevo.",
            file=sys.stderr,
        )
        return 2

    print("\n✅ Listo. Copiá estas líneas al .env del VPS:\n")
    print(f"GOOGLE_CALENDAR_CLIENT_ID={client_id}")
    print(f"GOOGLE_CALENDAR_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_CALENDAR_REFRESH_TOKEN={creds.refresh_token}")
    print(f"GOOGLE_CALENDAR_ID=primary")
    print(f"GOOGLE_CALENDAR_TIMEZONE=America/Argentina/Buenos_Aires")
    print(f"GOOGLE_CALENDAR_DURACION_DEFAULT_MIN=30")
    print()
    print("(token_expiry:", creds.expiry, ")")
    print("(scopes:", json.dumps(list(creds.scopes or [])), ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
