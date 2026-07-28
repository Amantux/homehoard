"""Miscellaneous endpoints: status, currency, qrcode, actions, reporting, import/export."""
import io
import os
import tempfile
import time

from flask import Blueprint, request, jsonify, Response, send_file, current_app, g
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..extensions import db, limiter
from ..models import Group, Item
from ..auth import login_required, owner_required, current_group
from ..services.csv_io import export_items, import_items

bp = Blueprint("misc", __name__)

CURRENCIES = [
    {"code": "usd", "name": "United States Dollar", "symbol": "$", "local": "en-US"},
    {"code": "eur", "name": "Euro", "symbol": "€", "local": "de-DE"},
    {"code": "gbp", "name": "British Pound", "symbol": "£", "local": "en-GB"},
    {"code": "jpy", "name": "Japanese Yen", "symbol": "¥", "local": "ja-JP"},
    {"code": "cad", "name": "Canadian Dollar", "symbol": "$", "local": "en-CA"},
    {"code": "aud", "name": "Australian Dollar", "symbol": "$", "local": "en-AU"},
    {"code": "chf", "name": "Swiss Franc", "symbol": "Fr", "local": "de-CH"},
    {"code": "inr", "name": "Indian Rupee", "symbol": "₹", "local": "en-IN"},
    {"code": "sek", "name": "Swedish Krona", "symbol": "kr", "local": "sv-SE"},
]


@bp.get("/status")
def status():
    """Liveness: the process is up and serving. Cheap, no dependency access."""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    return jsonify(
        {
            "health": True,
            "versions": ["v1"],
            "title": "HomeHoard",
            "message": "HomeHoard — homebox port running on Flask",
            # Storage backend in use — drives the "Migrate to PostgreSQL" action.
            "dbBackend": "sqlite" if uri.startswith("sqlite") else "postgresql",
        }
    )


@bp.get("/ready")
def ready():
    """Readiness: dependencies are actually usable (DB reachable, data dir
    writable). Distinct from /status (liveness) so an orchestrator/healthcheck
    can tell 'process running' from 'able to serve requests'. Returns 503 when a
    dependency is down; body reports each check as ok/error (no internals)."""
    checks = {}
    ok = True

    started = time.monotonic()
    try:
        db.session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - readiness must never leak a stack trace
        checks["database"] = "error"
        ok = False
    checks["dbLatencyMs"] = round((time.monotonic() - started) * 1000, 1)

    try:
        d = current_app.config["attachments_dir"]()
        # Unique probe file so concurrent readiness checks (2 workers) can't
        # race to remove a shared name. Still exercises write + free-space.
        fd, probe = tempfile.mkstemp(prefix=".readycheck-", dir=d)
        try:
            os.write(fd, b"ok")
        finally:
            os.close(fd)
            os.remove(probe)
        checks["storage"] = "ok"
    except Exception:  # noqa: BLE001
        checks["storage"] = "error"
        ok = False

    return jsonify({"ready": ok, "checks": checks}), (200 if ok else 503)


@bp.get("/diagnostics")
@login_required
def diagnostics():
    """Coarse, non-sensitive runtime facts for a user-initiated bug report.

    Login-gated so it doesn't reveal AI-configured state to anonymous callers, and
    deliberately returns only publishable facts — never secrets (API keys, provider
    base URLs, the DB URL) or any inventory content — because the report they seed
    becomes a PUBLIC GitHub issue."""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    try:
        from ..services.ai import provider_config
        provider = provider_config.effective().AI_PROVIDER or "none"
    except Exception:  # noqa: BLE001 - diagnostics must never 500
        provider = "unknown"
    return jsonify(
        {
            "app": "HomeHoard",
            "dbBackend": "sqlite" if uri.startswith("sqlite") else "postgresql",
            "aiProvider": provider,
            "mcpEnabled": os.environ.get("HBOX_MCP_ENABLED", "true").lower() == "true",
            "authDisabled": bool(current_app.config.get("DISABLE_AUTH")),
        }
    )


