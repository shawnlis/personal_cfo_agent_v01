"""Redacted Webull token and account-permission preflight diagnostics."""

from __future__ import annotations

import importlib
import io
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Callable, Mapping

from personal_cfo_agent.models import WarningCode


@dataclass(frozen=True)
class WebullTokenPreflight:
    sdk_import_ok: bool = False
    sdk_module_detected: str = "unavailable"
    client_constructed: bool = False
    token_preflight_attempted: bool = False
    token_present: bool = False
    token_status_category: str = "UNKNOWN"
    sms_app_verification_required: str = "unknown"
    account_permission_status: str = "unknown"
    account_query_should_proceed: bool = False
    exception_category_sanitized: str = "none"
    warning_codes: tuple[WarningCode, ...] = ()
    stage_failures: dict[str, str] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, object]:
        return {
            "sdk_import_ok": self.sdk_import_ok,
            "sdk_module_detected": self.sdk_module_detected,
            "client_constructed": self.client_constructed,
            "token_preflight_attempted": self.token_preflight_attempted,
            "token_present": self.token_present,
            "token_status_category": self.token_status_category,
            "sms_app_verification_required": self.sms_app_verification_required,
            "account_permission_status": self.account_permission_status,
            "account_query_should_proceed": self.account_query_should_proceed,
            "exception_category_sanitized": self.exception_category_sanitized,
            "warning_codes": [code.value for code in self.warning_codes],
            "stage_failures": dict(self.stage_failures),
        }


def run_webull_token_preflight(
    env: Mapping[str, str],
    *,
    import_module: Callable[[str], object] | None = None,
    token_operation_factory: Callable[[object], object] | None = None,
) -> WebullTokenPreflight:
    importer = import_module or importlib.import_module
    warnings: list[WarningCode] = [WarningCode.WEBULL_TOKEN_PREFLIGHT_ATTEMPTED]
    stage_failures: dict[str, str] = {}
    try:
        core_module = importer("webull.core.client")
        token_module = importer(
            ".".join(
                [
                    "webull",
                    "core",
                    "http",
                    "initializer",
                    "token",
                    "token_operation",
                ]
            )
        )
        api_client_cls = getattr(core_module, "ApiClient")
        operation_cls = getattr(token_module, "TokenOperation")
    except Exception as exc:
        warnings.extend(
            [WarningCode.WEBULL_SDK_NOT_INSTALLED, WarningCode.SDK_NOT_INSTALLED]
        )
        stage_failures["sdk_import"] = (
            f"Webull token preflight SDK import failed ({_safe_exception_name(exc)})"
        )
        return WebullTokenPreflight(
            sdk_import_ok=False,
            token_preflight_attempted=True,
            exception_category_sanitized=_exception_category(exc),
            warning_codes=tuple(_dedupe(warnings)),
            stage_failures=stage_failures,
        )

    try:
        with _suppress_sdk_console_output():
            api_client = api_client_cls(
                env.get("CFO_WEBULL_APP_KEY", ""),
                env.get("CFO_WEBULL_APP_SECRET", ""),
                env.get("CFO_WEBULL_API_HOST", "").strip() or "sg",
                token_check_duration_seconds=1,
                token_check_interval_seconds=1,
            )
            operation = (
                token_operation_factory(api_client)
                if token_operation_factory is not None
                else operation_cls(api_client)
            )
    except Exception as exc:
        warnings.extend(
            [
                WarningCode.WEBULL_CLIENT_INIT_FAILED,
                WarningCode.PROVIDER_CONNECTION_FAILED,
            ]
        )
        stage_failures["client_init"] = (
            f"Webull token preflight client initialization failed ({_safe_exception_name(exc)})"
        )
        return WebullTokenPreflight(
            sdk_import_ok=True,
            sdk_module_detected="webull",
            client_constructed=False,
            token_preflight_attempted=True,
            exception_category_sanitized=_exception_category(exc),
            warning_codes=tuple(_dedupe(warnings)),
            stage_failures=stage_failures,
        )

    try:
        with _suppress_sdk_console_output():
            response = operation.create_token(None)
        payload = _response_payload(response)
    except Exception as exc:
        category = _exception_category(exc)
        warnings.extend(
            [
                WarningCode.WEBULL_TOKEN_STATUS_UNKNOWN,
                WarningCode.WEBULL_ACCOUNT_QUERY_BLOCKED_BY_TOKEN,
            ]
        )
        if category == "auth_failed":
            warnings.append(WarningCode.WEBULL_ACCOUNT_QUERY_AUTH_FAILED)
        elif category == "permission_denied":
            warnings.append(WarningCode.WEBULL_ACCOUNT_PERMISSION_DENIED)
        else:
            warnings.append(WarningCode.WEBULL_ACCOUNT_QUERY_EXCEPTION_SANITIZED)
        stage_failures["token_preflight"] = (
            f"Webull token preflight failed ({_safe_exception_name(exc)})"
        )
        return WebullTokenPreflight(
            sdk_import_ok=True,
            sdk_module_detected="webull",
            client_constructed=True,
            token_preflight_attempted=True,
            token_status_category="UNKNOWN",
            account_permission_status="denied" if category == "permission_denied" else "unknown",
            exception_category_sanitized=category,
            warning_codes=tuple(_dedupe(warnings)),
            stage_failures=stage_failures,
        )

    token_present = bool(str(payload.get("token", "") or "").strip())
    token_status = _token_status(payload.get("status"))
    permission = _account_permission_status(payload)
    verification_required = "yes" if token_status == "PENDING" else "no"
    if token_status == "UNKNOWN":
        verification_required = "unknown"
    warnings.extend(_token_status_warnings(token_status))
    if token_status != "NORMAL":
        warnings.append(WarningCode.WEBULL_ACCOUNT_QUERY_BLOCKED_BY_TOKEN)
    if token_status == "PENDING":
        warnings.append(WarningCode.WEBULL_TOKEN_VERIFICATION_REQUIRED)
    if permission == "denied":
        warnings.extend(
            [
                WarningCode.WEBULL_ACCOUNT_PERMISSION_DENIED,
                WarningCode.WEBULL_ACCOUNT_QUERY_BLOCKED_BY_PERMISSION,
            ]
        )
    elif permission == "unknown":
        warnings.extend(
            [
                WarningCode.WEBULL_ACCOUNT_PERMISSION_UNKNOWN,
                WarningCode.WEBULL_ACCOUNT_QUERY_BLOCKED_BY_PERMISSION,
            ]
        )
    account_query_should_proceed = token_status == "NORMAL" and permission == "yes"
    return WebullTokenPreflight(
        sdk_import_ok=True,
        sdk_module_detected="webull",
        client_constructed=True,
        token_preflight_attempted=True,
        token_present=token_present,
        token_status_category=token_status,
        sms_app_verification_required=verification_required,
        account_permission_status=permission,
        account_query_should_proceed=account_query_should_proceed,
        warning_codes=tuple(_dedupe(warnings)),
        stage_failures=stage_failures,
    )


