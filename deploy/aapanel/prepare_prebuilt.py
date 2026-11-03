"""One-time operator preparation; never invoked by the deployment SSH key.

Keep the deployment switch off. This retains the existing edge image and copies
its private configuration only within the server, then mounts those files read-only.
"""

import json
import os
import shutil
import sys
import uuid

from docker_deploy import (
    DockerRuntime,
    compose_literals,
    fingerprint,
    private_file,
    runtime_boundary,
)

from deploy import DeploymentError, atomic_json, locked


def prepare(config_path, public_url, probe_ca=None):
    path = private_file(config_path)
    config = json.loads(path.read_text())
    if "public_url" in config:
        raise DeploymentError("PREBUILT_SETUP_ALREADY_RECORDED_REVIEW_EXISTING_STATE")
    config["public_url"] = public_url
    if probe_ca:
        config["probe_ca"] = str(private_file(probe_ca))
    runtime = DockerRuntime(config)
    shared = runtime.base / "shared"
    with locked(shared / "deploy.lock"):
        runtime.preflight()
        if not runtime.ready():
            raise DeploymentError("EXISTING_PUBLIC_STACK_NOT_HEALTHY")
        state_path = shared / "docker-state.json"
        state = (
            json.loads(private_file(state_path).read_text())
            if state_path.exists()
            else {}
        )
        compose = state.get("compose", config["compose"])
        previous = json.loads(
            runtime.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    config["project"],
                    "--file",
                    compose,
                    "config",
                    "--format",
                    "json",
                ]
            )
        )
        before = {
            key: runtime.inspect(config[key]) for key in ("backend", "edge", "postgres")
        }
        inventory = runtime.inventory()
        protected = {p: fingerprint(p) for p in config["protected_files"]}
        for key, item in before.items():
            if (
                item["State"].get("Health", {}).get("Status") != "healthy"
                or item["HostConfig"]["RestartPolicy"]["Name"] != "unless-stopped"
            ):
                raise DeploymentError("HEALTHY_RESTART_ENABLED_STACK_REQUIRED")
            if previous["services"][key].get("restart") != "unless-stopped":
                raise DeploymentError("COMPOSE_RESTART_POLICY_MUST_BE_REVIEWED_FIRST")
        backup = shared / ("prebuilt-setup-" + uuid.uuid4().hex)
        backup.mkdir(mode=0o700)
        shutil.copy2(path, backup / "controller-config.json")
        atomic_json(backup / "compose.json", compose_literals(previous))
        atomic_json(backup / "containers.json", before)
        if state:
            atomic_json(backup / "state.json", state)
        edge_config, assets = shared / "edge-config", shared / "frontend-assets"
        if edge_config.exists() or assets.exists():
            raise DeploymentError(
                "EDGE_COPY_DESTINATION_ALREADY_EXISTS_REVIEW_BEFORE_RETRY"
            )
        edge_config.mkdir(mode=0o700)
        assets.mkdir(mode=0o755)
        runtime.run(
            [
                "docker",
                "cp",
                config["edge"] + ":/etc/nginx/nginx.conf",
                str(edge_config / "nginx.conf"),
            ]
        )
        runtime.run(
            [
                "docker",
                "cp",
                config["edge"] + ":/etc/nginx/certs",
                str(edge_config / "certs"),
            ]
        )
        runtime.run(
            [
                "docker",
                "cp",
                config["edge"] + ":/usr/share/nginx/html/assets/.",
                str(assets),
            ]
        )
        for folder in (assets, *[p for p in assets.rglob("*") if p.is_dir()]):
            os.chmod(folder, 0o755)
        for file in assets.rglob("*"):
            if file.is_symlink():
                raise DeploymentError("UNEXPECTED_EDGE_ASSET_SYMLINK")
            if file.is_file():
                os.chmod(file, 0o644)
        os.chmod(edge_config / "nginx.conf", 0o600)
        candidate = json.loads(json.dumps(previous))
        mounts = [
            {
                "type": "bind",
                "source": str(edge_config / "nginx.conf"),
                "target": "/etc/nginx/nginx.conf",
                "read_only": True,
            },
            {
                "type": "bind",
                "source": str(edge_config / "certs"),
                "target": "/etc/nginx/certs",
                "read_only": True,
            },
            {
                "type": "bind",
                "source": str(assets),
                "target": "/usr/share/nginx/html/assets",
                "read_only": True,
            },
        ]
        targets = {m["target"] for m in mounts}
        if any(m["Destination"] in targets for m in before["edge"]["Mounts"]):
            raise DeploymentError("EXISTING_EDGE_MOUNT_REQUIRES_REVIEW")
        candidate["services"]["edge"].setdefault("volumes", []).extend(mounts)
        candidate["services"]["edge"]["image"] = before["edge"]["Image"]
        candidate["services"]["edge"].pop("build", None)
        target = shared / ("prebuilt-baseline-" + uuid.uuid4().hex + ".json")
        atomic_json(target, compose_literals(candidate))
        try:
            runtime.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    config["project"],
                    "--file",
                    str(target),
                    "up",
                    "--detach",
                    "--no-deps",
                    "--no-build",
                    "edge",
                ],
                timeout=180,
            )
            # Only the edge was recreated, so restore only its manual memberships.
            expected_edge = before["edge"]["NetworkSettings"]["Networks"]
            attached = runtime.inspect(config["edge"])["NetworkSettings"]["Networks"]
            for name, network in expected_edge.items():
                if name not in attached:
                    runtime.run(
                        [
                            "docker",
                            "network",
                            "connect",
                            network["NetworkID"],
                            config["edge"],
                        ]
                    )
            if not runtime.ready():
                raise DeploymentError("PREPARED_EDGE_NOT_HEALTHY")
            after = runtime.inspect(config["edge"])
            expected = runtime_boundary(before["edge"])
            expected["mounts"] = sorted(
                expected["mounts"]
                + [("bind", "", m["source"], m["target"], False) for m in mounts]
            )
            if (
                runtime_boundary(after) != expected
                or after["Image"] != before["edge"]["Image"]
            ):
                raise DeploymentError("EDGE_PREPARATION_CHANGED_UNEXPECTED_SETTINGS")
            now = runtime.inventory()
            if any(
                now.get(n) != i for n, i in inventory.items() if n != config["edge"]
            ):
                raise DeploymentError("UNRELATED_CONTAINER_CHANGED")
            if any(fingerprint(p) != h for p, h in protected.items()):
                raise DeploymentError("PROTECTED_CONFIGURATION_CHANGED")
            state["compose"] = str(target)
            atomic_json(state_path, state)
            atomic_json(path, config)
        except Exception:
            runtime.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    config["project"],
                    "--file",
                    str(backup / "compose.json"),
                    "up",
                    "--detach",
                    "--no-deps",
                    "--no-build",
                    "edge",
                ],
                timeout=180,
            )
            attached = runtime.inspect(config["edge"])["NetworkSettings"]["Networks"]
            for name, network in before["edge"]["NetworkSettings"]["Networks"].items():
                if name not in attached:
                    runtime.run(
                        [
                            "docker",
                            "network",
                            "connect",
                            network["NetworkID"],
                            config["edge"],
                        ]
                    )
            if not runtime.ready():
                raise DeploymentError(
                    "PREPARATION_ROLLBACK_FAILED_OPERATOR_REQUIRED"
                ) from None
            atomic_json(
                path, json.loads((backup / "controller-config.json").read_text())
            )
            if (backup / "state.json").exists():
                atomic_json(state_path, json.loads((backup / "state.json").read_text()))
            elif state_path.exists():
                state_path.unlink()
            raise
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "backup": str(backup),
                    "only_edge_recreated": True,
                    "same_edge_image": True,
                    "public_ready": True,
                }
            )
        )


if __name__ == "__main__":
    if os.name != "posix" or os.geteuid() != 0 or len(sys.argv) != 3:
        raise SystemExit("Usage as root: prepare_prebuilt.py CONFIG_PATH HTTPS_ORIGIN")
    os.umask(0o077)
    prepare(sys.argv[1], sys.argv[2])