@bp.get("/settings/chat")
@login_required
def get_chat_settings():
    """The household default for streaming chat responses. Any member can read it
    (the client also honours a per-browser override); only the owner sets it."""
    from ..services.settings_store import get_overrides
    val = (get_overrides().get("chat_streaming") or "").strip().lower()
    return jsonify({"stream": val == "true"})


@bp.put("/settings/chat")
@owner_required
def put_chat_settings():
    from ..services.settings_store import set_values
    data = request.get_json(force=True) or {}
    stream = bool(data.get("stream"))
    set_values({"chat_streaming": "true" if stream else "false"})
    return jsonify({"stream": stream})


@bp.get("/settings/ai/jobs")
@owner_required
def get_ai_job_settings():
    """The async-job AI preference: a provider+model default for background work,
    separate from chat. `enrich` = enrichment jobs; `organize` = categorize +
    cluster. Blank provider = same as the chat provider. Instance-admin only."""
    denied = _instance_admin_or_403()
    if denied:
        return denied
    from ..services.settings_store import get_overrides
    o = get_overrides()
    return jsonify({
        "enrich": {"provider": o.get("enrich_provider", ""), "model": o.get("enrich_model", "")},
        "organize": {"provider": o.get("organize_provider", ""), "model": o.get("organize_model", "")},
    })


@bp.put("/settings/ai/jobs")
@owner_required
def put_ai_job_settings():
    """Set the async-job AI preference. Body: {enrich:{provider,model},
    organize:{provider,model}}. A blank provider means 'same as chat'.
    Instance-admin only."""
    denied = _instance_admin_or_403()
    if denied:
        return denied
    from ..services.ai import provider_config
    from ..services.settings_store import set_values, get_overrides

    data = request.get_json(force=True) or {}
    pairs: dict[str, str] = {}
    for area in ("enrich", "organize"):
        blk = data.get(area)
        if not isinstance(blk, dict):
            continue
        if "provider" in blk:
            prov = str(blk.get("provider") or "")
            if prov and prov not in provider_config.VALID_PROVIDERS:
                return jsonify({"error": f"unknown provider '{prov}'"}), 422
            pairs[f"{area}_provider"] = prov
        if "model" in blk:
            pairs[f"{area}_model"] = str(blk.get("model") or "")[:100]
    if pairs:
        set_values(pairs)
    o = get_overrides()
    return jsonify({
        "enrich": {"provider": o.get("enrich_provider", ""), "model": o.get("enrich_model", "")},
        "organize": {"provider": o.get("organize_provider", ""), "model": o.get("organize_model", "")},
    })


@bp.get("/currency")
def currency():
    return jsonify(CURRENCIES)


def _instance_admin_or_403():
    """The AI-provider config is instance-wide infrastructure — it overrides the HA
    add-on options and drives outbound calls (Ollama URL, hosted-search key) shared by
    every household. `owner_required` only proves ownership of the caller's OWN group,
    so it would let any self-registered household's owner repoint that shared backend
    (SSRF / cross-tenant leakage). Restrict to the founding household's owner — the
    lowest-id group, which in the normal single-household add-on is simply the owner.
    Returns a 403 response tuple when the caller isn't that admin, else None."""
    # Group ids are random UUIDs, so "founding" is the earliest-created group
    # (id as a stable tiebreaker), not the lexicographically-smallest id.
    founding = (
        db.session.query(Group.id)
        .order_by(Group.created_at.asc(), Group.id.asc())
        .first()
    )
    if founding is None or g.current_user.group_id != founding[0]:
        return jsonify({"error": "instance admin privileges required"}), 403
    return None


