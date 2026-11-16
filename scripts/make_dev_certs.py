"""
GreenGrow — Certificats TLS de développement
=============================================
Lancement : python scripts/make_dev_certs.py [--host 192.168.1.20] [--force]

Crée dans certs/ :
  ca.crt, ca.key          une petite autorité de certification (CA) à toi
  server.crt, server.key  le certificat du broker, signé par cette CA

À quoi ça sert ?
TLS fait deux choses : il CHIFFRE la conversation, et il PROUVE au client
qu'il parle au bon serveur. La preuve fonctionne ainsi : le broker présente
server.crt ; le client (backend, simulateur, ESP32) possède ca.crt et vérifie
que le certificat a bien été signé par cette CA et qu'il porte le nom du
serveur auquel il voulait se connecter. Sans cette vérification, n'importe
qui pourrait se faire passer pour le broker et récupérer les mots de passe.

  ca.crt      -> public : on le copie dans chaque client (y compris l'ESP32)
  *.key       -> SECRET : ne quitte jamais cette machine, ignoré par Git

En production (étape 5), le certificat viendra d'une vraie autorité
(Let's Encrypt) ; le principe restera exactement le même.
"""

import argparse
import datetime
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERTS = Path(__file__).resolve().parent.parent / "certs"
NOW = datetime.datetime.now(datetime.timezone.utc)


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GreenGrow (dev)"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def _write_key(path: Path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def make_ca():
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("GreenGrow Dev CA"))
        .issuer_name(_name("GreenGrow Dev CA"))  # auto-signé : c'est la racine
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - datetime.timedelta(minutes=5))
        .not_valid_after(NOW + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_server(ca_key, ca_cert, hosts: list[str]):
    # Les noms et adresses sous lesquels le broker sera joint. Le client
    # refuse la connexion si celui qu'il a utilisé n'est pas dans cette liste.
    names: list[x509.GeneralName] = []
    for host in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(hosts[0]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - datetime.timedelta(minutes=5))
        .not_valid_after(NOW + datetime.timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def main() -> None:
    parser = argparse.ArgumentParser(description="Certificats TLS de développement GreenGrow")
    parser.add_argument(
        "--host", action="append", default=[],
        help="nom ou adresse IP supplémentaire du broker (ex. l'IP de ton PC sur le Wi-Fi, pour l'ESP32)",
    )
    parser.add_argument("--force", action="store_true", help="recrée aussi la CA (il faudra la recopier dans tous les clients)")
    args = parser.parse_args()

    CERTS.mkdir(exist_ok=True)
    ca_crt, ca_key_path = CERTS / "ca.crt", CERTS / "ca.key"

    if ca_crt.exists() and ca_key_path.exists() and not args.force:
        # On garde la CA existante : les clients qui la connaissent déjà
        # continueront de faire confiance au nouveau certificat serveur.
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_cert = x509.load_pem_x509_certificate(ca_crt.read_bytes())
        print("CA existante conservée (certs/ca.crt)")
    else:
        ca_key, ca_cert = make_ca()
        _write_key(ca_key_path, ca_key)
        os.chmod(ca_key_path, 0o600)
        ca_crt.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        print("Nouvelle CA créée (certs/ca.crt)")

    hosts = ["localhost", "mosquitto", "127.0.0.1", *args.host]
    key, cert = make_server(ca_key, ca_cert, hosts)
    _write_key(CERTS / "server.key", key)
    # Lisible par le conteneur Mosquitto (certificat de DÉVELOPPEMENT uniquement).
    os.chmod(CERTS / "server.key", 0o644)
    (CERTS / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Certificat du broker créé pour : {', '.join(hosts)}")
    print("Relance le broker pour le prendre en compte : docker compose restart mosquitto")


if __name__ == "__main__":
    main()
