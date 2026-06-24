"""Unified local-only private input center for manual Personal CFO data."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from personal_cfo_agent.manual_nav_input import (
    ManualNavBundleResult,
    manual_nav_to_provider_bundle,
    validate_manual_nav_input,
)
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.property_mortgage_snapshot import (
    PropertyMortgageSnapshotResult,
    record_property_mortgage_snapshot,
)
from personal_cfo_agent.sg_manual_snapshot import (
    SGManualSnapshotResult,
    record_sg_manual_snapshot,
)


SCHEMA_VERSION = "v0.5.8"
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "templates" / "private_inputs"
PRIVATE_INPUT_CENTER_EXAMPLE = TEMPLATE_DIR / "personal_cfo_input.example.json"
PRIVATE_INPUT_CENTER_FORM_TEMPLATE = TEMPLATE_DIR / "personal_cfo_input_form.html"
PRIVATE_INPUT_CENTER_SAVE_ENDPOINT_TOKEN = "__LOCAL_SAVE_ENDPOINT__"
PRIVATE_INPUT_CENTER_FX_ENDPOINT_TOKEN = "__LOCAL_FX_ENDPOINT__"
DEFAULT_FX_CURRENCIES = ("USD", "CNY", "HKD")

SECTION_KEYS = (
    "manual_nav_accounts",
    "properties",
    "mortgages",
    "cpf",
    "srs",
    "tax",
    "hdb_loans",
)

EXPECTED_MANUAL_LAYER_KEYS = (
    "manual_nav",
    "property_mortgage",
    "sg_retirement_tax",
)

_MANUAL_NAV_PROVIDER_MAP = {
    "manual_other": "other",
}
_MANUAL_NAV_ACCOUNT_TYPE_MAP = {
    "manual_nav": "other",
}
_MANUAL_NAV_SOURCE_TYPE_MAP = {
    "local_private_input_center": "app_manual",
}

_NRIC_PATTERN = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
_FORBIDDEN_KEYS = {
    "account_id",
    "account_number",
    "raw_account_id",
    "raw_account_number",
    "address",
    "raw_address",
    "postal_code",
    "unit_number",
    "nric",
    "fin",
    "uin",
    "government_id",
    "identity_number",
    "cpf_account_number",
    "hdb_account_number",
    "tax_reference_number",
    "bank_account_number",
    "password",
    "token",
    "secret",
    "api_key",
}


@dataclass(frozen=True)
class PrivateInputCenterFormResult:
    output_dir: Path
    output_path: Path
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterInitResult:
    output_file: Path
    created: bool
    skipped: bool
    overwritten: bool
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterValidationResult:
    input_file: Path
    valid: bool
    manual_nav_account_count: int = 0
    property_count: int = 0
    mortgage_count: int = 0
    cpf_count: int = 0
    srs_count: int = 0
    tax_count: int = 0
    hdb_loan_count: int = 0
    provider_labels: list[str] = field(default_factory=list)
    base_currencies: list[str] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterLocalSaveResult:
    input_file: Path
    saved: bool
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterFxFetchResult:
    out_file: Path | None
    generated: bool
    base_currency: str
    currencies: list[str] = field(default_factory=list)
    source_date: str = ""
    rates_to_base: dict[str, str] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)


@dataclass(frozen=True)
class PrivateInputCenterSnapshotResult:
    input_file: Path
    output_dir: Path
    manual_nav_output_dir: Path
    property_output_dir: Path
    sg_output_dir: Path
    manual_nav_result: ManualNavBundleResult | None = None
    property_result: PropertyMortgageSnapshotResult | None = None
    sg_result: SGManualSnapshotResult | None = None
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False


@dataclass(frozen=True)
class ExpectedSourceContract:
    providers_required: list[str] = field(default_factory=list)
    providers_optional: list[str] = field(default_factory=list)
    manual_layers_required: list[str] = field(default_factory=list)
    manual_layers_optional: list[str] = field(default_factory=list)
    warning_codes: list[WarningCode] = field(default_factory=list)


def generate_private_input_center_form(*, out_dir: Path) -> PrivateInputCenterFormResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "personal_cfo_input_form.html"
    output_path.write_text(
        build_private_input_center_form_html(local_save_endpoint=""),
        encoding="utf-8",
    )
    return PrivateInputCenterFormResult(
        output_dir=out_dir,
        output_path=output_path,
        warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_FORM_GENERATED],
    )


def build_private_input_center_form_html(
    *, local_save_endpoint: str = "", local_fx_endpoint: str = ""
) -> str:
    template = PRIVATE_INPUT_CENTER_FORM_TEMPLATE.read_text(encoding="utf-8")
    return (
        template.replace(
            PRIVATE_INPUT_CENTER_SAVE_ENDPOINT_TOKEN,
            _escape_javascript_string(local_save_endpoint),
        )
        .replace(
            PRIVATE_INPUT_CENTER_FX_ENDPOINT_TOKEN,
            _escape_javascript_string(local_fx_endpoint),
        )
    )


def save_private_input_center_payload(
    *, input_file: Path, payload_text: str
) -> PrivateInputCenterLocalSaveResult:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return PrivateInputCenterLocalSaveResult(
            input_file=input_file,
            saved=False,
            warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID],
        )
    if not isinstance(payload, dict):
        return PrivateInputCenterLocalSaveResult(
            input_file=input_file,
            saved=False,
            warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID],
        )

    normalized = json.dumps(payload, indent=2)
    with tempfile.TemporaryDirectory(prefix="personal_cfo_input_center_save_") as temp_name:
        temp_file = Path(temp_name) / "personal_cfo_input.local.json"
        temp_file.write_text(normalized, encoding="utf-8")
        validation = validate_private_input_center(input_file=temp_file)
    if not validation.valid:
        return PrivateInputCenterLocalSaveResult(
            input_file=input_file,
            saved=False,
            warning_codes=validation.warning_codes,
        )

    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_text(normalized + "\n", encoding="utf-8")
    return PrivateInputCenterLocalSaveResult(
        input_file=input_file,
        saved=True,
        warning_codes=validation.warning_codes,
    )


def fetch_public_fx_rates(
    *,
    base_currency: str,
    currencies: list[str] | tuple[str, ...] | None = None,
    out_file: Path | None = None,
    rate_date: str = "",
    urlopen_func: Any = urlopen,
) -> PrivateInputCenterFxFetchResult:
    """Fetch public reference FX rates into the local explicit-FX schema.

    The returned rates are currency-to-base values, matching the local
    `rates_to_base` convention used by dashboards and refresh checks.
    """

    base = _clean(base_currency).upper()
    requested = _currency_list(currencies or DEFAULT_FX_CURRENCIES)
    if not _valid_currency_code(base) or not requested:
        return PrivateInputCenterFxFetchResult(
            out_file=out_file,
            generated=False,
            base_currency=base,
            currencies=requested,
            warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_FX_FETCH_FAILED],
        )

    rates: dict[str, str] = {base: "1.00"}
    source_dates: set[str] = set()
    source_types: set[str] = set()
    endpoint_date = _fx_endpoint_date(rate_date)
    try:
        for currency in requested:
            if not _valid_currency_code(currency):
                raise ValueError("invalid_currency")
            if currency == base:
                continue
            rate, source_date, source_type = _fetch_reference_rate(
                from_currency=currency,
                to_currency=base,
                endpoint_date=endpoint_date,
                urlopen_func=urlopen_func,
            )
            if rate is None:
                raise ValueError("missing_rate")
            rates[currency] = format(rate, "f")
            if source_date:
                source_dates.add(source_date)
            if source_type:
                source_types.add(source_type)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        return PrivateInputCenterFxFetchResult(
            out_file=out_file,
            generated=False,
            base_currency=base,
            currencies=requested,
            warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_FX_FETCH_FAILED],
        )

    source_date = sorted(source_dates)[-1] if source_dates else endpoint_date
    payload = {
        "base_currency": base,
        "rates_to_base": rates,
        "source_type": "+".join(sorted(source_types)) or "public_fx_api",
        "source_date": source_date,
        "review_required": True,
    }
    if out_file is not None:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return PrivateInputCenterFxFetchResult(
        out_file=out_file,
        generated=True,
        base_currency=base,
        currencies=sorted(rates),
        source_date=source_date,
        rates_to_base=rates,
        warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_FX_FETCH_OK],
    )


def _fetch_reference_rate(
    *,
    from_currency: str,
    to_currency: str,
    endpoint_date: str,
    urlopen_func: Any,
) -> tuple[Decimal | None, str, str]:
    try:
        payload = _fetch_frankfurter_rate(
            from_currency=from_currency,
            to_currency=to_currency,
            endpoint_date=endpoint_date,
            urlopen_func=urlopen_func,
        )
        return (
            _positive_decimal(payload.get("rates", {}).get(to_currency)),
            _clean(payload.get("date")),
            "public_fx_api_frankfurter",
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
        payload = _fetch_open_er_rate(
            from_currency=from_currency,
            to_currency=to_currency,
            urlopen_func=urlopen_func,
        )
        return (
            _positive_decimal(payload.get("rates", {}).get(to_currency)),
            _clean(payload.get("time_last_update_utc") or payload.get("time_last_update_unix")),
            "public_fx_api_open_er_api",
        )


def _fetch_frankfurter_rate(
    *,
    from_currency: str,
    to_currency: str,
    endpoint_date: str,
    urlopen_func: Any,
) -> dict[str, Any]:
    query = urlencode({"from": from_currency, "to": to_currency})
    url = f"https://api.frankfurter.app/{endpoint_date}?{query}"
    with urlopen_func(url, timeout=10) as response:
        data = response.read().decode("utf-8")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    return payload


def _fetch_open_er_rate(
    *,
    from_currency: str,
    to_currency: str,
    urlopen_func: Any,
) -> dict[str, Any]:
    url = f"https://open.er-api.com/v6/latest/{from_currency}"
    with urlopen_func(url, timeout=10) as response:
        data = response.read().decode("utf-8")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    if payload.get("result") != "success" or to_currency not in payload.get("rates", {}):
        raise ValueError("missing_rate")
    return payload


def _fx_endpoint_date(value: str) -> str:
    cleaned = _clean(value)
    if not cleaned:
        return "latest"
    try:
        date.fromisoformat(cleaned)
    except ValueError:
        return "latest"
    return cleaned


def _currency_list(value: object) -> list[str]:
    if value is None:
        return list(DEFAULT_FX_CURRENCIES)
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []
    currencies: list[str] = []
    for part in parts:
        currency = _clean(part).upper()
        if currency and currency not in currencies:
            currencies.append(currency)
    return currencies


def _valid_currency_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", value))


def _positive_decimal(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def serve_private_input_center_local_app(
    *,
    input_file: Path,
    out_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    endpoint = f"http://{host}:{port}/save"
    fx_endpoint = f"http://{host}:{port}/fx-rates"
    html = build_private_input_center_form_html(
        local_save_endpoint=endpoint,
        local_fx_endpoint=fx_endpoint,
    )
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "personal_cfo_input_form.html").write_text(html, encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/personal_cfo_input_form.html"}:
                self._send_text(200, html, content_type="text/html; charset=utf-8")
                return
            if self.path == "/status":
                self._send_json(
                    200,
                    {
                        "local_save_ready": True,
                        "public_fx_fetch_ready": True,
                        "target_file_name": input_file.name,
                        "external_connections_used": False,
                        "external_fx_request_used_at_startup": False,
                    },
                )
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/fx-rates":
                self._handle_fx_rates()
                return
            if self.path != "/save":
                self._send_json(404, {"error": "not_found"})
                return
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                self._send_json(
                    400,
                    {
                        "saved": False,
                        "warning_codes": [
                            WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID.value
                        ],
                    },
                )
                return
            if length <= 0 or length > 1_000_000:
                self._send_json(
                    400,
                    {
                        "saved": False,
                        "warning_codes": [
                            WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID.value
                        ],
                    },
                )
                return
            payload_text = self.rfile.read(length).decode("utf-8")
            result = save_private_input_center_payload(
                input_file=input_file,
                payload_text=payload_text,
            )
            status = 200 if result.saved else 400
            self._send_json(
                status,
                {
                    "saved": result.saved,
                    "target_file_name": input_file.name,
                    "warning_codes": [code.value for code in result.warning_codes],
                },
            )

        def _handle_fx_rates(self) -> None:
            length_header = self.headers.get("Content-Length", "0")
            try:
                length = int(length_header)
            except ValueError:
                self._send_json(
                    400,
                    {
                        "generated": False,
                        "warning_codes": [
                            WarningCode.PRIVATE_INPUT_CENTER_FX_FETCH_FAILED.value
                        ],
                    },
                )
                return
            if length <= 0 or length > 20_000:
                self._send_json(
                    400,
                    {
                        "generated": False,
                        "warning_codes": [
                            WarningCode.PRIVATE_INPUT_CENTER_FX_FETCH_FAILED.value
                        ],
                    },
                )
                return
            try:
                request_payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json(
                    400,
                    {
                        "generated": False,
                        "warning_codes": [
                            WarningCode.PRIVATE_INPUT_CENTER_FX_FETCH_FAILED.value
                        ],
                    },
                )
                return
            if not isinstance(request_payload, dict):
                self._send_json(
                    400,
                    {
                        "generated": False,
                        "warning_codes": [
                            WarningCode.PRIVATE_INPUT_CENTER_FX_FETCH_FAILED.value
                        ],
                    },
                )
                return
            result = fetch_public_fx_rates(
                base_currency=_clean(request_payload.get("base_currency") or "SGD"),
                currencies=_currency_list(request_payload.get("currencies")),
                rate_date=_clean(request_payload.get("rate_date")),
                out_file=None,
            )
            status = 200 if result.generated else 502
            self._send_json(
                status,
                {
                    "generated": result.generated,
                    "base_currency": result.base_currency,
                    "currencies": result.currencies,
                    "source_date": result.source_date,
                    "rates_to_base": result.rates_to_base if result.generated else {},
                    "warning_codes": [code.value for code in result.warning_codes],
                },
            )

        def _send_text(
            self, status: int, text: str, *, content_type: str = "text/plain"
        ) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer((host, port), Handler) as server:
        server.serve_forever()


def init_private_input_center(
    *, out_file: Path, overwrite: bool = False
) -> PrivateInputCenterInitResult:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists() and not overwrite:
        return PrivateInputCenterInitResult(
            output_file=out_file,
            created=False,
            skipped=True,
            overwritten=False,
            warning_codes=[WarningCode.PRIVATE_INPUT_CENTER_EXISTS_SKIPPED],
        )
    overwritten = out_file.exists()
    shutil.copyfile(PRIVATE_INPUT_CENTER_EXAMPLE, out_file)
    warnings = [WarningCode.PRIVATE_INPUT_CENTER_INITIALIZED]
    if overwritten:
        warnings.append(WarningCode.PRIVATE_INPUT_CENTER_OVERWRITE_USED)
    return PrivateInputCenterInitResult(
        output_file=out_file,
        created=not overwritten,
        skipped=False,
        overwritten=overwritten,
        warning_codes=warnings,
    )


def validate_private_input_center(*, input_file: Path) -> PrivateInputCenterValidationResult:
    payload, read_warnings = _load_payload(input_file)
    if payload is None:
        return PrivateInputCenterValidationResult(
            input_file=input_file,
            valid=False,
            warning_codes=read_warnings,
        )
    with tempfile.TemporaryDirectory(prefix="personal_cfo_input_center_") as temp_name:
        temp_dir = Path(temp_name)
        split_paths = _write_split_inputs(payload, temp_dir)
        manual_result = validate_manual_nav_input(input_file=split_paths["manual_nav"])
    manual_accounts = _manual_nav_accounts_for_split(payload)

    warnings = _dedupe(
        [
            *_payload_warnings(payload),
            *_map_manual_nav_warnings(manual_result.warning_codes),
        ]
    )
    blocking = {
        WarningCode.PRIVATE_INPUT_CENTER_INPUT_MISSING,
        WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID,
        WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING,
        WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED,
        WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID,
    }
    valid = not any(code in blocking for code in warnings)
    completion = (
        WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_FAILED
        if not valid
        else WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS
        if warnings
        else WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_OK
    )
    return PrivateInputCenterValidationResult(
        input_file=input_file,
        valid=valid,
        manual_nav_account_count=_section_count(payload, "manual_nav_accounts"),
        property_count=_section_count(payload, "properties"),
        mortgage_count=_section_count(payload, "mortgages"),
        cpf_count=_section_count(payload, "cpf"),
        srs_count=_section_count(payload, "srs"),
        tax_count=_section_count(payload, "tax"),
        hdb_loan_count=_section_count(payload, "hdb_loans"),
        provider_labels=sorted(
            {
                _clean(account.get("provider_label"))
                for account in manual_accounts
                if _clean(account.get("provider_label"))
            }
        ),
        base_currencies=sorted(
            {
                _clean(account.get("base_currency"))
                for account in manual_accounts
                if _clean(account.get("base_currency"))
            }
        ),
        warning_codes=_dedupe([*warnings, completion]),
    )


def private_input_center_to_snapshots(
    *,
    input_file: Path,
    out_dir: Path,
    env: Mapping[str, str],
    generated_at: datetime | None = None,
) -> PrivateInputCenterSnapshotResult:
    validation = validate_private_input_center(input_file=input_file)
    manual_out = out_dir / "manual_nav"
    property_out = out_dir / "property_mortgage"
    sg_out = out_dir / "sg_retirement_tax"
    if not validation.valid:
        return PrivateInputCenterSnapshotResult(
            input_file=input_file,
            output_dir=out_dir,
            manual_nav_output_dir=manual_out,
            property_output_dir=property_out,
            sg_output_dir=sg_out,
            warning_codes=_dedupe(
                [
                    *validation.warning_codes,
                    WarningCode.PRIVATE_INPUT_CENTER_GENERATION_FAILED,
                ]
            ),
        )

    payload, _ = _load_payload(input_file)
    assert payload is not None
    generated_at = generated_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="personal_cfo_input_center_") as temp_name:
        split_paths = _write_split_inputs(payload, Path(temp_name))
        manual_result = manual_nav_to_provider_bundle(
            input_file=split_paths["manual_nav"],
            out_dir=manual_out,
            env=env,
            generated_at=generated_at,
        )
        property_result = record_property_mortgage_snapshot(
            property_input=split_paths["property"],
            mortgage_input=split_paths["mortgage"],
            out_dir=property_out,
            generated_at=generated_at,
        )
        sg_result = record_sg_manual_snapshot(
            cpf_input=split_paths["cpf"],
            srs_input=split_paths["srs"],
            tax_input=split_paths["tax"],
            hdb_loan_input=split_paths["hdb_loan"],
            out_dir=sg_out,
            generated_at=generated_at,
        )

    validation_warnings = [
        code
        for code in validation.warning_codes
        if code
        not in {
            WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_OK,
            WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS,
        }
    ]
    warnings = _dedupe(
        [
            *validation_warnings,
            *manual_result.warning_codes,
            *property_result.warning_codes,
            *sg_result.warning_codes,
        ]
    )
    generated = manual_result.generated and property_result.generated and sg_result.generated
    completion = (
        WarningCode.PRIVATE_INPUT_CENTER_GENERATED_WITH_WARNINGS
        if generated and warnings
        else WarningCode.PRIVATE_INPUT_CENTER_GENERATED_OK
        if generated
        else WarningCode.PRIVATE_INPUT_CENTER_GENERATION_FAILED
    )
    return PrivateInputCenterSnapshotResult(
        input_file=input_file,
        output_dir=out_dir,
        manual_nav_output_dir=manual_out,
        property_output_dir=property_out,
        sg_output_dir=sg_out,
        manual_nav_result=manual_result,
        property_result=property_result,
        sg_result=sg_result,
        warning_codes=_dedupe([*warnings, completion]),
        generated=generated,
    )


def write_fx_rates_from_private_input_center(
    *, input_file: Path, out_file: Path
) -> Path | None:
    """Extract explicit local FX rates from the unified private input file."""

    payload, _ = _load_payload(input_file)
    if payload is None:
        return None
    fx_rates = payload.get("fx_rates")
    if not isinstance(fx_rates, dict):
        return None
    base_currency = _clean(fx_rates.get("base_currency") or payload.get("base_currency")).upper()
    rates = fx_rates.get("rates_to_base")
    if not base_currency or not isinstance(rates, dict):
        return None
    clean_rates: dict[str, str] = {}
    for currency, rate in rates.items():
        currency_text = _clean(currency).upper()
        rate_text = _clean(rate).replace(",", "")
        rate_value = _parse_amount(rate_text)
        if not currency_text or rate_value is None or rate_value <= 0:
            continue
        clean_rates[currency_text] = rate_text
    clean_rates.setdefault(base_currency, "1.00")
    if len(clean_rates) <= 1:
        return None
    out_file.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        out_file,
        {
            "base_currency": base_currency,
            "rates_to_base": clean_rates,
            "source_type": "local_private_input_center",
            "review_required": True,
        },
    )
    return out_file


def read_expected_source_contract(*, input_file: Path) -> ExpectedSourceContract:
    """Read redacted expected source requirements from unified private input."""

    payload, read_warnings = _load_payload(input_file)
    if payload is None:
        return ExpectedSourceContract(warning_codes=read_warnings)
    return _expected_source_contract_from_payload(payload)


def _load_payload(path: Path) -> tuple[dict[str, Any] | None, list[WarningCode]]:
    if not path.exists():
        return None, [WarningCode.PRIVATE_INPUT_CENTER_INPUT_MISSING]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, [WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID]
    if not isinstance(payload, dict):
        return None, [WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID]
    return payload, []


def _payload_warnings(payload: dict[str, Any]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    for key in ("schema_version", "snapshot_date", "base_currency", "source_type", "review_required"):
        if not _has_value(payload.get(key)):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    if _parse_date(payload.get("snapshot_date")) is None:
        warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    for section in SECTION_KEYS:
        if not isinstance(payload.get(section), list) or not payload.get(section):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_SCHEMA_INVALID)
    if _contains_raw_identifier(payload):
        warnings.append(WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED)
    warnings.extend(_property_warnings(_rows(payload, "properties")))
    warnings.extend(_mortgage_warnings(_rows(payload, "mortgages")))
    warnings.extend(_sg_date_warnings(payload))
    warnings.extend(_expected_source_contract_from_payload(payload).warning_codes)
    return _dedupe(warnings)


def _expected_source_contract_from_payload(
    payload: dict[str, Any]
) -> ExpectedSourceContract:
    contract = payload.get("expected_sources")
    if contract is None:
        return ExpectedSourceContract()
    if not isinstance(contract, dict):
        return ExpectedSourceContract(
            warning_codes=[WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID]
        )

    provider_result = _expected_provider_lists(contract.get("providers"))
    manual_result = _expected_manual_layer_lists(contract.get("manual_layers"))
    warnings = _dedupe([*provider_result[2], *manual_result[2]])
    return ExpectedSourceContract(
        providers_required=provider_result[0],
        providers_optional=provider_result[1],
        manual_layers_required=manual_result[0],
        manual_layers_optional=manual_result[1],
        warning_codes=warnings,
    )


def _expected_provider_lists(
    value: object,
) -> tuple[list[str], list[str], list[WarningCode]]:
    required: set[str] = set()
    optional: set[str] = set()
    warnings: list[WarningCode] = []
    if value is None:
        return [], [], []
    if isinstance(value, dict):
        iterable = [
            {"provider": provider, "required": requirement}
            for provider, requirement in value.items()
        ]
    elif isinstance(value, list):
        iterable = value
    else:
        return [], [], [WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID]

    for item in iterable:
        if isinstance(item, str):
            provider = _clean(item).lower()
            if provider:
                required.add(provider)
            continue
        if not isinstance(item, dict):
            warnings.append(WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID)
            continue
        provider = _clean(item.get("provider") or item.get("name")).lower()
        requirement = _requirement_value(item.get("required", item.get("requirement", True)))
        if not provider or requirement is None:
            warnings.append(WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID)
            continue
        if requirement:
            required.add(provider)
            optional.discard(provider)
        elif provider not in required:
            optional.add(provider)
    return sorted(required), sorted(optional), warnings


def _expected_manual_layer_lists(
    value: object,
) -> tuple[list[str], list[str], list[WarningCode]]:
    required: set[str] = set()
    optional: set[str] = set()
    warnings: list[WarningCode] = []
    if value is None:
        return [], [], []
    if isinstance(value, dict):
        iterable = value.items()
    elif isinstance(value, list):
        iterable = [(item, True) for item in value]
    else:
        return [], [], [WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID]

    for layer_name, requirement_raw in iterable:
        layer = _clean(layer_name).lower()
        requirement = _requirement_value(requirement_raw)
        if layer not in EXPECTED_MANUAL_LAYER_KEYS or requirement is None:
            warnings.append(WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID)
            continue
        if requirement:
            required.add(layer)
            optional.discard(layer)
        elif layer not in required:
            optional.add(layer)
    return sorted(required), sorted(optional), warnings


def _requirement_value(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _clean(value).lower()
    if text in {"required", "require", "yes", "true", "1"}:
        return True
    if text in {"optional", "no", "false", "0", "skip", "not_required"}:
        return False
    return None


def _property_warnings(rows: list[dict[str, Any]]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    required = (
        "property_id_hash",
        "label",
        "type",
        "country",
        "ownership_pct",
        "valuation_amount",
        "currency",
        "valuation_date",
    )
    optional = ("area", "source", "confidence")
    for row in rows:
        if any(not _has_value(row.get(field)) for field in required):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
        if any(not _has_value(row.get(field)) for field in optional):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_OPTIONAL_FIELD_MISSING)
    return warnings


def _mortgage_warnings(rows: list[dict[str, Any]]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    required = ("loan_id_hash", "lender_label", "outstanding_balance", "currency")
    optional = (
        "linked_property_id_hash",
        "interest_rate",
        "rate_type",
        "monthly_payment",
        "repricing_date",
        "maturity_date",
        "snapshot_date",
    )
    for row in rows:
        if any(not _has_value(row.get(field)) for field in required):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
        if any(not _has_value(row.get(field)) for field in optional):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_OPTIONAL_FIELD_MISSING)
    return warnings


def _sg_date_warnings(payload: dict[str, Any]) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    for section in ("cpf", "srs", "hdb_loans"):
        for row in _rows(payload, section):
            if _parse_date(row.get("snapshot_date")) is None:
                warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    for row in _rows(payload, "tax"):
        if not _has_value(row.get("year_of_assessment")):
            warnings.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
    return warnings


def _map_manual_nav_warnings(codes: list[WarningCode]) -> list[WarningCode]:
    mapped: list[WarningCode] = []
    for code in codes:
        if code in {
            WarningCode.MANUAL_NAV_REQUIRED_FIELD_MISSING,
            WarningCode.MANUAL_NAV_SCHEMA_INVALID,
            WarningCode.MANUAL_NAV_INPUT_MISSING,
        }:
            mapped.append(WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING)
        elif code == WarningCode.MANUAL_NAV_RAW_IDENTIFIER_DETECTED:
            mapped.append(WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED)
        elif code in {
            WarningCode.MANUAL_NAV_OPTIONAL_SPLIT_MISSING,
            WarningCode.MANUAL_NAV_MIXED_CURRENCIES,
        }:
            mapped.append(code)
    return mapped


def _write_split_inputs(payload: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "manual_nav": out_dir / "manual_nav_input.local.json",
        "property": out_dir / "property_snapshot.json",
        "mortgage": out_dir / "mortgage_snapshot.json",
        "cpf": out_dir / "cpf_snapshot.json",
        "srs": out_dir / "srs_snapshot.json",
        "tax": out_dir / "tax_snapshot.json",
        "hdb_loan": out_dir / "hdb_loan_snapshot.json",
    }
    _write_json(
        paths["manual_nav"],
        {
            "schema_version": "v0.5.7",
            "snapshot_date": _clean(payload.get("snapshot_date")),
            "base_currency": _clean(payload.get("base_currency")),
            "source_type": _manual_nav_source_type(_clean(payload.get("source_type"))),
            "review_required": payload.get("review_required", True),
            "accounts": _manual_nav_accounts_for_split(payload),
        },
    )
    _write_json(paths["property"], {"properties": _property_rows_for_split(payload)})
    _write_json(paths["mortgage"], {"mortgages": _rows(payload, "mortgages")})
    _write_json(paths["cpf"], {"cpf": _cpf_rows_for_split(payload)})
    _write_json(paths["srs"], {"srs_accounts": _rows(payload, "srs")})
    _write_json(paths["tax"], {"tax_records": _rows(payload, "tax")})
    _write_json(paths["hdb_loan"], {"hdb_loans": _rows(payload, "hdb_loans")})
    return paths


def _manual_nav_accounts_for_split(payload: dict[str, Any]) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    for account in _rows(payload, "manual_nav_accounts"):
        mapped = dict(account)
        provider_label = _manual_nav_provider_label(_clean(mapped.get("provider_label")))
        mapped["provider_label"] = provider_label
        mapped["account_type"] = _manual_nav_account_type(_clean(mapped.get("account_type")))
        mapped["source_type"] = _manual_nav_source_type(_clean(mapped.get("source_type")))
        accounts.append(mapped)
    return accounts


def _manual_nav_provider_label(value: str) -> str:
    return _MANUAL_NAV_PROVIDER_MAP.get(value, value)


def _manual_nav_account_type(value: str) -> str:
    return _MANUAL_NAV_ACCOUNT_TYPE_MAP.get(value, value)


def _manual_nav_source_type(value: str) -> str:
    return _MANUAL_NAV_SOURCE_TYPE_MAP.get(value, value)


def _property_rows_for_split(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _rows(payload, "properties"):
        mapped = dict(row)
        mapped["ownership_pct"] = _property_ownership_for_split(mapped.get("ownership_pct"))
        rows.append(mapped)
    return rows


def _cpf_rows_for_split(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _rows(payload, "cpf"):
        mapped = dict(row)
        cpf_ia = _parse_amount(mapped.get("cpf_ia"))
        cpf_balance = _parse_amount(mapped.get("cpf_balance"))
        if cpf_ia is not None or cpf_balance is not None:
            mapped["total"] = _number_to_text((cpf_ia or 0.0) + (cpf_balance or 0.0))
        rows.append(mapped)
    return rows


def _property_ownership_for_split(value: object) -> str:
    text = _clean(value).replace(",", "")
    if not text or text.endswith("%"):
        return _clean(value)
    try:
        parsed = float(text)
    except ValueError:
        return _clean(value)
    if 1.0 < parsed <= 100.0:
        normalized = parsed / 100.0
        return f"{normalized:.6f}".rstrip("0").rstrip(".")
    return _clean(value)


def _parse_amount(value: object) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _number_to_text(value: float) -> str:
    return f"{value:.2f}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _rows(payload: dict[str, Any], section: str) -> list[dict[str, Any]]:
    rows = payload.get(section)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _section_count(payload: dict[str, Any], section: str) -> int:
    return len(_rows(payload, section))


def _contains_raw_identifier(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                return True
            if _contains_raw_identifier(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_raw_identifier(item) for item in value)
    if isinstance(value, str):
        return bool(_NRIC_PATTERN.search(value))
    return False


def _parse_date(value: object) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _escape_javascript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result
