"""Postgres-backed, Motor-compatible data layer for the Bangla Basket backend.

This module replaces ``motor`` (MongoDB) with ``asyncpg`` (Postgres) WITHOUT
changing any route handler, serializer, or API response shape.  Each Mongo
collection becomes one Postgres table::

    <collection> ( <pk columns...>, seq BIGSERIAL, doc JSONB NOT NULL )

* ``doc`` holds the FULL document exactly as Mongo would have stored it
  (same keys, same nesting, same explicit nulls, same absent-vs-null
  distinction).  Reads return ``doc`` itself, so response shapes are
  byte-identical to the Mongo version -- including fields that are absent
  rather than null (``$unset`` really removes the key).
* Primary-key columns mirror the business IDs the API exposes
  (``order_id``, ``user_id``, ``item_id``, ...).  They exist so uniqueness
  and the partial-unique users-email index can be enforced by Postgres.
  ``points_ledger`` has no business ID, so it gets a surrogate ``ledger_id``.
* ``seq`` is a monotonically increasing insertion sequence.  Mongo's
  ``find_one`` / ``update_one`` / ``delete_one`` act on the *first* matching
  document in insertion order; ``ORDER BY seq LIMIT 1`` reproduces that.
* Datetimes are stored in ``doc`` as ISO-8601 strings (JSON has no datetime
  type) and converted back to timezone-aware ``datetime`` objects on read
  for the per-table datetime fields listed in :data:`TABLES`.  This matches
  what the old code saw from Mongo (real datetimes) for every field the
  code compares, adds to, or calls ``.isoformat()`` on.  Fields the code
  stores as strings (weekly-menu ``created_at``, tracking-event ``ts``,
  integration ``last_test_at``) stay strings, exactly as before.
* No per-request transactions are introduced in this pass: every Motor
  call maps to one Postgres statement (or, for ``update_one`` /
  ``delete_one`` / ``find_one_and_update``, a locate-then-act pair), which
  preserves the old observable behaviour, including exact
  ``matched_count`` vs ``modified_count`` semantics.

Only the Motor surface actually used by ``server.py`` is implemented:
``find_one``, ``find`` (+ ``sort``/``limit``/``skip``/``to_list``/async-for),
``insert_one``, ``update_one``/``update_many`` (``$set``/``$inc``/``$push``/
``$unset``/``$pull``, dotted paths, positional ``$``), ``delete_one``/
``delete_many``, ``count_documents``, ``aggregate`` (``$match``/``$sort``/
``$group`` with ``$sum``/``$first``), ``find_one_and_update``,
``replace_one``, ``create_index``/``index_information``/``drop_index``.
Anything outside that surface raises loudly instead of silently
misbehaving.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date, datetime, timezone

import asyncpg

# ---------------------------------------------------------------------------
# Table configuration: collection -> (primary-key fields, datetime fields)
# ---------------------------------------------------------------------------
# Datetime fields are the top-level fields the code stores as real datetimes
# (Pydantic ``datetime`` model fields, or direct ``datetime.now(timezone.utc)``
# assignments).  They are converted ISO-string -> datetime on read.  Every
# other field keeps whatever JSON type it was written with.
TABLES = {
    "admins": (["email"], ["created_at"]),
    "analytics_events": ([], ["ts"]),  # surrogate PK column: ledger_id
    "business_settings": (["key"], []),
    "catering_packages": (["package_id"], []),
    "catering_quote_requests": (["request_id"], ["created_at"]),
    "coupons": (["code"], ["created_at"]),
    "coupon_redemptions": (["code", "user_id", "order_id"], ["ts"]),
    "delivery_applications": (["app_id"], ["created_at"]),
    "delivery_partners": (
        ["partner_id"],
        ["created_at", "updated_at", "current_location_updated_at",
         "journey_started_at", "journey_ended_at"],
    ),
    "export_files": (["token"], ["created_at", "expires_at"]),
    "grocery": (["item_id"], ["created_at", "updated_at"]),
    "master_menu": (["item_id"], ["created_at", "updated_at"]),
    "orders": (
        ["order_id"],
        ["created_at", "updated_at", "paid_at", "route_polyline_updated_at",
         "delivery_partner_updated_at", "delivery_eta_updated_at",
         "journey_started_at"],
    ),
    "otp_challenges": (["email"], ["created_at", "expires_at"]),
    "password_resets": (["token_hash"], ["created_at", "expires_at", "used_at"]),
    "payment_transactions": (["session_id"], ["created_at"]),
    "points_ledger": ([], ["ts"]),  # surrogate PK column: ledger_id
    "pricing_zones": (["zone_id"], ["created_at", "updated_at"]),
    "push_tokens": (["user_id", "token"], ["created_at"]),
    "thali_packages": (["package_id"], ["created_at"]),
    "user_sessions": (["session_token"], ["created_at", "expires_at"]),
    "users": (["user_id"], ["created_at", "first_login_at"]),
    "weekly_menus": (["week_start"], ["created_at", "updated_at"]),
    # WhatsApp module: inbound/outbound messages for the admin inbox +
    # broadcast. message_id = Twilio MessageSid (inbound) or the returned
    # SID for outbound sends. window_expires_at = last-customer-message
    # time + 24h (the customer-service window for free-form replies).
    "whatsapp_messages": (
        ["message_id"], ["created_at", "window_expires_at"],
    ),
}

# Fields that sort numerically when they appear in a sort spec.  Everything
# else sorts as text, except per-table datetime fields (timestamptz).
NUMERIC_SORT_FIELDS = {
    "sort_order", "total_cents", "subtotal_cents", "price_cents",
    "default_price_cents", "unit_price_cents", "line_total_cents",
    "loyalty_points", "stock_used", "stock_limit", "quantity",
    "guest_count", "used_count", "per_person_price_cents",
    "delivery_fee_cents", "tax_cents", "discount_cents",
    "points_redeemed", "points_awarded", "surcharge_cents",
    "amount_cents", "delta", "count", "delivery_eta_seconds",
    "delivery_route_order", "min_order_cents",
}

_NUM_RE = r"^-?[0-9]+(\.[0-9]+)?$"
_ISO_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _dumps(doc) -> str:
    return json.dumps(doc, default=_json_default, ensure_ascii=False,
                      separators=(",", ":"))


def _loads(raw):
    if isinstance(raw, str):
        return json.loads(raw)
    return raw  # already decoded (defensive; asyncpg returns str for jsonb)


def _parse_dt(text):
    """Parse an ISO-8601 string to an aware datetime, or None if not one."""
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _convert_datetimes(doc: dict, dt_fields) -> dict:
    for field in dt_fields:
        value = doc.get(field)
        if isinstance(value, str):
            parsed = _parse_dt(value)
            if parsed is not None:
                doc[field] = parsed
    return doc


def _sql_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_str_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Motor-compatible result objects
# ---------------------------------------------------------------------------
class InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id
        self.acknowledged = True


class UpdateResult:
    def __init__(self, matched_count, modified_count, upserted_id=None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id
        self.acknowledged = True


class DeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count
        self.acknowledged = True


class ReplaceResult(UpdateResult):
    pass


# ---------------------------------------------------------------------------
# Filter -> SQL compiler (WHERE fragment on the ``doc`` JSONB column)
# ---------------------------------------------------------------------------
class _SqlBuilder:
    """Collects bound parameters; placeholders are $1, $2, ..."""

    def __init__(self):
        self.params = []

    def add(self, value):
        self.params.append(value)
        return f"${len(self.params)}"


def _text_expr(field: str, mode: str) -> str:
    """SQL text expression for a field: ``doc->>'f'`` (or ``e->>'f'``)."""
    col = "doc" if mode == "doc" else "e"
    return f"({col}->>{_sql_str_literal(field)})"


def _path_text_expr(segments, mode: str) -> str:
    col = "doc" if mode == "doc" else "e"
    path = "{" + ",".join(segments) + "}"
    return f"({col} #>> {_sql_str_literal(path)})"


def _typed_expr(field: str, value, dt_fields, mode: str) -> str:
    """Type-aware comparison expression for a field + a Python value.

    Mongo compares numbers numerically and datetimes chronologically; the
    JSONB text extraction must therefore be cast -- guarded so that a
    non-numeric / non-ISO string degrades to NULL (no match) instead of
    raising a Postgres cast error.
    """
    if "." in field:
        text = _path_text_expr(field.split("."), mode)
    else:
        text = _text_expr(field, mode)
    if isinstance(value, bool):
        return (f"(CASE WHEN {text} IN ('true','false') "
                f"THEN {text}::boolean ELSE NULL END)")
    if isinstance(value, (int, float)):
        return (f"(CASE WHEN {text} ~ {_sql_str_literal(_NUM_RE)} "
                f"THEN {text}::numeric ELSE NULL END)")
    if isinstance(value, datetime):
        return (f"(CASE WHEN {text} ~ {_sql_str_literal(_ISO_RE)} "
                f"THEN {text}::timestamptz ELSE NULL END)")
    return text


def _eq_fragment(builder: _SqlBuilder, field: str, value, dt_fields,
                 mode: str = "doc") -> str:
    if value is None:
        return f"{_text_expr(field, mode) if '.' not in field else _path_text_expr(field.split('.'), mode)} IS NULL"
    expr = _typed_expr(field, value, dt_fields, mode)
    param = builder.add(value)
    if isinstance(value, datetime):
        param = f"{param}::timestamptz"
    return f"{expr} = {param}"


def _ne_fragment(builder: _SqlBuilder, field: str, value, dt_fields,
                 mode: str = "doc") -> str:
    if value is None:
        base = (_text_expr(field, mode) if "." not in field
                else _path_text_expr(field.split("."), mode))
        return f"{base} IS NOT NULL"
    expr = _typed_expr(field, value, dt_fields, mode)
    param = builder.add(value)
    if isinstance(value, datetime):
        param = f"{param}::timestamptz"
    return f"{expr} IS DISTINCT FROM {param}"


def _cmp_fragment(builder: _SqlBuilder, field: str, op: str, value,
                  dt_fields, mode: str = "doc") -> str:
    expr = _typed_expr(field, value, dt_fields, mode)
    param = builder.add(value)
    if isinstance(value, datetime):
        param = f"{param}::timestamptz"
    return f"{expr} {op} {param}"


def _compile_ops(builder: _SqlBuilder, field: str, ops: dict, dt_fields,
                 mode: str = "doc") -> str:
    parts = []
    regex_pattern = None
    regex_options = ""
    for op, value in ops.items():
        if op == "$eq":
            parts.append(_eq_fragment(builder, field, value, dt_fields, mode))
        elif op == "$ne":
            parts.append(_ne_fragment(builder, field, value, dt_fields, mode))
        elif op == "$in":
            if not value:
                parts.append("FALSE")
            else:
                ors = [_eq_fragment(builder, field, v, dt_fields, mode)
                       for v in value]
                parts.append("(" + " OR ".join(ors) + ")")
        elif op == "$nin":
            ands = [_ne_fragment(builder, field, v, dt_fields, mode)
                    for v in value]
            parts.append("(" + " AND ".join(ands) + ")" if ands else "TRUE")
        elif op in ("$gt", "$gte", "$lt", "$lte"):
            parts.append(_cmp_fragment(builder, field,
                                      {"$gt": ">", "$gte": ">=",
                                       "$lt": "<", "$lte": "<="}[op],
                                      value, dt_fields, mode))
        elif op == "$regex":
            regex_pattern = value
        elif op == "$options":
            regex_options = value or ""
        elif op == "$exists":
            base = (_text_expr(field, mode) if "." not in field
                    else _path_text_expr(field.split("."), mode))
            if mode == "doc" and "." not in field:
                exists = f"(doc ? {builder.add(field)})"
            else:
                exists = f"{base} IS NOT NULL"
            parts.append(exists if value else f"NOT ({exists})")
        elif op == "$elemMatch":
            if not isinstance(value, dict):
                raise NotImplementedError("$elemMatch needs a dict")
            sub = _compile_filter(builder, value, dt_fields, mode="elem")
            parts.append(
                f"EXISTS (SELECT 1 FROM jsonb_array_elements(doc->"
                f"{_sql_str_literal(field)}) AS e WHERE {sub})")
        else:
            raise NotImplementedError(f"unsupported filter operator: {op}")
    if regex_pattern is not None:
        if isinstance(regex_pattern, re.Pattern):
            pattern = regex_pattern.pattern
            insensitive = bool(regex_pattern.flags & re.IGNORECASE)
        else:
            pattern = str(regex_pattern)
            insensitive = "i" in regex_options
        text = (_text_expr(field, mode) if "." not in field
                else _path_text_expr(field.split("."), mode))
        oper = "~*" if insensitive else "~"
        parts.append(f"{text} {oper} {builder.add(pattern)}")
    return "(" + " AND ".join(parts) + ")" if parts else "TRUE"


def _dotted_array_fragment(builder: _SqlBuilder, segments, value,
                           dt_fields) -> str:
    """``{"items.item_id": X}`` -> some array element matches.

    Two-segment dotted filters in this codebase always mean "an element of
    the array has this field".  (Object-nested dotted paths appear only in
    ``$set`` updates, never in filters.)
    """
    arr, sub = segments[0], segments[1]
    if isinstance(value, dict) and any(k.startswith("$") for k in value):
        cond = _compile_ops(builder, sub, value, dt_fields, mode="elem")
    else:
        cond = _eq_fragment(builder, sub, value, dt_fields, mode="elem")
    return (f"EXISTS (SELECT 1 FROM jsonb_array_elements(doc->"
            f"{_sql_str_literal(arr)}) AS e WHERE {cond})")


def _compile_filter(builder: _SqlBuilder, filt: dict, dt_fields,
                    mode: str = "doc") -> str:
    if not filt:
        return "TRUE"
    parts = []
    for key, value in filt.items():
        if key in ("$and", "$or"):
            joiner = " AND " if key == "$and" else " OR "
            subs = [_compile_filter(builder, sub, dt_fields, mode)
                    for sub in value]
            parts.append("(" + joiner.join(subs) + ")")
        elif key.startswith("$"):
            raise NotImplementedError(f"unsupported top-level operator: {key}")
        elif mode == "elem" and "." in key:
            raise NotImplementedError("dotted keys inside $elemMatch")
        elif "." in key:
            segments = key.split(".")
            if len(segments) == 2 and mode == "doc":
                parts.append(_dotted_array_fragment(builder, segments, value,
                                                    dt_fields))
            else:
                if isinstance(value, dict) and any(
                        k.startswith("$") for k in value):
                    parts.append(_compile_ops(builder, key, value, dt_fields,
                                              mode))
                elif isinstance(value, dict):
                    parts.append(
                        f"({_path_text_expr(segments, mode)} = "
                        f"{builder.add(_dumps(value))}::jsonb)")
                else:
                    parts.append(_eq_fragment(builder, key, value, dt_fields,
                                              mode))
        elif isinstance(value, dict) and any(k.startswith("$")
                                             for k in value):
            parts.append(_compile_ops(builder, key, value, dt_fields, mode))
        elif isinstance(value, dict):
            # Whole-subdocument equality (unused by current code, but cheap).
            parts.append(f"(doc->>{_sql_str_literal(key)}) = "
                         f"{builder.add(_dumps(value))}::jsonb")
        else:
            parts.append(_eq_fragment(builder, key, value, dt_fields, mode))
    return "(" + " AND ".join(parts) + ")"


def _compile_sort(spec, dt_fields) -> str:
    """Motor sort spec -> ORDER BY fragment (Mongo null ordering)."""
    if spec is None:
        return ""
    if isinstance(spec, str):
        pairs = [(spec, 1)]
    elif isinstance(spec, tuple):
        pairs = [spec]
    else:
        pairs = list(spec)
    clauses = []
    for field, direction in pairs:
        if field in dt_fields:
            text = _text_expr(field, "doc")
            expr = (f"(CASE WHEN {text} ~ {_sql_str_literal(_ISO_RE)} "
                    f"THEN {text}::timestamptz ELSE NULL END)")
        elif field in NUMERIC_SORT_FIELDS:
            text = _text_expr(field, "doc")
            expr = (f"(CASE WHEN {text} ~ {_sql_str_literal(_NUM_RE)} "
                    f"THEN {text}::numeric ELSE NULL END)")
        elif "." in field:
            expr = _path_text_expr(field.split("."), "doc")
        else:
            expr = _text_expr(field, "doc")
        # Mongo sorts null/missing FIRST ascending, LAST descending.
        order = "ASC NULLS FIRST" if direction >= 0 else "DESC NULLS LAST"
        clauses.append(f"{expr} {order}")
    return "ORDER BY " + ", ".join(clauses) if clauses else ""


def _apply_projection(doc: dict, projection, filt) -> dict:
    """Apply a Motor projection to an already-decoded document."""
    if not projection:
        return dict(doc)
    if set(projection) == {"_id"} and projection.get("_id") == 0:
        out = dict(doc)
        out.pop("_id", None)
        return out
    inclusion = {k for k, v in projection.items() if v == 1}
    exclusion = {k for k, v in projection.items() if v == 0}
    if exclusion - {"_id"}:
        raise NotImplementedError(
            f"exclusion projection not supported: {sorted(exclusion)}")
    out = {}
    for key in inclusion:
        if key.endswith(".$"):
            arr = key[:-2]
            # Reduce the array to elements matching the filter's dotted key
            # (e.g. filter {"items.item_id": X} + projection {"items.$": 1}
            # keeps only the matching item).
            match_field, match_value = None, None
            for fk, fv in (filt or {}).items():
                if fk.startswith(arr + "."):
                    match_field = fk.split(".", 1)[1]
                    match_value = (fv.get("$eq") if isinstance(fv, dict)
                                   else fv)
            elements = doc.get(arr) or []
            if match_field is not None:
                elements = [e for e in elements
                            if isinstance(e, dict)
                            and e.get(match_field) == match_value]
            out[arr] = elements
        elif key in doc:
            out[key] = doc[key]
    return out


# ---------------------------------------------------------------------------
# Update -> SQL compiler (new-doc expression over the old ``doc`` value)
# ---------------------------------------------------------------------------
def _set_nested(doc: dict, segments, value) -> None:
    cur = doc
    for seg in segments[:-1]:
        nxt = cur.get(seg)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[seg] = nxt
        cur = nxt
    cur[segments[-1]] = value


def _positional_matcher(filt: dict, arr: str):
    """Find the filter's ``arr.<field> == value`` matcher for ``$`` paths."""
    for key, value in (filt or {}).items():
        if key.startswith(arr + ".") and "." in key and not isinstance(value, dict):
            return key.split(".", 1)[1], value
    return None, None


