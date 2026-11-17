"""
GreenGrow — Brancher les alertes Telegram
==========================================
1. Dans Telegram, parle à @BotFather : /newbot, choisis un nom. Il te donne
   un jeton. Mets-le dans .env :  TELEGRAM_BOT_TOKEN=123456:ABC...
2. Ouvre la conversation avec TON bot et envoie-lui n'importe quel message.
3. Lance ce script : il trouve l'identifiant de la conversation.

       python scripts/telegram_setup.py

4. Mets la valeur affichée dans .env (TELEGRAM_CHAT_ID=...), puis relance le
   script : il envoie un message d'essai.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.services import notify  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        sys.exit("❌ TELEGRAM_BOT_TOKEN est vide dans .env (étape 1 ci-dessus).")

    if settings.telegram_chat_id:
        ok = notify.send_now("✅ GreenGrow : les alertes Telegram fonctionnent.")
        print("✅ Message d'essai envoyé, regarde Telegram." if ok else "❌ Échec : vérifie le jeton et l'identifiant.")
        return

    try:
        response = httpx.get(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates", timeout=10.0
        )
    except httpx.HTTPError as exc:
        sys.exit(f"❌ Telegram injoignable ({type(exc).__name__}).")
    if response.status_code != 200:
        sys.exit("❌ Telegram refuse ce jeton : recopie-le depuis @BotFather.")

    chats = {}
    for update in response.json().get("result", []):
        chat = (update.get("message") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("first_name") or "?"
    if not chats:
        sys.exit("Aucun message reçu par le bot. Envoie-lui un message dans Telegram, puis relance.")
    print("Conversations trouvées :")
    for chat_id, name in chats.items():
        print(f"  TELEGRAM_CHAT_ID={chat_id}    ({name})")
    print("Copie la ligne voulue dans .env, puis relance ce script pour un essai.")


if __name__ == "__main__":
    main()
