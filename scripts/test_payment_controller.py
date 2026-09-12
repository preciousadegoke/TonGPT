"""Run real Engine controller regressions against a disposable PostgreSQL 15.

Requires Docker, .NET 8, and the postgres:15-alpine image. Never uses .env or the
application database. Only the container created here is removed on completion.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import uuid


def main():
    root = Path(__file__).resolve().parents[1]
    suffix = uuid.uuid4().hex
    name = "tongpt-payment-tests-" + suffix
    database = "tongpt_payment_tests_" + suffix
    password = uuid.uuid4().hex  # disposable test credential; never printed
    subprocess.run(["docker", "image", "inspect", "postgres:15-alpine"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    container_id = None
    try:
        result = subprocess.run([
            "docker", "run", "--detach", "--rm", "--name", name,
            "--label", "tongpt.disposable-payment-test=true",
            "--env", "POSTGRES_PASSWORD=" + password, "--env", "POSTGRES_DB=" + database,
            "--publish", "127.0.0.1::5432", "postgres:15-alpine",
        ], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()
        metadata = json.loads(subprocess.run(["docker", "inspect", container_id],
                              capture_output=True, text=True, check=True).stdout)[0]
        assert metadata["Name"] == "/" + name
        port = metadata["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        for _ in range(30):
            ready = subprocess.run(["docker", "exec", container_id, "pg_isready", "-U", "postgres", "-d", database],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise TimeoutError("Disposable PostgreSQL did not become ready within 30 checks")
        env = os.environ.copy()
        env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
        env["TONGPT_PAYMENT_TEST_DB"] = (
            f"Host=127.0.0.1;Port={port};Database={database};Username=postgres;Password={password};Timeout=15"
        )
        print("Running against isolated container:", name, flush=True)
        result = subprocess.run([
            "dotnet", "run", "--project",
            str(root / "backend/TonGPT.Engine.PaymentTests/TonGPT.Engine.PaymentTests.csproj"),
            "--verbosity", "quiet",
        ], cwd=root, env=env, timeout=300)
        return result.returncode
    finally:
        if container_id:
            metadata = json.loads(subprocess.run(["docker", "inspect", container_id],
                                  capture_output=True, text=True, check=True).stdout)[0]
            assert metadata["Name"] == "/" + name
            assert metadata["Config"]["Labels"].get("tongpt.disposable-payment-test") == "true"
            subprocess.run(["docker", "rm", "--force", container_id],
                           stdout=subprocess.DEVNULL, check=True)
            print("Removed disposable payment-test container.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