def _array_rebuild(builder: _SqlBuilder, current: str, arr: str,
                   match_field: str, match_value, elem_expr_fn) -> str:
    """Rebuild a JSONB array, transforming elements matching the filter."""
    mv = builder.add(match_value)
    case = (f"CASE WHEN e->>{_sql_str_literal(match_field)} = {mv} "
            f"THEN {elem_expr_fn('e')} ELSE e END")
    agg = (f"(SELECT jsonb_agg({case}) FROM "
           f"jsonb_array_elements({current} -> {_sql_str_literal(arr)}) AS e)")
    return (f"(CASE WHEN jsonb_typeof({current} -> {_sql_str_literal(arr)}) "
            f"= 'array' THEN {agg} ELSE {current} -> "
            f"{_sql_str_literal(arr)} END)")


def _update_expr(builder: _SqlBuilder, current: str, update: dict,
                 filt: dict) -> str:
    expr = current
    for op, changes in update.items():
        if op == "$set":
            for path, value in changes.items():
                segments = path.split(".")
                if "$" in segments:
                    idx = segments.index("$")
                    arr, rest = segments[0], segments[idx + 1:]
                    mf, mv = _positional_matcher(filt, arr)
                    if mf is None:
                        raise NotImplementedError(
                            f"positional $set without filter matcher: {path}")
                    param = builder.add(_dumps(value))
                    rebuilt = _array_rebuild(
                        builder, expr, arr, mf, mv,
                        lambda e: (f"jsonb_set({e}, "
                                   f"'{{{','.join(rest)}}}', {param}::jsonb)"))
                    expr = f"jsonb_set({expr}, '{{{arr}}}', {rebuilt})"
                else:
                    param = builder.add(_dumps(value))
                    expr = (f"jsonb_set({expr}, "
                            f"'{{{','.join(segments)}}}', {param}::jsonb)")
        elif op == "$inc":
            for path, delta in changes.items():
                segments = path.split(".")
                if "$" in segments:
                    idx = segments.index("$")
                    arr, rest = segments[0], segments[idx + 1:]
                    mf, mv = _positional_matcher(filt, arr)
                    if mf is None:
                        raise NotImplementedError(
                            f"positional $inc without filter matcher: {path}")
                    dparam = builder.add(delta)
                    rest_path = "{" + ",".join(rest) + "}"
                    rebuilt = _array_rebuild(
                        builder, expr, arr, mf, mv,
                        lambda e, _d=dparam, _r=rest_path: (
                            f"jsonb_set({e}, '{_r}', to_jsonb(COALESCE("
                            f"(CASE WHEN (e #>> '{_r}') ~ "
                            f"{_sql_str_literal(_NUM_RE)} THEN "
                            f"(e #>> '{_r}')::numeric ELSE NULL END), 0) "
                            f"+ {_d}))"))
                    expr = f"jsonb_set({expr}, '{{{arr}}}', {rebuilt})"
                else:
                    path_lit = "{" + ",".join(segments) + "}"
                    cur = f"({expr} #>> '{path_lit}')"
                    num = (f"(CASE WHEN {cur} ~ {_sql_str_literal(_NUM_RE)} "
                           f"THEN {cur}::numeric ELSE NULL END)")
                    dparam = builder.add(delta)
                    expr = (f"jsonb_set({expr}, '{path_lit}', "
                            f"to_jsonb(COALESCE({num}, 0) + {dparam}))")
        elif op == "$push":
            for path, value in changes.items():
                segments = path.split(".")
                path_lit = "{" + ",".join(segments) + "}"
                if isinstance(value, dict) and "$each" in value:
                    items = value["$each"]
                elif isinstance(value, list):
                    items = [value]  # push a list as ONE element (Mongo)
                else:
                    items = value
                param = builder.add(_dumps(items))
                cur_arr = (f"(CASE WHEN jsonb_typeof({expr} #> '{path_lit}') "
                           f"= 'array' THEN {expr} #> '{path_lit}' "
                           f"ELSE '[]'::jsonb END)")
                expr = (f"jsonb_set({expr}, '{path_lit}', "
                        f"({cur_arr} || {param}::jsonb))")
        elif op == "$unset":
            for path in changes:
                segments = path.split(".")
                if len(segments) == 1:
                    expr = f"({expr} - {_sql_str_literal(segments[0])})"
                else:
                    expr = (f"({expr} #- "
                            f"'{{{','.join(segments)}}}')")
        elif op == "$pull":
            for path, cond in changes.items():
                if not isinstance(cond, dict):
                    raise NotImplementedError("$pull needs a dict condition")
                segments = path.split(".")
                if len(segments) != 1:
                    raise NotImplementedError("$pull on nested path")
                field = segments[0]
                cond_parts = []
                for ck, cv in cond.items():
                    cond_parts.append(
                        _eq_fragment(builder, ck, cv, (), "elem"))
                cond_sql = " AND ".join(cond_parts)
                filtered = (
                    f"(SELECT COALESCE(jsonb_agg(e), '[]'::jsonb) FROM "
                    f"jsonb_array_elements({expr} -> "
                    f"{_sql_str_literal(field)}) AS e "
                    f"WHERE NOT ({cond_sql}))")
                expr = (f"(CASE WHEN jsonb_typeof({expr} -> "
                        f"{_sql_str_literal(field)}) = 'array' "
                        f"THEN jsonb_set({expr}, '{{{field}}}', {filtered}) "
                        f"ELSE {expr} END)")
        else:
            raise NotImplementedError(f"unsupported update operator: {op}")
    return expr


