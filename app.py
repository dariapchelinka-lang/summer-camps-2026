import json
import logging
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from functools import wraps
from hmac import compare_digest

import gspread
from flask import Flask, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from oauth2client.service_account import ServiceAccountCredentials


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SESSION_SECRET") or os.getenv(
    "FLASK_SECRET_KEY", "dev-only-change-this-secret"
)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
is_replit_preview = bool(
    os.getenv("REPLIT_DEV_DOMAIN") or os.getenv("REPLIT_DEPLOYMENT")
)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="None" if is_replit_preview else "Lax",
    SESSION_COOKIE_SECURE=is_replit_preview,
    SESSION_COOKIE_PARTITIONED=is_replit_preview,
)

GOOGLE_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
SHEET_HEADERS = [
    "Дата заявки",
    "ФИО",
    "Обучение на бюджете",
    "Курс",
    "Номер студенческого/аспирантского билета",
    "Номер профсоюзного билета",
    "Ссылка на страницу ВКонтакте",
    "Номер телефона",
    "Адрес электронной почты",
    "Ссылка на аккаунт в Телеграм",
    "Научные достижения",
    "Учебные достижения",
    "Общественные достижения",
    "Спортивные достижения",
    "Культурно-массовые достижения",
    "Ссылка на подтверждения достижений",
]
ADMIN_PERSONAL_FIELDS = [
    ("Обучение на бюджете", "Обучение на бюджете", False),
    ("Курс", "Курс", False),
    (
        "Номер студенческого/аспирантского билета",
        "Номер студенческого/аспирантского билета",
        False,
    ),
    ("Номер профсоюзного билета", "Номер профсоюзного билета", False),
    ("Ссылка на страницу ВКонтакте", "Ссылка на страницу ВКонтакте", True),
    ("Номер телефона", "Номер телефона", False),
    ("Адрес электронной почты", "Адрес электронной почты", False),
    ("Ссылка на аккаунт в Телеграм", "Ссылка на аккаунт в Телеграм", True),
]
ADMIN_ACHIEVEMENT_FIELDS = [
    ("Научные достижения", "Научные достижения", False),
    ("Учебные достижения", "Учебные достижения", False),
    ("Общественные достижения", "Общественные достижения", False),
    ("Спортивные достижения", "Спортивные достижения", False),
    ("Культурно-массовые достижения", "Культурно-массовые достижения", False),
    (
        "Ссылка на подтверждения достижений",
        "Ссылка на подтверждения достижений",
        True,
    ),
]
ADMIN_ACCESS_SALT = "summer-camp-admin-access-v1"
ADMIN_ACCESS_MAX_AGE = 60 * 60


class GoogleSheetsError(RuntimeError):
    """Raised when the application cannot save a submission to Google Sheets."""


def _has_expected_headers(rows):
    return bool(rows) and rows[0][: len(SHEET_HEADERS)] == SHEET_HEADERS


def _ensure_sheet_headers(worksheet):
    """Keep the first row aligned with the form schema without deleting data."""
    rows = worksheet.get_all_values()
    if not rows:
        worksheet.append_row(SHEET_HEADERS, value_input_option="RAW")
    elif not _has_expected_headers(rows):
        worksheet.insert_row(SHEET_HEADERS, index=1, value_input_option="RAW")


def _load_service_account_credentials():
    """Load credentials from a Replit secret or a local JSON file."""
    credentials_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    credentials_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

    if credentials_json:
        try:
            credentials_info = json.loads(credentials_json)
        except json.JSONDecodeError as error:
            raise GoogleSheetsError(
                "Секрет GOOGLE_SERVICE_ACCOUNT_JSON содержит некорректный JSON."
            ) from error
        return ServiceAccountCredentials.from_json_keyfile_dict(
            credentials_info, GOOGLE_SCOPES
        )

    if credentials_file:
        if not os.path.isfile(credentials_file):
            raise GoogleSheetsError(
                f"Файл сервисного аккаунта не найден: {credentials_file}"
            )
        return ServiceAccountCredentials.from_json_keyfile_name(
            credentials_file, GOOGLE_SCOPES
        )

    raise GoogleSheetsError(
        "Не настроены GOOGLE_SERVICE_ACCOUNT_JSON или GOOGLE_SERVICE_ACCOUNT_FILE."
    )


