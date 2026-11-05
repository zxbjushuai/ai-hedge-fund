"""Create/update the Sub2API OpenCode Go provider used by simulations."""

import os
import subprocess

import requests

API = "http://127.0.0.1:8000"
NAME = "sub2api opencode go"
MODEL = "deepseek-v4.1-flash"
BASE_URL = "http://127.0.0.1:18080/v1"
KEY_ID = 2


def db_password() -> str:
    out = subprocess.check_output(
        [
            "docker",
            "inspect",
            "personal-relay-sub2api-1",
            "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
        ],
        text=True,
    )
    for line in out.splitlines():
        if line.startswith("DATABASE_PASSWORD="):
            return line.split("=", 1)[1]
    raise SystemExit("DATABASE_PASSWORD not found")


def sub2api_key() -> str:
    env = dict(os.environ, PGPASSWORD=db_password())
    out = subprocess.check_output(
        [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            "15432",
            "-U",
            "sub2api",
            "-d",
            "sub2api",
            "-Atc",
            f"select key from api_keys where id={KEY_ID}",
        ],
        text=True,
        env=env,
    )
    key = out.strip()
    if not key:
        raise SystemExit(f"api key {KEY_ID} not found")
    return key


def main() -> None:
    key = sub2api_key()
    providers = requests.get(API + "/dashboard/llm/providers", timeout=30).json()[
        "providers"
    ]
    connection = next((p for p in providers if p["name"] == NAME), None)
    if connection is None:
        response = requests.post(
            API + "/dashboard/llm/providers",
            json={
                "name": NAME,
                "vendor": "custom",
                "protocol": "openai_chat_completions",
                "base_url": BASE_URL,
                "api_key": key,
                "enabled": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        connection = response.json()
        print("created connection", connection["id"])
    else:
        response = requests.patch(
            API + f"/dashboard/llm/providers/{connection['id']}",
            json={"base_url": BASE_URL, "api_key": key, "enabled": True},
            timeout=30,
        )
        response.raise_for_status()
        print("updated connection", connection["id"])

    connection_id = connection["id"]
    response = requests.post(
        API + f"/dashboard/llm/providers/{connection_id}/models",
        json={"model_id": MODEL, "display_name": MODEL, "enabled": True},
        timeout=30,
    )
    if response.status_code == 409:
        print("model already exists")
    else:
        response.raise_for_status()
        print("model added")
    print("connection_id", connection_id)


if __name__ == "__main__":
    main()