def _upsert_doc(filt: dict, update: dict) -> dict:
    """Build the inserted document for an upsert (Mongo semantics)."""
    doc: dict = {}
    for key, value in (filt or {}).items():
        if key.startswith("$") or isinstance(value, dict):
            continue
        _set_nested(doc, key.split("."), value)
    for op, changes in update.items():
        if op == "$set":
            for path, value in changes.items():
                _set_nested(doc, path.split("."), value)
        elif op == "$inc":
            for path, delta in changes.items():
                _set_nested(doc, path.split("."), delta)
        else:
            raise NotImplementedError(f"upsert with {op} not supported")
    return doc


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
class PgCollection:
    def __init__(self, db: "PgDatabase", name: str):
        self._db = db
        self.name = name
        pk_fields, dt_fields = TABLES[name]
        self._pk_fields = pk_fields
        self._dt_fields = dt_fields
        self._surrogate_pk = "ledger_id" if not pk_fields else None

    # -- helpers -----------------------------------------------------------
    @property
    def _table(self) -> str:
        return _sql_ident(self.name)

    def _pk_columns(self):
        return list(self._pk_fields) or [self._surrogate_pk]

    def _pk_values(self, doc: dict):
        if self._surrogate_pk:
            return [uuid.uuid4().hex]
        values = []
        for field in self._pk_fields:
            value = doc.get(field)
            if value is None:
                raise ValueError(
                    f"cannot insert into {self.name}: missing PK field "
                    f"{field!r} in document")
            values.append(value)
        return values

    def _decode(self, raw) -> dict:
        return _convert_datetimes(_loads(raw), self._dt_fields)

    async def _fetch_one(self, where: str, params):
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT seq, doc FROM {self._table} WHERE {where} "
                f"ORDER BY seq LIMIT 1", *params)
        return row

    # -- reads -------------------------------------------------------------
    async def find_one(self, filt=None, projection=None):
        builder = _SqlBuilder()
        where = _compile_filter(builder, filt or {}, self._dt_fields)
        row = await self._fetch_one(where, builder.params)
        if row is None:
            return None
        return _apply_projection(self._decode(row["doc"]), projection,
                                 filt or {})

    def find(self, filt=None, projection=None):
        return PgCursor(self, filt or {}, projection)

    async def count_documents(self, filt=None) -> int:
        builder = _SqlBuilder()
        where = _compile_filter(builder, filt or {}, self._dt_fields)
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                f"SELECT COUNT(*) FROM {self._table} WHERE {where}",
                *builder.params)

    def aggregate(self, pipeline):
        return AggCursor(self, pipeline)

    # -- writes ------------------------------------------------------------
    async def insert_one(self, doc: dict) -> InsertOneResult:
        if "_id" not in doc:
            doc["_id"] = uuid.uuid4().hex
        pk_values = self._pk_values(doc)
        cols = self._pk_columns()
        placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
        col_list = ", ".join(_sql_ident(c) for c in cols)
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self._table} ({col_list}, doc) "
                f"VALUES ({placeholders}, ${len(cols) + 1}::jsonb)",
                *pk_values, _dumps(doc))
        return InsertOneResult(doc["_id"])

    async def _update_where(self, filt, update, many: bool):
        """Returns (matched, modified) for a filter+update pair.

        The locate step runs BEFORE the update expression is compiled, so
        each statement is bound with exactly the parameters it references.
        ``modified`` counts only rows whose document actually changed
        (``IS DISTINCT FROM``), matching Mongo's ``modified_count`` --
        setting an already-equal value reports 0, which the Stripe webhook
        handler relies on (``res.modified_count == 0`` -> already paid).
        """
        builder = _SqlBuilder()
        where = _compile_filter(builder, filt or {}, self._dt_fields)
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            if many:
                matched = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {self._table} WHERE {where}",
                    *builder.params)
                new_expr = _update_expr(builder, "doc", update, filt or {})
                status = await conn.execute(
                    f"UPDATE {self._table} SET doc = {new_expr} "
                    f"WHERE {where} AND {new_expr} IS DISTINCT FROM doc",
                    *builder.params)
                return matched, int(status.split()[-1])
            row = await conn.fetchrow(
                f"SELECT seq FROM {self._table} WHERE {where} "
                f"ORDER BY seq LIMIT 1", *builder.params)
            if row is None:
                return 0, 0
            # Fresh builder: the UPDATE references only update params + seq.
            # Reusing the filter builder would leave $1 unreferenced (the
            # filter clause is not in this statement) and Postgres rejects
            # a typed-less $1 placeholder.
            update_builder = _SqlBuilder()
            new_expr = _update_expr(update_builder, "doc", update, filt or {})
            status = await conn.execute(
                f"UPDATE {self._table} SET doc = {new_expr} "
                f"WHERE seq = ${len(update_builder.params) + 1} "
                f"AND {new_expr} IS DISTINCT FROM doc",
                *update_builder.params, row["seq"])
            return 1, int(status.split()[-1])

    async def update_one(self, filt, update, upsert=False, **kwargs):
        matched, modified = await self._update_where(filt, update, many=False)
        if matched:
            return UpdateResult(matched, modified)
        if not upsert:
            return UpdateResult(0, 0)
        doc = _upsert_doc(filt, update)
        result = await self.insert_one(doc)
        return UpdateResult(0, 0, upserted_id=result.inserted_id)

    async def update_many(self, filt, update, upsert=False):
        if upsert:
            raise NotImplementedError("update_many(upsert=True)")
        matched, modified = await self._update_where(filt, update, many=True)
        return UpdateResult(matched, modified)

    async def delete_one(self, filt):
        builder = _SqlBuilder()
        where = _compile_filter(builder, filt or {}, self._dt_fields)
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT seq FROM {self._table} WHERE {where} "
                f"ORDER BY seq LIMIT 1", *builder.params)
            if row is None:
                return DeleteResult(0)
            status = await conn.execute(
                f"DELETE FROM {self._table} WHERE seq = $1", row["seq"])
        return DeleteResult(int(status.split()[-1]))

    async def delete_many(self, filt):
        builder = _SqlBuilder()
        where = _compile_filter(builder, filt or {}, self._dt_fields)
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                f"DELETE FROM {self._table} WHERE {where}", *builder.params)
        return DeleteResult(int(status.split()[-1]))

    async def find_one_and_update(self, filt, update, projection=None,
                                  **kwargs):
        builder = _SqlBuilder()
        where = _compile_filter(builder, filt or {}, self._dt_fields)
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT seq, doc FROM {self._table} WHERE {where} "
                f"ORDER BY seq LIMIT 1", *builder.params)
            if row is None:
                return None
            old = self._decode(row["doc"])
            # Fresh builder for the same reason as in _update_where: the
            # UPDATE references only update params + seq, not the filter.
            update_builder = _SqlBuilder()
            new_expr = _update_expr(update_builder, "doc", update, filt or {})
            await conn.execute(
                f"UPDATE {self._table} SET doc = {new_expr} WHERE seq = "
                f"${len(update_builder.params) + 1}",
                *update_builder.params, row["seq"])
        # Motor's default returns the PRE-update document.
        return _apply_projection(old, projection, filt or {})

    async def replace_one(self, filt, replacement, upsert=False):
        builder = _SqlBuilder()
        where = _compile_filter(builder, filt or {}, self._dt_fields)
        pool = await self._db._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT seq, doc FROM {self._table} WHERE {where} "
                f"ORDER BY seq LIMIT 1", *builder.params)
            if row is not None:
                old_doc = self._decode(row["doc"])
                new_doc = dict(replacement)
                if "_id" not in new_doc:
                    new_doc["_id"] = old_doc.get("_id")
                cols = self._pk_columns()
                sets = ["doc = $1::jsonb"]
                params = [_dumps(new_doc)]
                for col in cols:
                    if col == self._surrogate_pk:
                        continue
                    sets.append(f"{_sql_ident(col)} = "
                                f"${len(params) + 1}")
                    # Fall back to the old PK value if the replacement
                    # omits it (replacements in practice always include it).
                    params.append(new_doc.get(col, old_doc.get(col)))
                params.append(row["seq"])
                await conn.execute(
                    f"UPDATE {self._table} SET {', '.join(sets)} "
                    f"WHERE seq = ${len(params)}", *params)
                return ReplaceResult(1, 1)
        if not upsert:
            return ReplaceResult(0, 0)
        new_doc = _upsert_doc(filt, {})
        for key, value in replacement.items():
            new_doc[key] = value
        result = await self.insert_one(new_doc)
        return ReplaceResult(0, 1, upserted_id=result.inserted_id)

    # -- index shims (DDL owns the real indexes) ---------------------------
    async def create_index(self, keys, **kwargs):
        if isinstance(keys, str):
            return f"{keys}_1"
        return "_".join(f"{field}_{direction}"
                        for field, direction in keys)

    async def index_information(self):
        if self.name == "users":
            return {
                "email_1": {
                    "key": [("email", 1)],
                    "unique": True,
                    "partialFilterExpression": {"email": {"$type": "string"}},
                },
                "user_id_1": {"key": [("user_id", 1)], "unique": True},
            }
        if self.name == "otp_challenges":
            return {
                "email_1": {"key": [("email", 1)], "unique": True},
                # NOTE: deliberately NO expireAfterSeconds -- TTL is handled
                # by the sweeper job, not by a Postgres TTL (there is none).
                "expires_at_1": {"key": [("expires_at", 1)]},
            }
        if self.name == "export_files":
            return {
                "token_1": {"key": [("token", 1)], "unique": True},
                # NOTE: deliberately NO expireAfterSeconds -- expiry stays
                # LAZY on download, exactly as the old code intended when it
                # removed the TTL index.
                "expires_at_1": {"key": [("expires_at", 1)]},
            }
        return {}

    async def drop_index(self, name, **kwargs):
        return True


