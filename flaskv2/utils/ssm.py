

import shlex
from typing import Any, Dict, List, Optional

import boto3


def ssm_run_shell(
    *,
    instance_ids: List[str],
    lines: List[str],
    region: str = "us-east-1",
    run_as_user: Optional[str] = None,
    use_login_shell: bool = False,
    # Output options (all optional):

    comment: Optional[str] = None,
) -> str:
    """
    Send an AWS-RunShellScript command to one or more instances.

    - `lines`: the shell lines to run (we wrap them into a single subshell)
    - `run_as_user`: run everything as this user (via sudo)
    - `use_login_shell`: True -> bash -lc (reads profile); False -> bash --noprofile --norc
    - output_* and cloudwatch_log_group: enable S3/CW logs if you want full logs
    - returns the SSM CommandId
    """
    if not instance_ids:
        raise ValueError("instance_ids must be non-empty")
    if not lines:
        raise ValueError("lines must be non-empty")

    # Build the single script
    script = "\n".join(lines)

    # Choose the shell invocation
    if use_login_shell:
        shell_inv = f"bash -lc {shlex.quote(script)}"
    else:
        shell_inv = f"bash --noprofile --norc -c {shlex.quote(script)}"

    # Run entirely as another user, if requested
    if run_as_user:
        launcher = f"sudo -u {shlex.quote(run_as_user)} {shell_inv}"
    else:
        launcher = shell_inv

    params: Dict[str, Any] = {
        "InstanceIds": instance_ids,
        "DocumentName": "AWS-RunShellScript",
        "Parameters": {"commands": [launcher]},
    }

    if comment:
        params["Comment"] = comment

    ssm = boto3.client("ssm", region_name=region)
    resp = ssm.send_command(**params)
    return resp["Command"]["CommandId"]

def ssm_get_command_status(
    *,
    command_id: str,
    instance_id: str,
    region: str = "us-east-1",
) -> Dict[str, Any]:
    """
    Read back status + stdout/stderr (and S3/CW URLs if enabled).
    Uses GetCommandInvocation so we can also surface StandardOutputUrl.
    """
    ssm = boto3.client("ssm", region_name=region)
    inv = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)

    return {
        "ok": True,
        "status": inv.get("Status") or "Pending",
        "status_details": inv.get("StatusDetails") or "",
        "stdout": inv.get("StandardOutputContent") or "",
        "stderr": inv.get("StandardErrorContent") or "",
        "stdout_url": inv.get("StandardOutputUrl") or "",
        "stderr_url": inv.get("StandardErrorUrl") or "",
    }


def build_inject_lines(
    *,
    bucket: str,
    root: str,
    key_prefix: str,
    files: list[str],
    dest: str = "/opt/infor/landmark/tmp",
    ensure_dest_exists: bool = True,
    preclear_names: list[str] | None = None,
    filtered_listing: bool = False,
    list_filter_regex: str | None = None,
    extra_before: list[str] | None = None,
    extra_after: list[str] | None = None
) -> list[str]:
    """
    Build shell lines for the 'inject builds' task, with configurable knobs.

    - Set preclear_names=[] to skip pre-clearing.
    - Set filtered_listing=False for a full 'ls -lah "$DEST"'.
    - Tweak list_filter_regex to change what 'grep -E' shows (only used if filtered_listing=True).
    - Put any one-off commands in extra_before/extra_after.
    """
    s3_base = f"s3://{bucket}/{root}{key_prefix}"
    lines: list[str] = []

    # strict shell
    lines.append("set -euo pipefail")

    # Destination + (optional) existence check
    lines.append(f'DEST="{dest}"')
    lines.append('echo "[info] destination: $DEST"')
    if ensure_dest_exists:
        lines.append('test -d "$DEST" || { echo "[error] destination does not exist: $DEST"; exit 1; }')

    # Optional: user-provided pre-steps
    if extra_before:
        lines.extend(extra_before)

    # Pre-clear (if configured)
    names =  preclear_names
    if names:
        lines.append('echo "[info] pre-clearing known files"')
        for fname in names:
            lines.append(f'echo " - rm -f $DEST/{fname}"')
            lines.append(f'rm -f "$DEST/{fname}" || true')

    # Copy selected files
    lines.append('echo "[info] copying selected files"')
    for name in files:
        s3_src = f"{s3_base}{name}"
        lines.append(f'echo " - aws s3 cp {s3_src} $DEST/"')
        lines.append(f'aws s3 cp "{s3_src}" "$DEST/" --only-show-errors')

    # Optional: user-provided post-steps (before listing)
    if extra_after:
        lines.extend(extra_after)

    # Final listing
    if filtered_listing:
        # escape any double quotes in the regex
        pattern = (list_filter_regex or "").replace('"', r"\"")
        if pattern:
            lines += [
                'echo "[info] final destination listing (filtered):"',
                f'ls -lah "$DEST" | grep -E "{pattern}" || true',
            ]
        else:
            # if no pattern, just avoid huge output
            lines += [
                'echo "[info] final destination listing (tail):"',
                'ls -lah "$DEST" | tail -n 200 || true',
            ]
    else:
        lines += ['echo "[info] final destination listing:"', 'ls -lah "$DEST" || true']

    return lines

def send_inject_command(
    *,
    instance_id: str,
    bucket: str,
    root: str,
    key_prefix: str,
    files: list[str],
    region: str = "us-east-1",
    run_as_user: str | None = "lawson",
    use_login_shell: bool = False,
    # NEW: pass-through knobs for builder
    dest: str = "/opt/infor/landmark/tmp",
    ensure_dest_exists: bool = True,
    preclear_names: list[str] | None = None,
    filtered_listing: bool = True,
    list_filter_regex: str | None = None, # r"Install-.*\.jar|mt[_]dependencies\.txt",
    extra_before: list[str] | None = None,
    extra_after: list[str] | None = None
) -> str:
    lines = build_inject_lines(
        bucket=bucket,
        root=root,
        key_prefix=key_prefix,
        files=files,
        dest=dest,
        ensure_dest_exists=ensure_dest_exists,
        preclear_names=preclear_names,
        filtered_listing=filtered_listing,
        list_filter_regex=list_filter_regex,
        extra_before=extra_before,
        extra_after=extra_after
    )
    return ssm_run_shell(
        instance_ids=[instance_id],
        lines=lines,
        region=region,
        run_as_user=run_as_user,
        use_login_shell=use_login_shell,
        comment=f"Inject builds to {instance_id} from s3://{bucket}/{root}{key_prefix}",
    )
