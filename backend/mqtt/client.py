"""Fabrique de clients MQTT : TOUS nos clients se connectent de la même façon sûre."""

import ssl

import paho.mqtt.client as mqtt

from backend.config import get_settings


def new_client(client_id: str, username: str, password: str, clean_session: bool = True) -> mqtt.Client:
    settings = get_settings()
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=clean_session
    )
    client.username_pw_set(username, password)
    # tls_set avec ca_certs = "ne fais confiance qu'aux certificats signés par
    # cette CA". CERT_REQUIRED + vérification du nom d'hôte sont explicites :
    # on ne veut JAMAIS d'un client qui accepte n'importe quel certificat
    # (l'équivalent Python du setInsecure() de l'ESP32).
    client.tls_set(
        ca_certs=settings.mqtt_ca_file,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)
    return client