# ---------------------------------------------------------------------------
# Cursor (Motor-compatible subset)
# ---------------------------------------------------------------------------
class PgCursor:
    def __init__(self, coll: PgCollection, filt: dict, projection):
        self._coll = coll
        self._filt = filt
        self._projection = projection
        self._sort_spec = None
        self._limit = None
        self._skip = None
        self._rows = None
        self._rows_complete = False

    def sort(self, spec, direction=None):
        if direction is not None:
            spec = [(spec, direction)]
        self._sort_spec = spec
        return self

    def limit(self, n):
        self._limit = n
        return self

    def skip(self, n):
        self._skip = n
        return self

    def _build_sql(self, to_list_n):
        builder = _SqlBuilder()
        where = _compile_filter(builder, self._filt, self._coll._dt_fields)
        sql = f"SELECT doc FROM {self._coll._table} WHERE {where}"
        order = _compile_sort(self._sort_spec, self._coll._dt_fields)
        sql += f" {order}" if order else " ORDER BY seq"
        if self._sort_spec:
            sql += ", seq"  # deterministic tiebreak (insertion order)
        limit = self._limit
        if to_list_n is not None:
            limit = to_list_n if limit is None else min(limit, to_list_n)
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if self._skip:
            sql += f" OFFSET {int(self._skip)}"
        return sql, builder.params

    async def _fetch(self, to_list_n):
        sql, params = self._build_sql(to_list_n)
        pool = await self._coll._db._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        docs = [self._coll._decode(r["doc"]) for r in rows]
        return [_apply_projection(d, self._projection, self._filt)
                for d in docs]

    async def to_list(self, n=None):
        if self._rows is not None and self._rows_complete:
            return list(self._rows[:n] if n is not None else self._rows)
        rows = await self._fetch(n)
        if n is None:
            # Only a full fetch may be cached; a partial to_list(n) fetch
            # must never masquerade as the whole cursor.
            self._rows, self._rows_complete = rows, True
        return list(rows)

    async def __aiter__(self):
        if self._rows is None or not self._rows_complete:
            self._rows = await self._fetch(None)
            self._rows_complete = True
        for doc in self._rows:
            yield doc


