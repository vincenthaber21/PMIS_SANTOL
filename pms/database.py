"""Database URL parsing for Django MySQL configuration."""
from urllib.parse import parse_qs, unquote, urlparse


def get_secure_database_config(db_url):
    parsed = urlparse(db_url)
    query = parse_qs(parsed.query)

    options = {
        "connect_timeout": 20,
        "init_command": "SET sql_mode='STRICT_TRANS_TABLES', time_zone='+08:00'",
        "charset": "utf8mb4",
    }

    ssl_ca = query.get("ssl_ca", [None])[0]
    if ssl_ca:
        options["ssl"] = {"ca": ssl_ca}

    return {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": unquote(parsed.path.lstrip("/")),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "127.0.0.1",
            "PORT": str(parsed.port or 3306),
            "OPTIONS": options,
        }
    }