@lru_cache(maxsize=1)
def get_worksheet():
    """Connect to the configured spreadsheet only when the first submission arrives."""
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    worksheet_name = os.getenv("GOOGLE_WORKSHEET_NAME", "Лист1")

    if not spreadsheet_id:
        raise GoogleSheetsError("Не задан обязательный параметр GOOGLE_SHEET_ID.")

    try:
        credentials = _load_service_account_credentials()
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
    except GoogleSheetsError:
        raise
    except Exception as error:
        logger.exception("Google Sheets connection failed")
        raise GoogleSheetsError(
            "Не удалось подключиться к Google Sheets. Проверьте настройки API, "
            "ID таблицы и доступ сервисного аккаунта."
        ) from error

    return worksheet


def save_submission(values):
    """Append one validated form submission to the worksheet."""
    worksheet = get_worksheet()
    try:
        _ensure_sheet_headers(worksheet)

        worksheet.append_row(
            [
                datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                values["name"],
                values["budget"],
                values["course"],
                values["student_ticket"],
                values["union_ticket"],
                values["vk_link"],
                values["phone"],
                values["email"],
                values["telegram_link"],
                values["science"],
                values["education"],
                values["social"],
                values["sport"],
                values["culture"],
                values["achievements_link"],
            ],
            value_input_option="USER_ENTERED",
        )
    except Exception as error:
        logger.exception("Google Sheets append failed")
        raise GoogleSheetsError(
            "Таблица доступна, но запись не выполнена. Проверьте права редактора "
            "и название листа."
        ) from error


def load_submissions():
    """Read submitted rows from the same worksheet used by the public form."""
    worksheet = get_worksheet()
    try:
        rows = worksheet.get_all_values()
    except Exception as error:
        logger.exception("Google Sheets results read failed")
        raise GoogleSheetsError(
            "Не удалось загрузить результаты из Google Sheets. Проверьте доступ "
            "сервисного аккаунта к таблице."
        ) from error

    if not rows:
        return []

    # The first submission may have been saved before the header row existed.
    # Treat such rows as data in the current form's column order.
    data_rows = rows[1:] if _has_expected_headers(rows) else rows
    records = []
    for row in data_rows:
        if not any(str(cell).strip() for cell in row):
            continue
        padded_row = list(row[: len(SHEET_HEADERS)])
        padded_row.extend([""] * (len(SHEET_HEADERS) - len(padded_row)))
        records.append(dict(zip(SHEET_HEADERS, padded_row)))

    grouped = {}
    for record in records:
        fio = str(record.get("ФИО", "")).strip() or "ФИО не указаны"
        grouped.setdefault(fio, []).append(record)

    return [
        {"fio": fio, "submissions": submissions}
        for fio, submissions in grouped.items()
    ]


def _admin_access_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])


def _create_admin_access_token():
    return _admin_access_serializer().dumps(
        {"role": "admin"}, salt=ADMIN_ACCESS_SALT
    )


def _is_valid_admin_access_token(token):
    if not token:
        return False
    try:
        data = _admin_access_serializer().loads(
            token, salt=ADMIN_ACCESS_SALT, max_age=ADMIN_ACCESS_MAX_AGE
        )
    except (BadSignature, SignatureExpired):
        return False
    return data.get("role") == "admin"


