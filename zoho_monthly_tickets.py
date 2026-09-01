#!/usr/bin/env python3
"""Create monthly Zoho Desk tickets and notify Telegram."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "tickets.config.json"
DEFAULT_ENV = ROOT / ".env"
DEFAULT_STATE = ROOT / ".zoho_monthly_tickets_state.json"


REQUIRED_ENV = (
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'").strip("<>")
        os.environ[key] = value


def require_env() -> dict[str, str]:
    missing = [key for key in REQUIRED_ENV if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    return {key: os.environ[key] for key in REQUIRED_ENV}


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_state(state_path: Path) -> dict[str, object]:
    if not state_path.exists():
        return {}
    state = read_json(state_path)
    return state if isinstance(state, dict) else {}


def write_state(state_path: Path, state: dict[str, object]) -> None:
    write_json(state_path, state)


def request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: object | None = None,
    timeout: int = 45,
) -> object:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        safe_url = url
        if "api.telegram.org/bot" in safe_url:
            prefix, suffix = safe_url.split("/bot", 1)
            endpoint = suffix.split("/", 1)[1] if "/" in suffix else ""
            safe_url = f"{prefix}/bot<redacted>/{endpoint}"
        raise RuntimeError(f"{method} {safe_url} failed with HTTP {exc.code}: {detail}") from exc


def post_form(url: str, form: dict[str, str], timeout: int = 45) -> object:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed with HTTP {exc.code}: {detail}") from exc


def get_zoho_access_token(env: dict[str, str]) -> str:
    accounts_base = os.environ.get("ZOHO_ACCOUNTS_BASE", "https://accounts.zoho.in").rstrip("/")
    result = post_form(
        f"{accounts_base}/oauth/v2/token",
        {
            "refresh_token": env["ZOHO_REFRESH_TOKEN"],
            "client_id": env["ZOHO_CLIENT_ID"],
            "client_secret": env["ZOHO_CLIENT_SECRET"],
            "grant_type": "refresh_token",
        },
    )
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        raise RuntimeError(f"Zoho token response did not include access_token: {result}")
    return str(token)


def normalize_tickets(config: object, today: dt.date, include_due: bool = True) -> list[dict[str, object]]:
    if not isinstance(config, dict):
        raise RuntimeError("Config must be a JSON object.")
    tickets = config.get("tickets")
    if not isinstance(tickets, list) or not tickets:
        raise RuntimeError("Config must contain a non-empty 'tickets' array.")

    normalized: list[dict[str, object]] = []
    for index, item in enumerate(tickets, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Ticket #{index} must be an object.")
        run_day = int(item.get("run_day_of_month", 1))
        if include_due:
            if run_day > today.day:
                continue
        elif run_day != today.day:
            continue
        for field in ("departmentId",):
            if not item.get(field):
                raise RuntimeError(f"Ticket #{index} is missing required field '{field}'.")
        if not item.get("subject") and not item.get("subject_template"):
            raise RuntimeError(f"Ticket #{index} is missing required field 'subject' or 'subject_template'.")
        if not item.get("contactId") and not item.get("email"):
            raise RuntimeError(f"Ticket #{index} must include either 'contactId' or 'email'.")
        normalized.append(render_ticket(item, today))
    return normalized


def render_ticket(ticket: dict[str, object], today: dt.date) -> dict[str, object]:
    ticket = dict(ticket)
    first_of_month = today.replace(day=1)
    last_month_date = first_of_month - dt.timedelta(days=1)
    tat_day = ticket.pop("tat_day_of_current_month", None)
    tat_date = today.replace(day=int(tat_day)).isoformat() if tat_day is not None else ""
    context = {
        "current_month_name": today.strftime("%B"),
        "current_year": str(today.year),
        "current_year_short": today.strftime("%y"),
        "last_month_name": last_month_date.strftime("%B"),
        "last_month_year": str(last_month_date.year),
        "last_month_year_short": last_month_date.strftime("%y"),
        "tat_date": tat_date,
    }

    rendered: dict[str, object] = {}
    for key, value in ticket.items():
        if key.endswith("_template"):
            rendered[key.removesuffix("_template")] = render_value(value, context)
        elif key in {"ticket_key", "run_day_of_month"}:
            continue
        elif key == "cf" and isinstance(value, dict):
            rendered_cf = {
                str(cf_key): render_value(cf_value, context)
                for cf_key, cf_value in value.items()
                if render_value(cf_value, context) not in ("", None)
            }
            if rendered_cf:
                rendered[key] = rendered_cf
        else:
            rendered[key] = render_value(value, context)
    return rendered


def render_value(value: object, context: dict[str, str]) -> object:
    if isinstance(value, str):
        return value.format(**context)
    if isinstance(value, list):
        return [render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, context) for key, item in value.items()}
    return value


def month_key(today: dt.date) -> str:
    return today.strftime("%Y-%m")


def config_hash(config_path: Path) -> str:
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


def already_completed(state_path: Path, key: str, digest: str) -> bool:
    if not state_path.exists():
        return False
    state = read_json(state_path)
    if not isinstance(state, dict):
        return False
    month_state = state.get(key)
    return isinstance(month_state, dict) and month_state.get("config_sha256") == digest


def save_completed(state_path: Path, key: str, digest: str, created: list[dict[str, str]]) -> None:
    state = read_state(state_path)
    existing_created: list[dict[str, str]] = []
    existing_month = state.get(key)
    if isinstance(existing_month, dict) and isinstance(existing_month.get("created"), list):
        existing_created = [
            item
            for item in existing_month["created"]
            if isinstance(item, dict)
        ]
    seen = {
        str(item.get("id") or item.get("ticketNumber") or item.get("subject"))
        for item in existing_created
    }
    merged_created = list(existing_created)
    for item in created:
        item_key = str(item.get("id") or item.get("ticketNumber") or item.get("subject"))
        if item_key not in seen:
            merged_created.append(item)
            seen.add(item_key)
    state[key] = {
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config_sha256": digest,
        "created": merged_created,
    }
    write_state(state_path, state)


def ticket_state_key(ticket: dict[str, object], today: dt.date) -> str:
    raw_key = str(ticket.get("ticket_key") or ticket.get("subject") or ticket.get("subject_template"))
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]
    return f"{today:%Y-%m}:{digest}"


def completed_for_ticket(state_path: Path, key: str, subject: str, today: dt.date) -> bool:
    if not state_path.exists():
        return False
    state = read_json(state_path)
    if not isinstance(state, dict):
        return False
    tickets_state = state.get("tickets")
    if isinstance(tickets_state, dict) and key in tickets_state:
        return True

    legacy_month_state = state.get(month_key(today))
    if isinstance(legacy_month_state, dict):
        created = legacy_month_state.get("created")
        if isinstance(created, list):
            for item in created:
                if isinstance(item, dict) and item.get("subject") == subject:
                    return True
    return False


def save_ticket_completed(state_path: Path, key: str, created: dict[str, str]) -> None:
    state = read_state(state_path)
    tickets_state = state.setdefault("tickets", {})
    if not isinstance(tickets_state, dict):
        tickets_state = {}
        state["tickets"] = tickets_state
    tickets_state[key] = {
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "created": created,
    }
    write_state(state_path, state)


def add_pending_notification(state_path: Path, message: str, error: str) -> None:
    state = read_state(state_path)
    pending = state.setdefault("pending_telegram_notifications", [])
    if not isinstance(pending, list):
        pending = []
        state["pending_telegram_notifications"] = pending
    pending.append(
        {
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "message": message,
            "last_error": error,
        }
    )
    write_state(state_path, state)


def retry_pending_notifications(state_path: Path, env: dict[str, str]) -> None:
    state = read_state(state_path)
    pending = state.get("pending_telegram_notifications")
    if not isinstance(pending, list) or not pending:
        return

    remaining: list[object] = []
    for item in pending:
        if not isinstance(item, dict) or not item.get("message"):
            continue
        try:
            send_telegram(env, str(item["message"]))
            print("Sent pending Telegram notification.")
        except Exception as exc:
            item["last_error"] = str(exc)
            item["last_attempt_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            remaining.append(item)

    if remaining:
        state["pending_telegram_notifications"] = remaining
    else:
        state.pop("pending_telegram_notifications", None)
    write_state(state_path, state)


def create_ticket(ticket: dict[str, object], access_token: str, org_id: str | None = None) -> dict[str, str]:
    desk_base = os.environ.get("ZOHO_DESK_API_BASE", "https://desk.zoho.in/api/v1").rstrip("/")
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
    }
    if org_id and not org_id.startswith("replace_with_"):
        headers["orgId"] = org_id
    result = request_json("POST", f"{desk_base}/tickets", headers=headers, body=ticket)
    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected Zoho ticket response: {result}")
    return {
        "id": str(result.get("id", "")),
        "ticketNumber": str(result.get("ticketNumber", "")),
        "subject": str(result.get("subject", ticket.get("subject", ""))),
    }


def send_telegram(env: dict[str, str], message: str) -> None:
    bot_token = env["TELEGRAM_BOT_TOKEN"]
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    request_json(
        "POST",
        url,
        body={
            "chat_id": env["TELEGRAM_CHAT_ID"],
            "text": message,
            "disable_web_page_preview": True,
        },
    )


def send_telegram_with_retries(env: dict[str, str], message: str, attempts: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            send_telegram(env, message)
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Telegram notification failed after {attempts} attempts: {last_error}")


def build_message(created: list[dict[str, str]], dry_run: bool) -> str:
    prefix = "DRY RUN: " if dry_run else ""
    if not created:
        return prefix + "No Zoho Desk tickets were created."
    lines = [f"{prefix}Zoho Desk monthly tickets created: {len(created)}"]
    for ticket in created:
        number = ticket.get("ticketNumber") or ticket.get("id") or "unknown"
        lines.append(f"- {number}: {ticket.get('subject', '')}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--today", type=dt.date.fromisoformat, help="Override today's date for testing, YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Run even if this month is already completed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env(args.env_file)

    if not args.config.exists():
        raise RuntimeError(f"Config file not found: {args.config}")

    digest = config_hash(args.config)

    today = args.today or dt.date.today()
    tickets = normalize_tickets(read_json(args.config), today)
    if not tickets:
        print("No tickets are scheduled for today.")
        return 0

    created: list[dict[str, str]] = []
    if args.dry_run:
        created = [
            {"id": f"dry-run-{index}", "ticketNumber": f"DRY-{index}", "subject": str(ticket["subject"])}
            for index, ticket in enumerate(tickets, start=1)
        ]
    else:
        env = require_env()
        retry_pending_notifications(args.state, env)
        access_token = get_zoho_access_token(env)
        org_id = os.environ.get("ZOHO_ORG_ID")
        for ticket in tickets:
            ticket_key = ticket_state_key(ticket, today)
            subject = str(ticket.get("subject", ""))
            if not args.force and completed_for_ticket(args.state, ticket_key, subject, today):
                print(f"Already completed this month: {subject}")
                continue
            created_ticket = create_ticket(ticket, access_token, org_id)
            created.append(created_ticket)
            save_ticket_completed(args.state, ticket_key, created_ticket)
            time.sleep(0.5)
        if created:
            save_completed(args.state, month_key(today), digest, created)

    message = build_message(created, args.dry_run)
    print(message)
    if not args.dry_run and created:
        try:
            send_telegram_with_retries(env, message)
        except Exception as exc:
            add_pending_notification(args.state, message, str(exc))
            raise
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