def _response_payload(response: object) -> Mapping[str, object]:
    if isinstance(response, Mapping):
        return response
    json_method = getattr(response, "json", None)
    if callable(json_method):
        data = json_method()
        if isinstance(data, Mapping):
            return data
    if hasattr(response, "__dict__"):
        return vars(response)
    return {}


def _token_status(value: object) -> str:
    status = str(value or "").strip().upper()
    if status in {"NORMAL", "PENDING", "INVALID", "EXPIRED"}:
        return status
    return "UNKNOWN"


def _token_status_warnings(status: str) -> list[WarningCode]:
    if status == "NORMAL":
        return [WarningCode.WEBULL_TOKEN_STATUS_NORMAL]
    if status == "PENDING":
        return [WarningCode.WEBULL_TOKEN_STATUS_PENDING]
    if status == "INVALID":
        return [WarningCode.WEBULL_TOKEN_STATUS_INVALID]
    if status == "EXPIRED":
        return [WarningCode.WEBULL_TOKEN_STATUS_EXPIRED]
    return [WarningCode.WEBULL_TOKEN_STATUS_UNKNOWN]


def _account_permission_status(payload: Mapping[str, object]) -> str:
    for key in (
        "account_permission",
        "accountPermission",
        "account_service_permission",
        "accountServicePermission",
        "account_query_permission",
        "accountQueryPermission",
    ):
        raw = payload.get(key)
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if value in {"true", "yes", "enabled", "available", "normal", "allowed"}:
            return "yes"
        if value in {"false", "no", "disabled", "denied", "forbidden"}:
            return "denied"
    return "unknown"


def _safe_exception_name(exc: BaseException) -> str:
    return exc.__class__.__name__


def _exception_category(exc: BaseException) -> str:
    name = _safe_exception_name(exc).lower()
    if any(token in name for token in ("auth", "credential", "signature", "token")):
        return "auth_failed"
    if any(token in name for token in ("permission", "forbidden", "denied")):
        return "permission_denied"
    if any(token in name for token in ("http", "endpoint", "request", "response", "server")):
        return "endpoint_failed"
    return "exception_sanitized"


def _dedupe(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result


@contextmanager
def _suppress_sdk_console_output():
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        yield