@bp.get("/settings/ai")
@owner_required
def get_ai_settings():
    """Redacted view of the effective AI-provider config: active provider, its
    base URL / model, whether a key + the web-search key are set, and the provider
    list. No secret values. Instance-admin only."""
    denied = _instance_admin_or_403()
    if denied:
        return denied
    from ..services.ai import provider_config
    from ..services.ai.registry import list_providers

    return jsonify({**provider_config.settings_view(), "providers": list_providers()})


@bp.put("/settings/ai")
@owner_required
def put_ai_settings():
    """Set the AI-provider overrides (provider / base URL / model / API key) plus the
    Ollama web-search key. A blank API key is left unchanged (doesn't clobber a saved
    one). The base URL is SSRF-guarded. Instance-admin only."""
    denied = _instance_admin_or_403()
    if denied:
        return denied
    from ..services.ai import provider_config
    from ..services.ai.url_guard import llm_url_ok

    data = request.get_json(force=True) or {}
    provider = data.get("provider")
    if provider is not None and str(provider) not in provider_config.VALID_PROVIDERS:
        return jsonify({"error": f"unknown provider '{provider}'"}), 422
    base_url = data.get("baseUrl")
    if base_url:
        ok, err = llm_url_ok(str(base_url))
        if not ok:
            return jsonify({"error": err}), 422
    provider_config.set_overrides(
        provider=str(provider) if provider is not None else None,
        base_url=str(base_url) if base_url is not None else None,
        model=str(data["model"]) if "model" in data else None,
        api_key=str(data["apiKey"]) if data.get("apiKey") else None,
        search_key=str(data["ollamaSearchKey"]) if data.get("ollamaSearchKey") else None,
        clear_api_key=bool(data.get("clearApiKey")),
    )
    from ..services.ai.registry import list_providers
    return jsonify({**provider_config.settings_view(), "providers": list_providers()})


@bp.get("/settings/ai/providers")
@owner_required
def get_ai_providers():
    """The provider list with availability + which is active. Instance-admin only."""
    denied = _instance_admin_or_403()
    if denied:
        return denied
    from ..services.ai.registry import list_providers
    return jsonify({"providers": list_providers()})


@bp.post("/settings/ai/models")
@owner_required
def probe_ai_models():
    """Live model list for the picker, using the values currently in the form
    (provider/base URL/key) — falls back to the saved/env config. Instance-admin only."""
    denied = _instance_admin_or_403()
    if denied:
        return denied
    from ..services.ai import provider_config
    from ..services.ai.url_guard import llm_url_ok

    data = request.get_json(silent=True) or {}
    base_url = data.get("baseUrl")
    if base_url:
        ok, err = llm_url_ok(str(base_url))
        if not ok:
            return jsonify({"error": err}), 422
    eff = provider_config.probe_config(
        provider=data.get("provider"), base_url=base_url, api_key=data.get("apiKey"))
    return jsonify({"models": provider_config.list_models(eff)})


@bp.get("/qrcode")
@login_required
def qrcode_gen():
    import qrcode

    data = request.args.get("data", "")
    if len(data) > 1024:  # bound CPU/image size (QR practical limit is ~3KB)
        return jsonify({"error": "data too long"}), 422
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# --- Import / Export -----------------------------------------------------
@bp.get("/items/export")
@login_required
def export():
    csv_text = export_items(current_group().id)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=homehoard.csv"},
    )


@bp.post("/items/import")
@login_required
@limiter.limit("6 per minute")
def do_import():
    file = request.files.get("csv") or request.files.get("file")
    if file:
        text = file.read().decode("utf-8-sig")
    else:
        text = (request.get_json(silent=True) or {}).get("data", "")
    if not text:
        return jsonify({"error": "no csv data"}), 422
    count = import_items(current_group().id, text)
    return jsonify({"imported": count}), 201


# --- Reporting -----------------------------------------------------------
@bp.get("/reporting/bill-of-materials")
@login_required
def bill_of_materials():
    csv_text = export_items(current_group().id)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=bom.csv"},
    )