def admin_required(view):
    """Protect an admin view with the signed Flask session."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not (
            session.get("admin_authenticated")
            or _is_valid_admin_access_token(request.args.get("admin_access"))
        ):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped_view


def validate_form(form):
    """Return normalized values and a list of user-facing validation errors."""
    values = {
        "name": " ".join(form.get("name", "").split()),
        "budget": form.get("budget", "").strip(),
        "course": form.get("course", "").strip(),
        "student_ticket": form.get("student_ticket", "").strip(),
        "union_ticket": form.get("union_ticket", "").strip(),
        "vk_link": form.get("vk_link", "").strip(),
        "email": form.get("email", "").strip(),
        "phone": form.get("phone", "").strip(),
        "telegram_link": form.get("telegram_link", "").strip(),
        "science": form.get("science", "").strip(),
        "education": form.get("education", "").strip(),
        "social": form.get("social", "").strip(),
        "sport": form.get("sport", "").strip(),
        "culture": form.get("culture", "").strip(),
        "achievements_link": form.get("achievements_link", "").strip(),
    }
    errors = []

    if len(values["name"]) < 2 or len(values["name"]) > 150:
        errors.append("Укажите ФИО длиной от 2 до 150 символов.")
    if values["budget"] not in {"Да", "Нет"}:
        errors.append("Укажите, обучаетесь ли вы на бюджетной основе.")
    if values["course"] not in {"1", "2", "3", "4", "5", "6", "Аспирантура"}:
        errors.append("Выберите номер курса.")
    if not re.fullmatch(r"\d{13}", values["student_ticket"]):
        errors.append("Номер студенческого/аспирантского билета должен состоять из 13 цифр.")
    if not values["union_ticket"] or len(values["union_ticket"]) > 80:
        errors.append("Укажите номер профсоюзного билета.")
    if not values["vk_link"].startswith(("https://vk.com/", "https://vk.ru/")):
        errors.append("Ссылка ВКонтакте должна начинаться с https://vk.com/ или https://vk.ru/.")
    if not re.fullmatch(r"8\d{10}", values["phone"]):
        errors.append("Номер телефона укажите в формате 8XXXXXXXXXX.")
    if (
        not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values["email"])
        or len(values["email"]) > 254
    ):
        errors.append("Введите корректный адрес электронной почты.")
    if not values["telegram_link"].startswith("https://t.me/"):
        errors.append("Ссылка на Телеграм должна начинаться с https://t.me/.")

    achievement_labels = {
        "science": "научные",
        "education": "учебные",
        "social": "общественные",
        "sport": "спортивные",
        "culture": "культурно-массовые",
    }
    for field, label in achievement_labels.items():
        if len(values[field]) < 5 or len(values[field]) > 4000:
            errors.append(
                f"Опишите ваши {label} достижения (от 5 до 4000 символов)."
            )
    if not values["achievements_link"].startswith(("https://", "http://")):
        errors.append("Добавьте ссылку на диск с подтверждениями достижений.")

    return values, errors


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/submit")
def submit():
    # Honeypot field catches simple bots without affecting real users.
    if request.form.get("website", "").strip():
        flash("Спасибо! Ваша заявка принята.", "success")
        return redirect(url_for("success"))

    values, errors = validate_form(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("index.html", form=values), 400

    try:
        save_submission(values)
    except GoogleSheetsError as error:
        flash(str(error), "error")
        return render_template("index.html", form=values), 503

    return redirect(url_for("success"))


@app.get("/success")
def success():
    return render_template("success.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_authenticated"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        admin_password = os.getenv("ADMIN_PASSWORD")
        password = request.form.get("password", "")

        if not admin_password:
            flash(
                "Админ-доступ пока не настроен. Добавьте Secret ADMIN_PASSWORD.",
                "error",
            )
        elif compare_digest(
            password.encode("utf-8"), admin_password.encode("utf-8")
        ):
            session.clear()
            session["admin_authenticated"] = True
            return redirect(
                url_for(
                    "admin_dashboard",
                    admin_access=_create_admin_access_token(),
                )
            )
        else:
            flash("Неверный пароль администратора.", "error")

    return render_template("admin_login.html")


@app.get("/admin")
@admin_required
def admin_dashboard():
    try:
        participants = load_submissions()
    except GoogleSheetsError as error:
        flash(str(error), "error")
        participants = []

    return render_template(
        "admin_dashboard.html",
        participants=participants,
        personal_fields=ADMIN_PERSONAL_FIELDS,
        achievement_fields=ADMIN_ACHIEVEMENT_FIELDS,
    )


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.get("/health")
def health():
    return {"status": "ok", "service": "flask-google-sheets-form"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)