# ---------------------------------------------------------------------------
# Aggregation (Python-side stages over SQL-filtered documents)
# ---------------------------------------------------------------------------
def _sort_key(value):
    if value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, datetime):
        return (1, value.timestamp())
    if isinstance(value, str):
        return (2, value)
    return (3, str(value))


def _agg_sort(docs, spec: dict):
    for field, direction in reversed(list(spec.items())):
        reverse = direction < 0
        docs.sort(key=lambda d: _sort_key(d.get(field)),
                  reverse=reverse)
    return docs


def _agg_group(docs, spec: dict):
    key_spec = spec.get("_id")
    groups: dict = {}
    order = []
    for doc in docs:
        if key_spec is None:
            key = None
        elif isinstance(key_spec, str) and key_spec.startswith("$"):
            key = doc.get(key_spec[1:])
        else:
            key = key_spec
        # Dict keys must be hashable; group keys here are scalars/None.
        marker = ("__none__",) if key is None else ("__val__", key)
        if marker not in groups:
            groups[marker] = {"_id": key}
            order.append(marker)
        out = groups[marker]
        for out_field, acc in spec.items():
            if out_field == "_id":
                continue
            if not isinstance(acc, dict):
                raise NotImplementedError(f"accumulator: {acc!r}")
            if "$sum" in acc:
                operand = acc["$sum"]
                if operand == 1:
                    out[out_field] = out.get(out_field, 0) + 1
                elif isinstance(operand, str) and operand.startswith("$"):
                    value = doc.get(operand[1:])
                    if isinstance(value, bool):
                        continue
                    if isinstance(value, (int, float)):
                        out[out_field] = out.get(out_field, 0) + value
                elif isinstance(operand, (int, float)):
                    out[out_field] = out.get(out_field, 0) + operand
                else:
                    raise NotImplementedError(f"$sum operand: {operand!r}")
            elif "$first" in acc:
                operand = acc["$first"]
                if out_field not in out:
                    out[out_field] = (doc.get(operand[1:])
                                      if isinstance(operand, str)
                                      and operand.startswith("$")
                                      else operand)
            else:
                raise NotImplementedError(f"accumulator: {acc!r}")
    # Groups with only $sum accumulators and no docs never appear (Mongo
    # returns no rows for an empty input); groups formed here all have docs.
    return [groups[m] for m in order]