# --- Actions (maintenance/cleanup helpers) -------------------------------
@bp.post("/actions/ensure-asset-ids")
@login_required
def ensure_asset_ids():
    items = (
        db.session.query(Item)
        .filter_by(group_id=current_group().id)
        .order_by(Item.created_at.asc())
        .all()
    )
    next_id = 1
    completed = 0
    used = {i.asset_id for i in items if i.asset_id}
    for i in items:
        if not i.asset_id:
            while next_id in used:
                next_id += 1
            i.asset_id = next_id
            used.add(next_id)
            completed += 1
    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent create grabbed one of these ids first (the partial unique
        # index caught it). Roll back and report a retryable conflict rather than 500.
        db.session.rollback()
        return jsonify({"error": "asset ids changed concurrently, please retry"}), 409
    return jsonify({"completed": completed})


@bp.post("/actions/ensure-import-refs")
@login_required
def ensure_import_refs():
    import uuid

    items = db.session.query(Item).filter_by(group_id=current_group().id).all()
    completed = 0
    for i in items:
        if not i.import_ref:
            i.import_ref = uuid.uuid4().hex[:8]
            completed += 1
    db.session.commit()
    return jsonify({"completed": completed})


@bp.post("/actions/zero-item-time-fields")
@login_required
def zero_time_fields():
    items = db.session.query(Item).filter_by(group_id=current_group().id).all()
    completed = 0
    for i in items:
        for attr in ("purchase_date", "sold_date", "warranty_expires"):
            val = getattr(i, attr)
            if val and (val.hour or val.minute or val.second):
                setattr(i, attr, val.replace(hour=0, minute=0, second=0, microsecond=0))
                completed += 1
    db.session.commit()
    return jsonify({"completed": completed})


@bp.post("/actions/set-primary-photos")
@login_required
def set_primary_photos():
    items = db.session.query(Item).filter_by(group_id=current_group().id).all()
    completed = 0
    for i in items:
        photos = [a for a in i.attachments if a.type == "photo"]
        if photos and not any(a.primary for a in photos):
            photos[0].primary = True
            completed += 1
    db.session.commit()
    return jsonify({"completed": completed})


# --- Assets --------------------------------------------------------------
@bp.get("/assets/<asset_id>")
@login_required
def get_by_asset(asset_id):
    from ..schemas.serializers import item_summary

    # Accept "000-001" or raw integer
    try:
        if "-" in asset_id:
            hi, lo = asset_id.split("-")
            num = int(hi) * 1000 + int(lo)
        else:
            num = int(asset_id)
    except ValueError:
        return jsonify({"error": "invalid asset id"}), 422
    items = (
        db.session.query(Item)
        .filter_by(group_id=current_group().id, asset_id=num)
        .all()
    )
    return jsonify(
        {"items": [item_summary(i) for i in items], "total": len(items)}
    )


@bp.post("/migrate/postgres")
@owner_required
def migrate_postgres():
    """Copy the whole SQLite database into an EMPTY PostgreSQL target, then the
    operator sets HBOX_DATABASE_URL + restarts to run on it. Owner-only; never
    touches the SQLite source."""
    from ..services.db_copy import (DbCopyError, TargetNotEmpty,
                                    migrate_sqlite_to_postgres)

    source = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not source.startswith("sqlite"):
        return jsonify({"error": "HomeHoard is already running on an external database."}), 400
    target = ((request.get_json(silent=True) or {}).get("targetUrl") or "").strip()
    if not target:
        return jsonify({"error": "targetUrl is required"}), 400
    try:
        report = migrate_sqlite_to_postgres(source, target)
    except TargetNotEmpty as e:
        return jsonify({"error": str(e)}), 409
    except DbCopyError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001 — surface connection/other failures to the user
        return jsonify({"error": f"Migration failed: {e}"}), 400
    report["next"] = ("Data copied. Set HBOX_DATABASE_URL to this Postgres URL and "
                      "restart HomeHoard to run on it.")
    return jsonify(report)
