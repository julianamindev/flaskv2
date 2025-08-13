import os, json, socket

SECRET_MAP = {
    2: "flaskv2/staging",
    3: "flaskv2/prod"
}

def load_env():
    envnum = int(os.getenv("ENVNUM", "2"))

    # --- Heavy work only once per process tree ---
    if os.environ.get("L2A_ENV_BOOTSTRAPPED") != "1":
        if envnum == 1:
            # Local: load .env once (parent); child inherits the env
            from dotenv import load_dotenv, find_dotenv
            load_dotenv(find_dotenv(), override=False)
            os.environ.setdefault("ENVNUM", "1")
        else:
            # Staging/Prod: fetch AWS secrets once (parent); child inherits the env
            import boto3
            from botocore.exceptions import ClientError
            secret_id = SECRET_MAP.get(envnum)
            if secret_id is None:
                raise RuntimeError(f"Unsupported ENVNUM={envnum}")
            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            sm = boto3.client("secretsmanager", region_name=region)
            try:
                resp = sm.get_secret_value(SecretId=secret_id)
                s = resp.get("SecretString") or resp.get("SecretBinary", b"").decode("utf-8")
                data = json.loads(s)
            except ClientError as e:
                raise RuntimeError(f"Failed to load secrets '{secret_id}': {e}")

            for k, v in data.items():
                os.environ.setdefault(k, str(v))
            os.environ["ENVNUM"] = str(envnum)

        # mark heavy work done (propagates to child via environment)
        os.environ["L2A_ENV_BOOTSTRAPPED"] = "1"

    # --- Print only in serving child when reloader is active ---
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        print(f"Running in TEST: {socket.gethostname()}")

    return envnum
