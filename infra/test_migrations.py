"""Integration check using isolated Docker volumes; never touches the Broski DB.

Run: python3 infra/test_migrations.py
Requires a running Docker daemon and network access for uncached images.
"""

import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {
        **os.environ,
        "PGPASSWORD": secrets.token_hex(24),
        # Required only while rendering Compose; the API service is removed below.
        "BROSKI_DEV_TOKEN": secrets.token_hex(24),
    }
    config = json.loads(subprocess.check_output(
        ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "config", "--format", "json"],
        env=env, text=True,
    ))
    # Reuse the real migration configuration, but remove the API and host ports.
    config.pop("name", None)
    config["services"] = {key: config["services"][key] for key in ("db", "migrate")}
    config["services"]["db"].pop("ports", None)
    for volume in config.get("volumes", {}).values():
        volume.pop("name", None)
    project = "broski-migration-test-" + secrets.token_hex(5)

    with tempfile.TemporaryDirectory(prefix="broski-migrations-") as directory:
        path = Path(directory) / "compose.json"
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        command = ["docker", "compose", "-p", project, "-f", str(path)]

        def run(*args, succeeds=True):
            result = subprocess.run(command + list(args), env=env, text=True, capture_output=True)
            if (result.returncode == 0) != succeeds:
                # Do not echo rendered configuration or random connection credentials.
                output = (result.stdout + result.stderr).replace(env["PGPASSWORD"], "[redacted]")
                raise RuntimeError(output)
            return result.stdout.strip()

        def sql(query, database="broski"):
            return run("exec", "-T", "db", "psql", "-U", "broski", "-d", database,
                       "-v", "ON_ERROR_STOP=1", "-Atc", query)

        def require(condition, message):
            if not condition:
                raise RuntimeError(message)

        try:
            run("up", "-d", "--wait", "db")
            print("Fresh database: migrate and validate", flush=True)
            run("run", "--rm", "migrate", "migrate")
            run("run", "--rm", "migrate", "validate")
            require(sql("SELECT count(*) FROM pg_extension WHERE extname='vector'") == "1",
                    "pgvector was not enabled")
            history = "SELECT count(*) FROM flyway_history.flyway_schema_history WHERE version='1' AND success"
            require(sql(history) == "1", "Expected one successful V1 migration")
            require(sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='documents'") == "1",
                    "documents table was not created")
            require(sql("SELECT count(*) FROM flyway_history.flyway_schema_history WHERE version='2' AND success") == "1",
                    "Expected one successful V2 migration")
            print("Repeat migration: no duplicate version", flush=True)
            run("run", "--rm", "migrate", "migrate")
            require(sql(history) == "1", "Repeated migration duplicated V1")
            print("Existing extension-only database: adopt without baseline", flush=True)
            sql("CREATE DATABASE broski_legacy")
            sql("CREATE EXTENSION vector", "broski_legacy")
            run("run", "--rm", "-e", "FLYWAY_URL=jdbc:postgresql://db:5432/broski_legacy",
                "migrate", "migrate")
            require(sql(history, "broski_legacy") == "1", "Legacy database did not apply V1")
            print("Invalid checksum: validation must fail", flush=True)
            sql("UPDATE flyway_history.flyway_schema_history SET checksum=checksum+1 WHERE version='1'")
            run("run", "--rm", "migrate", "validate", succeeds=False)
            print("PASS: fresh, repeat, existing extension, and checksum checks", flush=True)
        finally:
            # Only the uniquely named test project's resources are removed.
            run("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