class AggCursor:
    def __init__(self, coll: PgCollection, pipeline):
        self._coll = coll
        self._pipeline = pipeline
        self._rows = None

    async def _run(self):
        if self._rows is not None:
            return self._rows
        match_filter: dict = {}
        stages = list(self._pipeline)
        # Leading $match stages collapse into one SQL WHERE.
        while stages and set(stages[0]) == {"$match"}:
            match_filter = {**match_filter, **stages.pop(0)["$match"]}
        builder = _SqlBuilder()
        where = _compile_filter(builder, match_filter,
                                self._coll._dt_fields)
        pool = await self._coll._db._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT doc FROM {self._coll._table} WHERE {where}",
                *builder.params)
        docs = [self._coll._decode(r["doc"]) for r in rows]
        for stage in stages:
            if "$sort" in stage:
                docs = _agg_sort(docs, stage["$sort"])
            elif "$group" in stage:
                docs = _agg_group(docs, stage["$group"])
            elif "$limit" in stage:
                docs = docs[:stage["$limit"]]
            else:
                raise NotImplementedError(
                    f"unsupported aggregate stage: {sorted(stage)}")
        self._rows = docs
        return docs

    async def to_list(self, n=None):
        rows = await self._run()
        return list(rows[:n] if n is not None else rows)

    async def __aiter__(self):
        for doc in await self._run():
            yield doc


# ---------------------------------------------------------------------------
# Database (attribute access: db.<collection>)
# ---------------------------------------------------------------------------
class PgDatabase:
    """Drop-in replacement for ``client[db_name]`` in server.py.

    The asyncpg pool is created lazily on first use (server.py constructs
    the database object at import time, before any event loop runs).
    """

    def __init__(self, dsn: str, pool=None):
        self._dsn = dsn
        self._pool = pool
        self._pool_lock = asyncio.Lock()
        self._collections: dict = {}

    async def _ensure_pool(self):
        if self._pool is None:
            async with self._pool_lock:
                if self._pool is None:
                    self._pool = await asyncpg.create_pool(
                        self._dsn, min_size=2, max_size=10)
        return self._pool

    async def close(self):
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in TABLES:
            raise AttributeError(f"unknown collection: {name!r}")
        coll = self._collections.get(name)
        if coll is None:
            coll = PgCollection(self, name)
            self._collections[name] = coll
        return coll
