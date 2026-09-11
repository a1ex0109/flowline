import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, redirect, url_for, request, session, send_file, jsonify
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_socketio import SocketIO, emit, join_room
import datetime
import time
import random
import uuid
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from dotenv import load_dotenv
import os
import threading
import time
from twilio.rest import Client
import qrcode
from io import BytesIO
import secrets
import json

from database_manager import Session, Provider, ProviderCredentials, ProviderService, ProviderSettings, Appointment, QueueEntry, ProviderSubscription, ProviderStaff, User

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config['REMEMBER_COOKIE_DURATION'] = datetime.timedelta(days=30)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "provider_login_page"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
registration_data = {}
password_reset_data = {}

@login_manager.user_loader
def user_loader(user_id):
    session_db = Session()
    creds = session_db.query(ProviderCredentials).filter_by(provider_id=user_id).first()

    session_db.close()

    if creds:
        return User(creds.provider_id, creds.email)

    return None

@socketio.on("join_room")
def join_room_event(data):
    join_room(data["room"])

def emit_to_user(event, data):
    room = session.get("room_id")
    socketio.emit(event, data, room=room)

@app.route("/", methods=["POST", "GET"])
def index():
    return render_template("index.html")

@app.route("/provider-login-page", methods=["GET"])
def provider_login_page():
    session["room_id"] = f"login_{secrets.token_urlsafe(16)}"
    return render_template("provider-login.html", room_id=session.get("room_id"))

@app.route("/provider-login", methods=["POST", "GET"])
def provider_login():
    email = request.form.get("email")
    password = request.form.get("password")
    remember_me = request.form.get("remember_me") == "true"

    if not email and not password:
        emit_to_user("error", {
            "error": "Bitte gib sowohl E‑Mail als auch Passwort ein."
        })
        return jsonify({"error": "Bitte E‑Mail und Passwort eingeben."}), 400

    session_db = Session()

    creds = session_db.query(ProviderCredentials).filter_by(email=email).first()

    session_db.close()

    if creds is None:
        emit_to_user("error", {"error": "Diese E‑Mail ist nicht registriert."})
        return jsonify({"error": "E‑Mail ist nicht registriert."}), 400

    if not bcrypt.check_password_hash(creds.password_hash, password):
        emit_to_user("error", {
            "error": "E‑Mail oder Passwort ist falsch."
        })
        return jsonify({"error": "E‑Mail oder Passwort ist falsch."}), 400

    user_obj = User(creds.provider_id, creds.email)
    login_user(user_obj, remember=remember_me)

    session["room_id"] = f"provider_{creds.provider_id}"

    return jsonify({"message": "Login erfolgreich."}), 200


@app.route("/register/provider", methods=["GET"])
def provider_register():
    session["room_id"] = f"register_{secrets.token_urlsafe(16)}"
    return render_template("provider-register.html", room_id=session.get("room_id"))

@app.route("/register/provider/submit", methods=["POST", "GET"])
def provider_register_submit():
    email = request.form.get("email")
    owner_name = request.form.get("owner_name")
    business_name = request.form.get("business_name")
    category = request.form.get("category")
    street = request.form.get("street")
    postal_code = request.form.get("postal_code")
    city = request.form.get("city")
    password = request.form.get("password")
    confirm_password = request.form.get("password_repeat")


    reg_token = secrets.token_urlsafe(16)
    registration_data[reg_token] = {
        "email": email,
        "owner_name": owner_name,
        "business_name": business_name,
        "category": category,
        "street": street,
        "postal_code": postal_code,
        "city": city,
        "password": password,
        "password_repeat": confirm_password,
        "created_at": time.time()
    }

    session_db = Session()
    try:
        if password != confirm_password:
            emit_to_user("error", {
                "error": "Das Passwort und die Passwortbestätigung stimmen nicht überein."
            })
            return jsonify({"error": "Passwörter stimmen nicht überein."}), 400

        existing = session_db.query(ProviderCredentials).filter_by(email=email).first()

        if existing:
            emit_to_user("error", {
                "error": "Ein Benutzer mit dieser E‑Mail-Adresse existiert bereits."
            })
            return jsonify({"error": "E‑Mail-Adresse ist bereits registriert."}), 400

        return jsonify({"message": "Registrierungsdaten sind gültig.", "reg_token": reg_token}), 200

    except Exception as e:
        emit_to_user("message", {"message": str(e)})
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/register/provider/code", methods=["GET"])
def register_provider_code_page():
    reg_token = request.args.get("reg_token")

    if reg_token not in registration_data:
        return redirect(url_for("provider-register"))

    return render_template("verify-code.html", submit_url="/register/provider/code/verify", resend_url="/register/provider/code/send", room_id=session.get("room_id"))


@app.route("/register/provider/code/send", methods=["POST", "GET"])
def register_provider_code_send():
    data = request.get_json()
    reg_token = data.get("reg_token")
    reg_data = registration_data.get(reg_token)

    if not reg_data:
        return jsonify({"error": "Der Registrierungsprozess ist abgelaufen. Bitte starte die Registrierung erneut."}), 400

    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    YOUR_EMAIL = os.getenv("SMTP_EMAIL")
    YOUR_APP_PASSWORD = os.getenv("SMTP_PASSWORD")

    try:
        email = reg_data["email"]
        code = "".join(random.choices("0123456789", k=4))

        registration_data[reg_token]["code"] = code
        registration_data[reg_token]["expires"] = time.time() + 300

        text_fallback = f'''
Hallo,

du hast versucht, ein neues Konto auf unserer Terminplattform zu erstellen.

Dein Bestätigungscode lautet:

{code}

Bitte gib diesen Code auf der Verifizierungsseite ein, um deine Registrierung abzuschließen.

Aus Sicherheitsgründen läuft dieser Code in 5 Minuten ab.

Falls du diese Registrierung nicht angefordert hast, kannst du diese Email einfach ignorieren oder uns unter {YOUR_EMAIL} kontaktieren.

Viele Grüße  
Das Flowline-Team  
{YOUR_EMAIL}
'''

        message = f'''
        <html><body style="margin:0;padding:0;background:#f0f2ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px;">
        <tr><td align="center">
          <table width="560" cellpadding="0" cellspacing="0" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
            <tr><td style="background:#2d6a4f;padding:28px 40px;">
              <span style="font-size:20px;font-weight:700;color:white;letter-spacing:-0.3px;">Flowline</span>
            </td></tr>
            <tr><td style="padding:40px;">
              <p style="font-size:14px;color:#6b7280;margin:0 0 24px;">Hallo,</p>
              <h1 style="font-size:22px;font-weight:700;color:#111827;margin:0 0 12px;letter-spacing:-0.4px;">Dein Bestätigungscode</h1>
              <p style="font-size:14px;color:#6b7280;line-height:1.6;margin:0 0 32px;">Um deine Registrierung bei Flowline abzuschließen, gib bitte den folgenden Code ein.</p>
              <div style="background:#f0f2ee;border-radius:12px;padding:28px;text-align:center;margin:0 0 32px;">
                <span style="font-size:36px;font-weight:700;color:#2d6a4f;letter-spacing:12px;">{code}</span>
              </div>
              <p style="font-size:13px;color:#9ca3af;margin:0 0 32px;">Dieser Code läuft in <strong style="color:#6b7280;">5 Minuten</strong> ab.</p>
              <hr style="border:none;border-top:1px solid #f3f4f6;margin:0 0 24px;">
              <p style="font-size:12px;color:#9ca3af;line-height:1.6;margin:0;">Falls du diese Registrierung nicht angefordert hast, kannst du diese E-Mail ignorieren.<br>Bei Fragen erreichst du uns unter <a href="mailto:{YOUR_EMAIL}" style="color:#2d6a4f;">{YOUR_EMAIL}</a>.</p>
            </td></tr>
            <tr><td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #f3f4f6;">
              <p style="font-size:12px;color:#9ca3af;margin:0;">© 2026 Flowline · <a href="mailto:{YOUR_EMAIL}" style="color:#9ca3af;">Kontakt</a></p>
            </td></tr>
          </table>
        </td></tr>
        </table>
        </body></html>
        '''

        msg = EmailMessage()
        msg.set_content(text_fallback)
        msg.add_alternative(message, subtype='html')
        msg["Subject"] = "Ihr Verifizierungscode für die Registrierung – Flowline"
        msg["From"] = YOUR_EMAIL
        msg["To"] = email

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(YOUR_EMAIL, YOUR_APP_PASSWORD)
            server.send_message(msg)

        return jsonify({"message": "Der Verifizierungscode wurde erfolgreich versendet."}), 200

    except smtplib.SMTPRecipientsRefused:
        emit_to_user("error", {
            "error": "Es gibt keinen Account mit dieser E‑Mail-Adresse."
        })
        return jsonify({"error": "Die E‑Mail konnte nicht zugestellt werden."}), 500


@app.route("/register/provider/code/verify", methods=["POST"])
def register_provider_code_verify():
    code = request.form.get("verification_code")
    reg_token = request.form.get("reg_token")

    if not reg_token or reg_token not in registration_data:
        emit_to_user("error", {
            "error": "Der Registrierungsprozess ist abgelaufen. Bitte starte die Registrierung erneut."
        })
        return jsonify(
            {"error": "Der Registrierungsprozess ist abgelaufen."}), 400

    verif_code = registration_data[reg_token]["code"]
    expires = registration_data[reg_token]["expires"]

    #if expires is None or verif_code is None:
        #registration_data.pop(reg_token, None)
        #return jsonify({"error": "Code abgelaufen."}), 400

    if time.time() > expires:
        emit_to_user("error", {"error": "Der Code ist abgelaufen. Bitte starte die Registrierung erneut."})
        registration_data.pop(reg_token, None)
        return jsonify({"error": "Code abgelaufen."}), 400

    if code != verif_code:
        emit_to_user("error", {"error": "Dieser Code stimmt nicht. Bitte überprüfe deine Eingabe."})
        return jsonify({"error": "Der Verifizierungscode ist falsch."}), 400

    password_hash = bcrypt.generate_password_hash(registration_data[reg_token]["password"]).decode()

    session_db = Session()

    new_provider = Provider(
        owner_name=registration_data[reg_token]["owner_name"],
        business_name=registration_data[reg_token]["business_name"],
        category=registration_data[reg_token]["category"],
        street=registration_data[reg_token]["street"],
        postal_code=registration_data[reg_token]["postal_code"],
        city=registration_data[reg_token]["city"],
    )

    session_db.add(new_provider)
    session_db.flush()

    new_credentials = ProviderCredentials(
        provider_id=new_provider.id,
        email=registration_data[reg_token]["email"],
        password_hash=password_hash
    )

    session_db.add(new_credentials)
    session_db.flush()

    settings = ProviderSettings(
        provider_id=new_provider.id,
        queue_token=secrets.token_urlsafe(16)
    )

    session_db.add(settings)
    session_db.flush()

    subscription = ProviderSubscription(
        provider_id=new_provider.id,
    )

    session_db.add(subscription)
    session_db.flush()

    staff = ProviderStaff(
        provider_id=new_provider.id,
        name=registration_data[reg_token]["owner_name"],
        is_owner=True,
    )

    session_db.add(staff)
    session_db.commit()

    user_obj = User(new_provider.id, registration_data[reg_token]["email"])
    login_user(user_obj)

    session_db.close()

    registration_data.pop(reg_token, None)
    return jsonify({"message": "Verifizierung erfolgreich."}), 200

@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "GET":
        return render_template("onboarding.html")

    # POST
    session_db = Session()
    try:
        data = request.get_json()
        services = data.get("services", [])

        if not services:
            emit_to_user("error", {"error": "Bitte füge mindestens einen Service hinzu, bevor du fortfährst."})
            return jsonify({"error": "Mindestens ein Service erforderlich."}), 400

        for s in services:
            name = s.get("name", "").strip()
            duration = s.get("duration")
            if not name or not duration:
                emit_to_user("error", {"error": "Bitte gib für jeden Service einen Namen und eine Dauer an."})
                return jsonify({"error": "Ungültige Service-Daten"}), 400

            session_db.add(ProviderService(
                provider_id=current_user.id,
                name=name,
                duration_minutes=int(duration)
            ))

        session_db.commit()

        return jsonify({"redirect": "/onboarding/staff"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()


@app.route("/onboarding/staff", methods=["GET", "POST"])
@login_required
def onboarding_staff():
    if request.method == "GET":
        return render_template("onboarding_staff.html")

    session_db = Session()
    try:
        data = request.get_json()
        staff_members = data.get("staff", [])

        for name in staff_members:
            name = name.strip()
            if not name:
                continue
            session_db.add(ProviderStaff(
                provider_id=current_user.id,
                name=name,
                is_owner=False
            ))

            session_db.commit()

        return jsonify({"redirect": "/dashboard"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/password-reset", methods=["POST", "GET"])
def password_reset():
    session["room_id"] = f"reset_{secrets.token_urlsafe(16)}"

    return render_template("password-reset.html", room_id=session.get("room_id"))

@app.route("/password-reset/enter-code", methods=["POST", "GET"])
def password_reset_verify_code():

    return render_template("verify-code.html", submit_url="/password-reset/check-password", resend_url="/password-reset/verify", room_id=session.get("room_id"))

@app.route("/password-reset/verify", methods=["POST"])
def password_reset_verify():
    reset_email_address = request.form.get("email")
    reset_token = request.form.get("reset_token")

    if not reset_token or reset_token not in password_reset_data:
        reset_token = secrets.token_urlsafe(16)

    email = reset_email_address or password_reset_data.get(reset_token, {}).get("email")

    if not email:
        return jsonify({"error": "E‑Mail fehlt."}), 400

    session_db = Session()
    creds = session_db.query(ProviderCredentials).filter_by(email=email).first()
    session_db.close()

    if not creds:
        emit_to_user("error", {
            "error": "Zu dieser E‑Mail existiert kein Konto."
        })
        return jsonify({"error": "Kein Konto mit dieser E‑Mail gefunden."}), 400

    verification_code = "".join(random.choices("0123456789", k=4))

    password_reset_data[reset_token] = {
        "email": email,
        "code": verification_code,
        "expires": time.time() + 300,
        "created_at": time.time()
    }

    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    YOUR_EMAIL = os.getenv("SMTP_EMAIL")
    YOUR_APP_PASSWORD = os.getenv("SMTP_PASSWORD")

    text_fallback = f'''
Hallo,

du hast angefragt, dein Passwort zurückzusetzen.

Dein Bestätigungscode lautet:

{verification_code}

Der Code ist 5 Minuten gültig.

Falls du diese Anfrage nicht gestellt hast, ignoriere diese E-Mail.

Viele Grüße  
Flowline-Team
'''

    message = f'''
    <html><body style="margin:0;padding:0;background:#f0f2ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <tr><td style="background:#2d6a4f;padding:28px 40px;">
          <span style="font-size:20px;font-weight:700;color:white;letter-spacing:-0.3px;">Flowline</span>
        </td></tr>
        <tr><td style="padding:40px;">
          <p style="font-size:14px;color:#6b7280;margin:0 0 24px;">Hallo,</p>
          <h1 style="font-size:22px;font-weight:700;color:#111827;margin:0 0 12px;letter-spacing:-0.4px;">Passwort zurücksetzen</h1>
          <p style="font-size:14px;color:#6b7280;line-height:1.6;margin:0 0 32px;">Wir haben eine Anfrage erhalten, dein Passwort zurückzusetzen. Gib den folgenden Code ein um fortzufahren.</p>
          <div style="background:#f0f2ee;border-radius:12px;padding:28px;text-align:center;margin:0 0 32px;">
            <span style="font-size:36px;font-weight:700;color:#2d6a4f;letter-spacing:12px;">{verification_code}</span>
          </div>
          <p style="font-size:13px;color:#9ca3af;margin:0 0 32px;">Dieser Code läuft in <strong style="color:#6b7280;">5 Minuten</strong> ab.</p>
          <hr style="border:none;border-top:1px solid #f3f4f6;margin:0 0 24px;">
          <p style="font-size:12px;color:#9ca3af;line-height:1.6;margin:0;">Falls du diese Anfrage nicht gestellt hast, ignoriere diese E-Mail einfach.<br>Dein Passwort bleibt unverändert.<br>Bei Fragen erreichst du uns unter <a href="mailto:{YOUR_EMAIL}" style="color:#2d6a4f;">{YOUR_EMAIL}</a>.</p>
        </td></tr>
        <tr><td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #f3f4f6;">
          <p style="font-size:12px;color:#9ca3af;margin:0;">© 2026 Flowline · <a href="mailto:{YOUR_EMAIL}" style="color:#9ca3af;">Kontakt</a></p>
        </td></tr>
      </table>
    </td></tr>
    </table>
    </body></html>
    '''

    msg = EmailMessage()
    msg.set_content(text_fallback)
    msg.add_alternative(message, subtype='html')
    msg["Subject"] = "Dein Code zum Zurücksetzen deines Passworts"
    msg["From"] = YOUR_EMAIL
    msg["To"] = email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(YOUR_EMAIL, YOUR_APP_PASSWORD)
        server.send_message(msg)

    emit_to_user("message", {
        "message": "Der Bestätigungscode wurde versendet."
    })
    return jsonify({"message": "Der Bestätigungscode wurde versendet.", "reset_token": reset_token}), 200

@app.route("/password-reset/check-password", methods=["POST", "GET"])
def passwort_reset_check():
    code = request.form.get("verification_code")

    reset_token = request.form.get("reset_token")

    if not reset_token or reset_token not in password_reset_data:
        emit_to_user("error", {
            "error": "Die Passwort‑Zurücksetzung ist abgelaufen. Bitte starte erneut."
        })
        return jsonify({"error": "Die Passwort‑Zurücksetzung ist abgelaufen."}), 400

    email = password_reset_data[reset_token]["email"]
    reset_code = password_reset_data[reset_token]["code"]
    expires = password_reset_data[reset_token]["expires"]

    if not email or not reset_code or not expires:
        emit_to_user("error", {
            "error": "Dein Code ist abgelaufen. Bitte beginne den Vorgang erneut."
        })
        return jsonify({"error": "Code abgelaufen."}), 400

    if time.time() > expires:
        emit_to_user("error", {
            "error": "Dein Code ist abgelaufen. Bitte beginne den Vorgang erneut."
        })
        password_reset_data.pop(reset_token, None)
        return jsonify({"error": "Code abgelaufen."}), 400

    if code == reset_code:
        return jsonify({"message": "Code ist gültig."}), 200

    emit_to_user("error", {
        "error": "Dieser Code stimmt nicht. Bitte überprüfe deine Eingabe."
    })
    return jsonify({"error": "Code ist ungültig."}), 400


@app.route("/password-update", methods=["POST", "GET"])
def password_update():
    session["room_id"] = f"pw_update_{secrets.token_urlsafe(16)}"

    return render_template("password-update.html", room_id=session.get("room_id"))

@app.route("/password-update/confirm", methods=["POST", "GET"])
def password_update_confirm():
    password = request.form.get("password")
    password_repeat = request.form.get("password_repeat")

    reset_token = request.form.get("reset_token")

    if not reset_token or reset_token not in password_reset_data:
        emit_to_user("error", {
            "error": "Die Passwort‑Zurücksetzung ist abgelaufen. Bitte starte erneut."
        })
        return jsonify({"error": "Die Passwort‑Zurücksetzung ist abgelaufen."}), 400

    email = password_reset_data[reset_token]["email"]
    reset_code = password_reset_data[reset_token]["code"]
    expires = password_reset_data[reset_token]["expires"]

    if not email or not reset_code or not expires:
        emit_to_user("error", {
            "error": "Die Passwort‑Zurücksetzung ist abgelaufen. Bitte starte erneut."
        })
        return jsonify({"error": "Passwort‑Zurücksetzung abgelaufen."}), 400

    if time.time() > expires:
        emit_to_user("error", {
            "error": "Die Passwort‑Zurücksetzung ist abgelaufen. Bitte starte erneut."
        })
        password_reset_data.pop(reset_token, None)
        return jsonify({"error": "Passwort‑Zurücksetzung abgelaufen."}), 400

    if password != password_repeat:
        emit_to_user("error", {
            "error": "Das Passwort und die Passwortbestätigung stimmen nicht überein."
        })
        return jsonify({"error": "Passwörter stimmen nicht überein."}), 400


    session_db = Session()

    creds = session_db.query(ProviderCredentials).filter_by(email=email).first()

    if bcrypt.check_password_hash(creds.password_hash, password):
        emit_to_user("error", {
            "error": "Das neue Passwort darf nicht mit dem bisherigen übereinstimmen."
        })
        return jsonify({"error": "Neues Passwort entspricht dem alten."}), 400

    new_hash = bcrypt.generate_password_hash(password).decode()

    creds.password_hash = new_hash

    session_db.commit()

    session_db.close()

    password_reset_data.pop(reset_token, None)

    return jsonify({"message": "Passwort wurde erfolgreich aktualisiert."}), 200

@app.route("/dashboard")
def dashboard():
    if not current_user.is_authenticated:
        return redirect("/login")

    session_db = Session()

    services = session_db.query(ProviderService).filter_by(
        provider_id=current_user.id
    ).all()

    session_db.close()
    print(session.get("room_id"), "room_id")
    return render_template("dashboard.html", room_id=session.get("room_id"), services=services)

@app.route("/dashboard/appointments", methods=["POST", "GET"])
@login_required
def appointments():
    provider_id = current_user.id

    customer_name = request.form.get("customer_name")

    start_datetime = datetime.datetime.fromisoformat(
        request.form.get("appointment_datetime")
    ).astimezone() # str -> datetime

    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    phone_number = request.form.get("appointment_phone")
    customer_email = request.form.get("appointment_email")
    services = request.form.getlist("services[]")
    custom_duration = request.form.get("custom_duration", None)
    notes = request.form.get("appointment_notes")

    session_db = Session()
    try:
        if custom_duration == "":
            emit_to_user("error", {"error": "Bitte eine gültige Dauer eingeben."})
            return jsonify({"error": "Custom-Dauer fehlt."}), 400

        if not services and custom_duration is None:
            emit_to_user("error", {"error": "Bitte mindestens einen Service auswählen."})
            return jsonify({"error": "Kein Service ausgewählt."}), 400

        duration_list = []

        for s in services:
            service = session_db.query(ProviderService).filter_by(
                id=int(s),
                provider_id=provider_id
            ).first()

            if not service:
                emit_to_user("error", {"error": "Ein ausgewählter Service existiert nicht."})
                return jsonify({"error": "Service nicht gefunden."}), 400

            duration_list.append(service.duration_minutes)

        if custom_duration:
            duration_list.append(int(custom_duration))

        total_duration = sum(duration_list)
        end_datetime = (start_datetime + datetime.timedelta(minutes=total_duration)).astimezone()

        if has_conflict(provider_id, start_datetime, end_datetime):
            emit_to_user("error", {
                "error": "Dieser Zeitraum ist bereits vergeben."
            })
            return jsonify({"error": "Zeit bereits belegt."}), 400

        if start_datetime >= now:
            new_appointment = Appointment(
                provider_id=provider_id,
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                start=start_datetime,
                end=end_datetime,
                duration_minutes=total_duration,
                notes=notes,
                services_json=json.dumps(services),
                custom_duration=custom_duration if custom_duration else None,
                status="pending"
            )

            session_db.add(new_appointment)
            session_db.commit()

            emit_to_user("message", {
                "message": "Termin wurde erfolgreich erstellt."
            })
            return jsonify({"message": "Termin erstellt."}), 200

        emit_to_user("error", {
            "error": "Der Termin kann nicht in der Vergangenheit erstellt werden."
        })
        return jsonify({"error": "Der Termin liegt in der Vergangenheit."}), 400

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Beim Erstellen des Termins ist ein Fehler aufgetreten.",
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/appointments/<int:appointment_id>/edit", methods=["POST", "GET"])
@login_required
def edit_appointment(appointment_id):
    provider_id = current_user.id

    customer_name = request.form.get("customer_name")
    start_datetime = datetime.datetime.fromisoformat(
        request.form.get("appointment_datetime")
    ).astimezone()

    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    phone_number = request.form.get("appointment_phone")
    customer_email = request.form.get("appointment_email")

    services = request.form.getlist("services[]")
    custom_duration = request.form.get("custom_duration")

    notes = request.form.get("appointment_notes")

    session_db = Session()
    try:
        if not services or not custom_duration:
            emit_to_user("error", {"error": "Bitte mindestens einen Service auswählen."})
            return jsonify({"error": "Kein Service ausgewählt."}), 400

        duration_list = []

        for s in services:
            service = session_db.query(ProviderService).filter_by(
                id=int(s),
                provider_id=provider_id
            ).first()

            if not service:
                emit_to_user("error", {"error": "Ein ausgewählter Service existiert nicht."})
                return jsonify({"error": "Service nicht gefunden."}), 400

            duration_list.append(service.duration_minutes)

        duration_list.append(int(custom_duration))

        total_duration = sum(duration_list)
        end_datetime = (start_datetime + datetime.timedelta(minutes=total_duration)).astimezone()

        if has_conflict(provider_id, start_datetime, end_datetime, appointment_id):
            emit_to_user("error", {"error": "Dieser Zeitraum ist bereits vergeben."})
            return jsonify({"error": "Zeit bereits belegt."}), 400

        appointment = session_db.query(Appointment).filter_by(
            id=appointment_id,
            provider_id=provider_id
        ).first()

        if not appointment:
            emit_to_user("error", {"error": "Der Termin wurde erfolgreich aktualisiert."})
            return jsonify({"error": "Termin nicht gefunden."}), 404

        current_status = appointment.status if appointment else 'pending'

        if start_datetime != appointment.start.astimezone():
            if appointment.start.astimezone() <= now:
                emit_to_user("error", {"error": "Vergangene oder laufende Termine können nicht verschoben werden."})
                return jsonify({"error": "Der Termin liegt in der Vergangenheit."}), 400

            if start_datetime < now:
                emit_to_user("error", {"error": "Der Termin kann nicht in die Vergangenheit verschoben werden."})
                return jsonify({"error": "Der Termin liegt in der Vergangenheit."}), 400

        appointment.customer_name = customer_name
        appointment.start = start_datetime
        appointment.end = end_datetime
        appointment.duration_minutes = total_duration
        appointment.customer_phone = phone_number
        appointment.customer_email = customer_email
        appointment.notes = notes

        appointment.services_json = json.dumps(services)
        appointment.custom_duration = custom_duration

        appointment.status = current_status

        session_db.commit()

        emit_to_user("message", {"message": "Termin erfolgreich aktualisiert."})
        return jsonify({"message": "Termin aktualisiert."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {"error": "Beim Aktualisieren des Termins ist ein Fehler aufgetreten."})
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()


def has_conflict(provider_id, start, end, exclude_appointment_id=None):
    session_db = Session()

    #rows = cursor.execute("""
        #SELECT appointment_id, start, end
        #FROM appointments_table
        #WHERE provider_id = ?
          #AND status NOT IN ('no_show', 'completed')
    #""", (provider_id,)).fetchall()

    appointments = session_db.query(Appointment).filter(
        Appointment.provider_id == provider_id,
        Appointment.status.not_in(["no_show", "completed"])
    ).all()

    if not appointments:
        return False

    for a in appointments:
        if exclude_appointment_id and a.id == exclude_appointment_id:
            continue

        if start < a.end.astimezone() and end > a.start.astimezone():
            return True

    # 2. Walk‑ins prüfen (nur assigned)

    queues = session_db.query(QueueEntry).filter(
        QueueEntry.provider_id == provider_id,
        QueueEntry.status.in_(["assigned", "in_progress"])
    ).all()

    session_db.close()

    for q in queues:
        if not q.start:
            continue

        if start < q.end.astimezone() and end > q.start.astimezone():
            return True

    return False


@app.route("/dashboard/appointments/<int:appointment_id>/<string:type>/move", methods=["PATCH"])
@login_required
def move_appointment(appointment_id, type):
    data = request.get_json()
    new_start = datetime.datetime.fromisoformat(data.get("start")).astimezone()
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    if type == "Walk-in":
        emit_to_user("error", {
            "error": "Walk‑ins ordnen sich automatisch ein und können nicht verschoben werden."
        })
        return jsonify({"error": "Walk‑ins nicht verschiebbar."}), 400


    session_db = Session()
    try:
        appointment = session_db.query(Appointment).filter_by(id=appointment_id, provider_id=current_user.id).first()

        if not appointment:
            emit_to_user("error", {
                "error": "Der Termin wurde nicht gefunden.",
            })
            return jsonify({"error": "Termin nicht gefunden."}), 404

        if appointment.start.astimezone() <= now:
            emit_to_user("error", {
                "error": "Vergangene oder laufende Termine können nicht verschoben werden."
            })
            return jsonify({"error": "Der Termin liegt in der Vergangenheit."}), 400

        if new_start < now:
            emit_to_user("error", {
                "error": "Der Termin kann nicht in die Vergangenheit verschoben werden."
            })
            return jsonify({"error": "Der Termin liegt in der Vergangenheit."}), 400

        duration_delta = datetime.timedelta(minutes=appointment.duration_minutes)
        end = new_start + duration_delta


        appointment.start = new_start
        appointment.end = end

        session_db.commit()

        emit_to_user("message", {
            "message": "Termin erfolgreich aktualisiert."
        })
        return jsonify({"message": "Termin aktualisiert."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Beim Aktualisieren des Termins ist ein Fehler aufgetreten.",
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/appointments/<int:appointment_id>/<string:type>/resize", methods=["PATCH"])
@login_required
def resize_appointment(appointment_id, type):
    data = request.get_json()
    start = datetime.datetime.fromisoformat(data.get("start")).astimezone()
    end = datetime.datetime.fromisoformat(data.get("end")).astimezone()
    diff = int((end - start).total_seconds() / 60)

    session_db = Session()
    try:
        if type == "Termin":
            appointment = session_db.query(Appointment).filter_by(
                id=appointment_id,
                provider_id=current_user.id
            ).first()

            if not appointment:
                emit_to_user("error", {"error": "Der Termin wurde nicht gefunden."})
                return jsonify({"error": "Termin nicht gefunden."}), 404

            appointment.start = start
            appointment.end = end
            appointment.duration_minutes = diff

            session_db.commit()

            emit_to_user("message", {
                "message": "Termin erfolgreich aktualisiert."
            })
            return jsonify({"message": "Termin aktualisiert."}), 200

        else:
            queue = session_db.query(QueueEntry).filter_by(
                id=appointment_id,
                provider_id=current_user.id
            ).first()

            if not queue:
                emit_to_user("error", {"error": "Der Walk-in wurde nicht gefunden."})
                return jsonify({"error": "Walk-in nicht gefunden."}), 404

            queue.start = start
            queue.end = end
            queue.duration_minutes = diff

            session_db.commit()

            emit_to_user("message", {
                "message": "Walk-in erfolgreich aktualisiert."
            })
            return jsonify({"message": "Walk-in aktualisiert."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Beim Aktualisieren des Termins ist ein Fehler aufgetreten.",
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/appointments/<int:appointment_id>/delete", methods=["DELETE"])
@login_required
def delete_appointment(appointment_id):
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    session_db = Session()
    try:
        appointment = session_db.query(Appointment).filter_by(
            id=appointment_id,
            provider_id=current_user.id
        ).first()

        if not appointment:
            emit_to_user("error", {
                "error": "Der Termin wurde nicht gefunden."
            })
            return jsonify({"error": "Termin nicht gefunden."}), 400

        if appointment.start.astimezone() <= now:
            emit_to_user("error", {
                "error": "Vergangene oder laufende Termine können nicht gelöscht werden."
            })
            return jsonify({"error": "Termin liegt in der Vergangenheit."}), 400

        session_db.delete(appointment)
        session_db.commit()

        emit_to_user("message", {
            "message": "Termin erfolgreich gelöscht."
        })
        return jsonify({"message": "Termin gelöscht."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Termin konnte nicht gelöscht werden.",
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()


@app.route("/dashboard/appointments/today", methods=["GET"])
@login_required
def appointments_today():
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)
    today = now.date()

    day_start = datetime.datetime.combine(today, datetime.time.min)
    day_end = datetime.datetime.combine(today, datetime.time.max)

    session_db = Session()

    appointments = session_db.query(Appointment).filter(
        Appointment.start.between(day_start, day_end),
        Appointment.provider_id == current_user.id,
        Appointment.status.not_in(["no_show"])
    ).all()

    appointments_fc = []

    for a in appointments:
        try:
            service_ids = json.loads(a.services_json)
        except:
            service_ids = []

        services = session_db.query(ProviderService).filter(
            ProviderService.id.in_(service_ids)
        ).all()

        service_names = " + ".join([s.name for s in services]) if services else None

        if a.custom_duration:
            if service_names:
                service_names += f" + Custom ({a.custom_duration} Min)"
            else:
                service_names = f"Custom ({a.custom_duration} Min)"

        appointments_fc.append({
            "title": a.customer_name,
            "start": a.start.astimezone(),
            "end": a.end.astimezone(),
            "extendedProps": {
                "duration": a.duration_minutes,
                "service": service_names,
                "status": a.status
            }
        })

    session_db.close()

    return jsonify({
        "date": today,
        "appointments": appointments_fc
    })



@app.route("/dashboard/appointments/next", methods=["GET"])
@login_required
def next_appointment():
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    session_db = Session()

    appointments = session_db.query(Appointment).filter(
        Appointment.provider_id == current_user.id,
        Appointment.start > now,
        Appointment.status != "completed"
    ).all()

    appointments_fc = []

    for a in appointments:
        try:
            service_ids = json.loads(a.services_json)
        except:
            service_ids = []

        # Alle Services laden
        services = session_db.query(ProviderService).filter(
            ProviderService.id.in_(service_ids)
        ).all()

        service_names = " + ".join([s.name for s in services]) if services else None

        if a.custom_duration:
            if service_names:
                service_names += f" + Custom ({a.custom_duration} Min)"
            else:
                service_names = f"Custom ({a.custom_duration} Min)"

        appointments_fc.append({
            "title": a.customer_name,
            "start": a.start.astimezone(),
            "end": a.end.astimezone(),
            "extendedProps": {
                "type": "Termin",
                "duration": a.duration_minutes,
                "service": service_names,
                "status": a.status
            }
        })

    queues = session_db.query(QueueEntry).filter(
        QueueEntry.provider_id == current_user.id,
        QueueEntry.start > now,
        QueueEntry.status != "completed"
    ).all()

    queues_fc = []

    for q in queues:
        try:
            service_ids = json.loads(q.services_json)
        except:
            service_ids = []

        services = session_db.query(ProviderService).filter(
            ProviderService.id.in_(service_ids)
        ).all()

        service_names = " + ".join([s.name for s in services]) if services else None

        if q.custom_duration:
            if service_names:
                service_names += f" + Custom ({q.custom_duration} Min)"
            else:
                service_names = f"Custom ({q.custom_duration} Min)"

        queues_fc.append({
            "title": q.customer_name,
            "start": q.start.astimezone(),
            "end": q.end.astimezone(),
            "extendedProps": {
                "type": "Walk-in",
                "duration": q.duration_minutes,
                "service": service_names,
                "status": q.status
            }
        })

    session_db.close()

    combined = appointments_fc + queues_fc
    combined.sort(key=lambda x: x["start"])

    return jsonify({
        "appointments": combined
    })



@app.route("/dashboard/appointments/current", methods=["GET"])
@login_required
def current_appointment():
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    session_db = Session()

    appointment = session_db.query(Appointment).filter(
        Appointment.provider_id == current_user.id,
        Appointment.start <= now,
        Appointment.end >= now,
        Appointment.status.not_in(["completed", "no_show"])
    ).first()

    walkin = session_db.query(QueueEntry).filter(
        QueueEntry.provider_id == current_user.id,
        QueueEntry.start <= now,
        QueueEntry.end >= now,
        QueueEntry.status.in_(["assigned", "in_progress"])
    ).first()

    if appointment:
        try:
            service_ids = json.loads(appointment.services_json)
        except:
            service_ids = []

        services = session_db.query(ProviderService).filter(
            ProviderService.id.in_(service_ids)
        ).all()

        service_names = " + ".join([s.name for s in services]) if services else None

        if appointment.custom_duration:
            if service_names:
                service_names += f" + Custom ({appointment.custom_duration} Min)"
            else:
                service_names = f"Custom ({appointment.custom_duration} Min)"

        session_db.close()

        return jsonify({
            "type": "Termin",
            "data": {
                "id": appointment.id,
                "title": appointment.customer_name,
                "start": appointment.start.astimezone(),
                "end": appointment.end.astimezone(),
                "extendedProps": {
                    "duration": appointment.duration_minutes,
                    "service": service_names,
                    "status": appointment.status
                }
            }
        })

    if walkin:
        try:
            service_ids = json.loads(walkin.services_json)
        except:
            service_ids = []

        services = session_db.query(ProviderService).filter(
            ProviderService.id.in_(service_ids)
        ).all()

        service_names = " + ".join([s.name for s in services]) if services else None

        if walkin.custom_duration:
            if service_names:
                service_names += f" + Custom ({walkin.custom_duration} Min)"
            else:
                service_names = f"Custom ({walkin.custom_duration} Min)"

        session_db.close()

        return jsonify({
            "type": "Walk-in",
            "data": {
                "id": walkin.id,
                "title": walkin.customer_name,
                "start": walkin.start.astimezone(),
                "end": walkin.end.astimezone(),
                "extendedProps": {
                    "duration": walkin.duration_minutes,
                    "service": service_names,
                    "status": walkin.status
                }
            }
        })

    session_db.close()

    return jsonify({
        "type": None,
        "data": None
    })



@app.route("/dashboard/appointments/<string:type>/<int:id>/update-status", methods=["PATCH"])
@login_required
def update_status(type, id):
    data = request.get_json()
    status = data.get("status")

    session_db = Session()
    try:
        # 1. Termin oder Walk‑in laden
        if type == "Termin":
            entry = session_db.query(Appointment).filter_by(
                id=id,
                provider_id=current_user.id
            ).first()
        else:
            entry = session_db.query(QueueEntry).filter_by(
                id=id,
                provider_id=current_user.id
            ).first()

        if not entry:
            emit_to_user("error", {"error": "Eintrag nicht gefunden."})
            return jsonify({"error": "Eintrag nicht gefunden."}), 404

        # 2. Status aktualisieren
        entry.status = status

        if type == "Walk-in" and status == "completed":
            settings = session_db.query(ProviderSettings).filter_by(
                provider_id=current_user.id
            ).first()

            if settings and settings.sms_enabled:
                next_entry = session_db.query(QueueEntry).filter_by(
                    provider_id=current_user.id,
                    status="pending"
                ).order_by(QueueEntry.position.asc()).first()

                provider = session_db.query(Provider).filter_by(
                    id=current_user.id
                ).first()

                if next_entry and next_entry.customer_phone:
                    result = send_sms(
                        current_user.id,
                        next_entry.customer_phone,
                        f"Du bist als Nächstes dran bei {provider.business_name}. Bitte komm rein. 💈"
                    )
                    if result and result["success"]:
                        settings.sms_credits_used += 1
                        session_db.commit()



        # 3. Wenn ein Termin/Walk‑in auf "in_progress" gesetzt wird:
        #    → alle anderen aktiven Einträge zurücksetzen
        if status == "in_progress":
            session_db.query(Appointment).filter(
                Appointment.provider_id == current_user.id,
                Appointment.status == "in_progress",
                Appointment.id != entry.id
            ).update({Appointment.status: "assigned"})

            session_db.query(QueueEntry).filter(
                QueueEntry.provider_id == current_user.id,
                QueueEntry.status == "in_progress",
                QueueEntry.id != entry.id
            ).update({QueueEntry.status: "assigned"})

        session_db.commit()

        emit_to_user("message", {"message": "Status aktualisiert."})
        return jsonify({"message": "Status aktualisiert"}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {"error": "Ein Fehler ist aufgetreten."})
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()


@app.route("/dashboard/queue/add", methods=["POST"])
@login_required
def add_to_queue():
    customer_name = request.form.get("customer_name")
    phone_number = request.form.get("queue_phone")
    services = request.form.getlist("services[]")
    custom_duration = request.form.get("custom_duration", None)
    created_at = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")

    session_db = Session()
    try:
        if custom_duration == "":
            emit_to_user("error", {"error": "Bitte eine gültige Dauer eingeben."})
            return jsonify({"error": "Custom-Dauer fehlt."}), 400

        if not services and custom_duration is None:
            emit_to_user("error", {"error": "Bitte mindestens einen Service auswählen."})
            return jsonify({"error": "Kein Service ausgewählt."}), 400

        count = session_db.query(QueueEntry).filter_by(
            provider_id=current_user.id,
        ).count()

        if not customer_name:
            customer_name = f"Walk-In #{count + 1}"

        duration_list = []

        for s in services:
            service = session_db.query(ProviderService).filter_by(
                id=int(s),
                provider_id=current_user.id
            ).first()

            if not service:
                emit_to_user("error", {
                    "error": "Der ausgewählte Service existiert nicht."
                })
                return jsonify({"error": "Service nicht gefunden."}), 400

            duration_list.append(service.duration_minutes)

        if custom_duration:
            duration_list.append(int(custom_duration))

        queues = session_db.query(QueueEntry).filter(
            QueueEntry.provider_id == current_user.id,
            QueueEntry.status.notin_(["completed", "no_show"])
        ).all()

        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=current_user.id,
        ).first()

        if len(queues) >= settings.queue_max_length:
            emit_to_user("error", {
                "error": "Die Warteschlange ist voll. Neue Kunden können sich momentan nicht eintragen."
            })
            return jsonify({"error": "Warteschlange voll"}), 200

        max_position = max(q.position for q in queues) if queues else 0

        new_position = max_position + 1

        new_queue = QueueEntry(
            provider_id=current_user.id,
            services_json=json.dumps(services),
            custom_duration=custom_duration if custom_duration else None,
            customer_name=customer_name,
            customer_phone=phone_number,
            duration_minutes=sum(duration_list),
            position=new_position,
            original_position=new_position,
            created_at=datetime.datetime.fromisoformat(created_at)
        )

        session_db.add(new_queue)
        session_db.commit()

        emit_to_user("message", {
            "message": "Zur Warteschlange hinzugefügt"
        })
        return jsonify({"message": "Zur Queue hinzugefügt."}), 200


    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Konnte nicht hinzugefügt werden"
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/queue/load", methods=["GET"])
@login_required
def load_queue():
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    session_db = Session()
    try:
        queues = session_db.query(QueueEntry).filter_by(
            provider_id=current_user.id,
        ).order_by(QueueEntry.position.asc()).all()

        queue = []
        updates = []

        for q in queues:
            status = q.status

            service = session_db.query(ProviderService).filter(
                ProviderService.id.in_(json.loads(q.services_json))
            ).all()

            service_names = " + ".join([s.name for s in service]) if service else ""

            if q.custom_duration:
                if service_names:
                    service_names += f" + Custom ({q.custom_duration} Min)"
                else:
                    service_names = f"Custom ({q.custom_duration} Min)"

            # Prüfen ob assigned Zeitraum aktiv ist
            if q.start and q.end and status == "assigned":
                if q.start.astimezone() <= now <= q.end.astimezone():
                    status = "in_progress"
                    updates.append((status, q.id))

            queue.append({
                "customer_name": q.customer_name,
                "service": service_names,
                "duration": q.duration_minutes,
                "position": q.position,
                "queue_id": q.id,
                "status": status
            })

        if updates:
            for status, queue_id in updates:
                session_db.query(QueueEntry).filter(
                    QueueEntry.id == queue_id,
                    QueueEntry.provider_id == current_user.id
                ).update({QueueEntry.status: status})

            session_db.commit()


        return jsonify(queue), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Warteschlange konnte nicht geladen werden"
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/queue/<int:queue_id>/remove", methods=["DELETE"])
@login_required
def remove_from_queue(queue_id):

    session_db = Session()
    try:
        queue = session_db.query(QueueEntry).filter_by(
            id=queue_id,
            provider_id=current_user.id
        ).first()

        if not queue:
            emit_to_user("error", {"error": "Eintrag nicht gefunden."})
            return jsonify({"error": "Eintrag nicht gefunden."}), 404

        position = queue.position

        session_db.delete(queue)

        queues = session_db.query(QueueEntry).filter(
            QueueEntry.provider_id == current_user.id,
            QueueEntry.position > position
        ).all()

        for q in queues:
            q.position -= 1
            q.original_position -= 1

            q.start = None
            q.end = None
            q.status = "pending"

        session_db.commit()

        emit_to_user("message",{
            "message": "Erfolgreich aus der Warteschlange entfernt."
        })
        return jsonify({"message": "Erfolgreich aus Queue entfernt."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Fehler beim Entfernen aus der Warteschlange."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/queue/avg_waiting_time", methods=["GET"])
@login_required
def calculate_avg_waiting_time():
    today = datetime.date.today()

    session_db = Session()
    try:
        session_db = Session()

        queues = session_db.query(QueueEntry).filter(
            QueueEntry.provider_id == current_user.id,
            func.date(QueueEntry.created_at) == today,
            QueueEntry.start.isnot(None),
            QueueEntry.status.not_in(["no_show", "in_progress", "pending"])
        ).all()

        if not queues:
            return jsonify({"avg_wait": 0})

        waiting_time = 0

        for q in queues:
            local = q.start.astimezone().replace(second=0, microsecond=0)
            created_at = q.created_at.astimezone()
            waiting_time += (local - created_at).total_seconds() / 60

        avg_wait = round(waiting_time / len(queues))

        return jsonify({
            "avg_wait": int(avg_wait)
        })

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Fehler beim Kalkulieren der durchschnittlichen Wartezeit."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

# <--- Für die Timeline --->

def load_appointments_for_timeline(provider_id):
    session_db = Session()

    appointments = session_db.query(Appointment).filter(
        Appointment.provider_id == provider_id,
        Appointment.status != "no_show"
    ).all()

    appointments_list = []

    for a in appointments:
        start = a.start.astimezone()
        end = a.end.astimezone()

        appointments_list.append({
            "id": a.id,
            "type": "Termin",
            "customer_name": a.customer_name,
            "services": json.loads(a.services_json),
            "custom_duration": a.custom_duration,
            "start": start,
            "end": end,
            "phone": a.customer_phone,
            "email": a.customer_email,
            "duration": a.duration_minutes,
            "notes": a.notes,
            "status": a.status
        })
    session_db.close()
    return appointments_list

def load_queue_for_timeline(provider_id):
    session_db = Session()

    queues = session_db.query(QueueEntry).filter_by(
        provider_id=provider_id,
    ).order_by(QueueEntry.position.asc()).all()

    queues_list = []

    for q in queues:
        start = q.start.astimezone() if q.start else None
        end = q.end.astimezone() if q.end else None

        queues_list.append({
            "id": q.id,
            "type": "Walk-in",
            "customer_name": q.customer_name,
            "services": json.loads(q.services_json),
            "custom_duration": q.custom_duration,
            "duration": q.duration_minutes,
            "start": start,
            "end": end,
            "created_at": q.created_at.astimezone(),
            "phone": q.customer_phone,
            "status": q.status,
            "position": q.position
        })
    session_db.close()
    return queues_list

def build_timeline(appointments, queue):
    timeline = []
    now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

    # 1. Termine und Walkins sortieren und Vergangene Termine filtern
    appointments = sorted([a for a in appointments if a["status"] not in ("completed", "no_show")], key=lambda x: x["start"])
    queues = sorted([q for q in queue if q["status"] not in ("completed", "no_show")], key=lambda x: x["position"])

    session_db = Session()

    # 3. Walk‑ins automatisch einplanen
    for q in queues:
        duration = datetime.timedelta(minutes=q["duration"])

        if  q["status"] not in ("completed", "no_show", "in_progress"):
            slot_start = find_free_slot(now, duration, appointments, timeline)
            slot_end = slot_start + duration

            session_db.query(QueueEntry).filter_by(
                id=q["id"]
            ).update({QueueEntry.start: slot_start, QueueEntry.end: slot_end})

            session_db.commit()

        else:
            slot_start = q["start"].replace(second=0, microsecond=0)
            slot_end = q["end"].replace(second=0, microsecond=0)

        timeline.append({
            "id": q["id"],
            "type": "Walk-in",
            "customer_name": q["customer_name"],
            "services": q["services"],
            "custom_duration": q["custom_duration"],
            "start": slot_start,
            "end": slot_end,
            "phone": q["phone"],
            "duration": q["duration"],
            "status": q["status"]
        })

    # 4. Termine + Walk‑ins zusammenführen
    all_events = appointments + timeline
    all_events.sort(key=lambda x: x["start"])

    session_db.close()
    return all_events

def find_free_slot(start_time, duration, appointments, timeline):
    candidate = start_time

    while True:
        candidate_end = candidate + duration
        conflict = False

        # Termine prüfen
        for a in appointments:
            if not (candidate_end <= a["start"] or a["end"] <= candidate):
                conflict = True
                candidate = a["end"]
                break

        if conflict:
            continue

        # Walk‑ins prüfen
        for q in timeline:
            if not (candidate_end <= q["start"] or q["end"] <= candidate):
                conflict = True
                candidate = q["end"]
                break

        if conflict:
            continue

        return candidate.replace(second=0, microsecond=0)

@app.route("/timeline")
def get_timeline():

    session_db = Session()
    try:
        provider_id = current_user.id
        now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)

        appointments = load_appointments_for_timeline(provider_id)
        queue = load_queue_for_timeline(provider_id)

        completed_appointments = [a for a in appointments if a["status"] == "completed"]
        completed_walkins = [q for q in queue if q["status"] == "completed"]

        events = build_timeline(appointments, queue)
        events += completed_appointments + completed_walkins
        events.sort(key=lambda x: x["start"])

        calendar_events = []
        for item in events:
            if item["type"] == "Termin" and item["status"] in ("pending", "confirmed", "in_progress"):
                if item["end"] <= now:
                    session_db.query(Appointment).filter(
                        Appointment.provider_id == provider_id,
                        Appointment.id == item["id"]
                    ).update({Appointment.status: "completed"})

                    session_db.commit()

                    item["status"] = "completed"

                elif item["start"] <= now <= item["end"]:
                    session_db.query(Appointment).filter(
                        Appointment.provider_id == provider_id,
                        Appointment.id == item["id"]
                    ).update({Appointment.status: "in_progress"})

                    session_db.commit()

                    item["status"] = "in_progress"


            elif item["type"] == "Walk-in" and item["status"] in ("assigned", "in_progress"):
                print(item["end"], now, item["end"] < now)
                if item["end"] <= now:
                    session_db.query(QueueEntry).filter(
                        QueueEntry.provider_id == provider_id,
                        QueueEntry.id == item["id"]
                    ).update({QueueEntry.status: "completed"})

                    session_db.commit()

                    item["status"] = "completed"

                elif item["start"] <= now <= item["end"]:
                    session_db.query(QueueEntry).filter(
                        QueueEntry.provider_id == provider_id,
                        QueueEntry.id == item["id"]
                    ).update({QueueEntry.status: "in_progress"})
                    session_db.commit()
                    item["status"] = "in_progress"


            if item["type"] == "Walk-in":
                if item["status"] not in ("completed", "no_show", "in_progress"):
                    session_db.query(QueueEntry).filter_by(
                        id=item["id"]
                    ).update({
                        QueueEntry.start: item["start"],
                        QueueEntry.end: item["end"],
                        QueueEntry.status: "assigned"
                    })

                    session_db.commit()

                service_ids = [int(s) for s in item["services"]]
                services = session_db.query(ProviderService).filter(
                    ProviderService.id.in_(service_ids)
                ).all()
                service_names = " + ".join([s.name for s in services]) if services else None

                if item["custom_duration"]:
                    if service_names:
                        service_names += f" + Custom ({item['custom_duration']} Min)"
                    else:
                        service_names = f"Custom ({item['custom_duration']} Min)"

                calendar_events.append({
                    "id": item["id"],
                    "title": item["customer_name"],
                    "start": item["start"].isoformat(),
                    "end": item["end"].isoformat(),
                    "color": "#1e88e5",
                    "extendedProps": {
                        "type": "Walk-in",
                        "service": service_names,
                        "services_json": item["services"],
                        "custom_duration": item["custom_duration"],
                        "duration": item["duration"],
                        "status": item["status"],
                        "email": None,
                        "phone": item.get("phone"),
                        "notes": None
                    }
                })

            else:
                service_ids = [int(s) for s in item["services"]]
                services = session_db.query(ProviderService).filter(
                    ProviderService.id.in_(service_ids)
                ).all()
                service_names = " + ".join([s.name for s in services]) if services else None

                if item["custom_duration"]:
                    if service_names:
                        service_names += f" + Custom ({item['custom_duration']} Min)"
                    else:
                        service_names = f"Custom ({item['custom_duration']} Min)"

                calendar_events.append({
                    "id": item["id"],
                    "title": item["customer_name"],
                    "start": item["start"].isoformat(),
                    "end": item["end"].isoformat(),
                    "color": "#43a047",
                    "extendedProps": {
                        "type": "Termin",
                        "service": service_names,
                        "services_json": item["services"],
                        "custom_duration": item["custom_duration"],
                        "duration": item["duration"],
                        "status": item["status"],
                        "email": item["email"],
                        "phone": item["phone"],
                        "notes": item["notes"]
                    }
                })

        return jsonify(calendar_events)

    except Exception as e:
        print("TIMELINE ERROR:", e)
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/logout", methods=["GET"])
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect("/")

@app.route("/dashboard/settings", methods=["GET"])
@login_required
def settings():
    session_db = Session()

    subscription = session_db.query(ProviderSubscription).filter_by(
        provider_id=current_user.id,
        is_active=True
    ).first()

    settings = session_db.query(ProviderSettings).filter_by(
        provider_id=current_user.id
    ).first()

    token = settings.queue_token

    url = f"http://127.0.0.1:6060/queue/{token}"

    plan = subscription.plan

    SMS_LIMITS = {"pro": 80, "premium": 200}
    limit = SMS_LIMITS.get(plan, 0)

    return render_template("settings.html",
           room_id=session.get("room_id"),
           subscription_plan=plan,
           qrcode_url=url,
           sms_credits_used=settings.sms_credits_used,
           sms_limit=limit
    )

@app.route("/dashboard/settings/delete_account", methods=["POST"])
@login_required
def delete_account():
    provider_id = current_user.id

    session_db = Session()
    try:
        session_db.query(Appointment).filter_by(provider_id=provider_id).delete()
        session_db.query(QueueEntry).filter_by(provider_id=provider_id).delete()
        session_db.query(ProviderService).filter_by(provider_id=provider_id).delete()
        session_db.query(ProviderCredentials).filter_by(provider_id=provider_id).delete()
        session_db.query(ProviderStaff).filter_by(id=provider_id).delete()
        session_db.query(ProviderSettings).filter_by(id=provider_id).delete()
        session_db.query(ProviderSubscription).filter_by(id=provider_id).delete()
        session_db.query(Provider).filter_by(id=provider_id).delete() # <-- zuletzt
        session_db.commit()

        session_db.commit()

        logout_user()
        session.clear()

        return jsonify({"message": "Konto erfolgreich gelöscht."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Account konnte nicht gelöscht werden."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/settings/get_provider_profile", methods=["GET"])
@login_required
def get_provider_profile():

    session_db = Session()
    try:
        provider = session_db.query(Provider).filter_by(id=current_user.id).first()

        credentials = session_db.query(ProviderCredentials).filter_by(
            provider_id=current_user.id
        ).first()

        services = session_db.query(ProviderService).filter_by(
            provider_id=current_user.id
        ).all()

        staff = session_db.query(ProviderStaff).filter(
            ProviderStaff.provider_id == current_user.id,
            ProviderStaff.is_owner == False,
        ).all()

        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=current_user.id
        ).first()

        data = {
            "business_name": provider.business_name,
            "category": provider.category,
            "street": provider.street,
            "postal_code": provider.postal_code,
            "city": provider.city,
            "email": credentials.email,
            "services": [serialize_service(s) for s in services],
            "staff": [serialize_staff(s) for s in staff],
            "reminder_24h": settings.reminder_24h,
            "reminder_3h": settings.reminder_3h,
            "weekday_open": settings.weekday_open,
            "weekday_close": settings.weekday_close,
            "saturday_open": settings.saturday_open,
            "saturday_close": settings.saturday_close,
            "sunday_closed": settings.sunday_closed,
            "queue_enabled": settings.queue_enabled,
            "queue_max_length": settings.queue_max_length,
        }


        return jsonify(data), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Beim Laden der Anbieterdaten ist ein Fehler aufgetreten."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

def serialize_service(s):
    return {
        "id": s.id,
        "name": s.name,
        "duration": s.duration_minutes
    }

def serialize_staff(s):
    return {
        "id": s.id,
        "name": s.name,
    }


@app.route("/dashboard/settings/change_password/check", methods=["POST"])
@login_required
def change_password_check():
    current_password = request.form.get("current_password")
    new_password = request.form.get("new_password")
    new_password_repeat = request.form.get("new_password_repeat")

    session_db = Session()
    try:
        if not current_password or not new_password or not new_password_repeat:
            emit_to_user("error", {
                "error": "Bitte füllen Sie alle Passwortfelder aus."
            })
            return jsonify({"error": "Felder fehlen"}), 400

        if new_password != new_password_repeat:
            emit_to_user("error", {
                "error": "Das neue Passwort und die Wiederholung stimmen nicht überein."
            })
            return jsonify({"error": "Passwörter stimmen nicht überein."}), 400

        session_db = Session()

        credentials = session_db.query(ProviderCredentials).filter_by(
            provider_id=current_user.id
        ).first()

        if not bcrypt.check_password_hash(credentials.password_hash, current_password):
            emit_to_user("error", {
                "error": "Das aktuelle Passwort ist falsch."
            })
            return jsonify({"error": "Falsches Passwort."}), 400

        if bcrypt.check_password_hash(credentials.password_hash, new_password):
            emit_to_user("error", {
                "error": "Das neue Passwort darf nicht mit dem alten Passwort identisch sein."
            })
            return jsonify({"error": "Neues Passwort ist identisch mit dem alten."}), 400

        session["new_password"] = new_password

        return jsonify({"message": "Passwort erfolgreich geprüft."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Es ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/settings/change_password/code", methods=["GET"])
@login_required
def change_password_code():
    try:
        SMTP_SERVER = "smtp.gmail.com"
        SMTP_PORT = 587
        YOUR_EMAIL = os.getenv("SMTP_EMAIL")
        YOUR_APP_PASSWORD = os.getenv("SMTP_PASSWORD")

        session["change_password_email"] = current_user.email
        session["change_password_code"] = "".join(random.choices("0123456789", k=4))
        session["change_password_expires"] = time.time() + 300

        text_fallback = f'''
Hallo,

du hast versucht, deinen Passwort auf unserer Terminplattform zu ändern.

Dein Bestätigungscode lautet:

{session.get("change_password_code")}

Bitte gib diesen Code auf der Verifizierungsseite ein, um die Änderung deiner E‑Mail‑Adresse abzuschließen.

Aus Sicherheitsgründen läuft dieser Code in 5 Minuten ab.

Falls du diese Änderung nicht angefordert hast, kannst du diese E‑Mail einfach ignorieren oder uns unter {YOUR_EMAIL} kontaktieren.

Viele Grüße  
Das Flowline‑Team  
{YOUR_EMAIL}
'''

        message = f'''
        <html><body style="margin:0;padding:0;background:#f0f2ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px;">
        <tr><td align="center">
          <table width="560" cellpadding="0" cellspacing="0" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
            <tr><td style="background:#2d6a4f;padding:28px 40px;">
              <span style="font-size:20px;font-weight:700;color:white;letter-spacing:-0.3px;">Flowline</span>
            </td></tr>
            <tr><td style="padding:40px;">
              <p style="font-size:14px;color:#6b7280;margin:0 0 24px;">Hallo,</p>
              <h1 style="font-size:22px;font-weight:700;color:#111827;margin:0 0 12px;letter-spacing:-0.4px;">Passwort ändern</h1>
              <p style="font-size:14px;color:#6b7280;line-height:1.6;margin:0 0 32px;">Du hast eine Anfrage gestellt, dein Passwort zu ändern. Gib den folgenden Code ein um die Änderung zu bestätigen.</p>
              <div style="background:#f0f2ee;border-radius:12px;padding:28px;text-align:center;margin:0 0 32px;">
                <span style="font-size:36px;font-weight:700;color:#2d6a4f;letter-spacing:12px;">{session.get("change_password_code")}</span>
              </div>
              <p style="font-size:13px;color:#9ca3af;margin:0 0 32px;">Dieser Code läuft in <strong style="color:#6b7280;">5 Minuten</strong> ab.</p>
              <hr style="border:none;border-top:1px solid #f3f4f6;margin:0 0 24px;">
              <p style="font-size:12px;color:#9ca3af;line-height:1.6;margin:0;">Falls du diese Änderung nicht angefordert hast, kontaktiere uns sofort unter <a href="mailto:{YOUR_EMAIL}" style="color:#2d6a4f;">{YOUR_EMAIL}</a>.</p>
            </td></tr>
            <tr><td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #f3f4f6;">
              <p style="font-size:12px;color:#9ca3af;margin:0;">© 2026 Flowline · <a href="mailto:{YOUR_EMAIL}" style="color:#9ca3af;">Kontakt</a></p>
            </td></tr>
          </table>
        </td></tr>
        </table>
        </body></html>
        '''

        msg = EmailMessage()
        msg.set_content(text_fallback)
        msg.add_alternative(message, subtype='html')
        msg["Subject"] = "Ihr Verifizierungscode zur Änderung Ihres Passworts – Flowline"
        msg["From"] = YOUR_EMAIL
        msg["To"] = current_user.email

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(YOUR_EMAIL, YOUR_APP_PASSWORD)
            server.send_message(msg)

        emit_to_user("message", {
            "message": "Verifizierungscode wurde erfolgreich versendet."
        })

        return render_template("verify-code.html", submit_url="/dashboard/settings/change_password/verify", resend_url="/dashboard/settings/change_password/code", room_id=session.get("room_id"))

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Es ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut."
        })
        return jsonify({"error": str(e)}), 500

@app.route("/dashboard/settings/change_password/verify", methods=["POST"])
@login_required
def change_password_verify():
    code = request.form.get("verification_code")

    new_password = session.get("new_password")
    password_code = session.get("change_password_code")
    password_email = session.get("change_password_email")
    password_expires = session.get("change_password_expires")

    if not password_code or not password_email or not password_expires:
        emit_to_user("error", {
            "error": "Dein Code ist abgelaufen. Bitte beginne den Vorgang erneut."
        })
        return jsonify({"error": "Code abgelaufen."}), 400

    if time.time() > password_expires:
        emit_to_user("error", {
            "error": "Dein Code ist abgelaufen. Bitte beginne den Vorgang erneut."
        })

        session.pop("new_password", None)
        session.pop("change_password_code", None)
        session.pop("change_password_email", None)
        session.pop("change_password_expires", None)
        return jsonify({"error": "Code abgelaufen."}), 400

    if code == password_code:
        session_db = Session()


        session_db.query(ProviderCredentials).filter_by(
            provider_id=current_user.id
        ).update({ProviderCredentials.password_hash: bcrypt.generate_password_hash(new_password).decode("utf-8")})

        session_db.commit()

        session_db.close()

        session.pop("new_password", None)
        session.pop("change_password_code", None)
        session.pop("change_password_email", None)
        session.pop("change_password_expires", None)

        emit_to_user("message", {
            "message": "Ihr Passwort wurde erfolgreich geändert."
        })

        return jsonify({"message": "Passwort erfolgreich geändert."}), 200

    emit_to_user("error", {
        "error": "Dieser Code stimmt nicht. Bitte überprüfe deine Eingabe."
    })
    return jsonify({"error": "Code stimmt nicht."}), 400


@app.route("/dashboard/settings/save_business_info", methods=["POST"])
@login_required
def save_business_info():
    business_name = request.form.get("business_name")
    category = request.form.get("category")
    street = request.form.get("street")
    postal_code = request.form.get("postal_code")
    city = request.form.get("city")

    session_db = Session()
    try:
        if not business_name or not category or not street or not postal_code or not city:
            emit_to_user("error", {
                "error": "Bitte füllen Sie alle erforderlichen Felder aus."
            })
            return jsonify({"error": "Felder fehlen."}), 400

        provider = session_db.query(Provider).filter_by(
            id=current_user.id
        ).first()

        if (provider.business_name, provider.category, provider.street, provider.postal_code, provider.city) == (business_name, category, street, postal_code, city):
            emit_to_user("error", {
                "error": "Es wurden keine Änderungen vorgenommen."
            })
            return jsonify({"error": "Keine Änderungen"}), 400

        session_db.query(Provider).filter_by(
            id=current_user.id
        ).update({
            Provider.business_name: business_name,
            Provider.category: category,
            Provider.street: street,
            Provider.postal_code: postal_code,
            Provider.city: city,
        })

        session_db.commit()

        emit_to_user("message", {
            "message": "Ihre Salon-Informationen wurden erfolgreich gespeichert."
        })

        return jsonify({"message": "Erfolgreich gespeichert."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Es ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/settings/update_email/code/send", methods=["POST"])
@login_required
def update_email_send_code():
    email = request.form.get("email")

    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    YOUR_EMAIL = os.getenv("SMTP_EMAIL")
    YOUR_APP_PASSWORD = os.getenv("SMTP_PASSWORD")

    session_db = Session()
    try:
        # Wenn keine E-Mail im POST → Resend → Session verwenden
        if not email:
            email = session.get("update_email")
            if not email:
                emit_to_user("error", {
                    "error": "Bitte geben Sie eine gültige E‑Mail-Adresse ein."
                })
                return jsonify({"error": "E-Mail fehlt."}), 400

        provider = session_db.query(ProviderCredentials).filter_by(
            provider_id=current_user.id
        ).first()

        if provider.email == email:
            emit_to_user("error", {
                "error": "Es wurden keine Änderungen vorgenommen."
            })
            return jsonify({"error": "Keine Änderungen."}), 400

        try:
            if not session.get("update_email"):
                session["update_email"] = email

            session["update_code"] = "".join(random.choices("0123456789", k=4))
            session["update_expires"] = time.time() + 300

            text_fallback = f'''
Hallo,

du hast versucht, deine E‑Mail‑Adresse auf unserer Terminplattform zu ändern.

Dein Bestätigungscode lautet:

{session.get("update_code")}

Bitte gib diesen Code auf der Verifizierungsseite ein, um die Änderung deiner E‑Mail‑Adresse abzuschließen.

Aus Sicherheitsgründen läuft dieser Code in 5 Minuten ab.

Falls du diese Änderung nicht angefordert hast, kannst du diese E‑Mail einfach ignorieren oder uns unter {YOUR_EMAIL} kontaktieren.

Viele Grüße  
Das Flowline‑Team  
{YOUR_EMAIL}
'''

            message = f'''
            <html><body style="margin:0;padding:0;background:#f0f2ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px;">
            <tr><td align="center">
              <table width="560" cellpadding="0" cellspacing="0" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
                <tr><td style="background:#2d6a4f;padding:28px 40px;">
                  <span style="font-size:20px;font-weight:700;color:white;letter-spacing:-0.3px;">Flowline</span>
                </td></tr>
                <tr><td style="padding:40px;">
                  <p style="font-size:14px;color:#6b7280;margin:0 0 24px;">Hallo,</p>
                  <h1 style="font-size:22px;font-weight:700;color:#111827;margin:0 0 12px;letter-spacing:-0.4px;">E-Mail-Adresse ändern</h1>
                  <p style="font-size:14px;color:#6b7280;line-height:1.6;margin:0 0 32px;">Du hast eine Anfrage gestellt, deine E-Mail-Adresse zu ändern. Gib den folgenden Code ein um die Änderung zu bestätigen.</p>
                  <div style="background:#f0f2ee;border-radius:12px;padding:28px;text-align:center;margin:0 0 32px;">
                    <span style="font-size:36px;font-weight:700;color:#2d6a4f;letter-spacing:12px;">{session.get("update_code")}</span>
                  </div>
                  <p style="font-size:13px;color:#9ca3af;margin:0 0 32px;">Dieser Code läuft in <strong style="color:#6b7280;">5 Minuten</strong> ab.</p>
                  <hr style="border:none;border-top:1px solid #f3f4f6;margin:0 0 24px;">
                  <p style="font-size:12px;color:#9ca3af;line-height:1.6;margin:0;">Falls du diese Änderung nicht angefordert hast, kontaktiere uns sofort unter <a href="mailto:{YOUR_EMAIL}" style="color:#2d6a4f;">{YOUR_EMAIL}</a>.</p>
                </td></tr>
                <tr><td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #f3f4f6;">
                  <p style="font-size:12px;color:#9ca3af;margin:0;">© 2026 Flowline · <a href="mailto:{YOUR_EMAIL}" style="color:#9ca3af;">Kontakt</a></p>
                </td></tr>
              </table>
            </td></tr>
            </table>
            </body></html>
            '''

            msg = EmailMessage()
            msg.set_content(text_fallback)
            msg.add_alternative(message, subtype='html')
            msg["Subject"] = "Ihr Verifizierungscode zur Änderung Ihrer E‑Mail-Adresse – Flowline"
            msg["From"] = YOUR_EMAIL
            msg["To"] = email

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(YOUR_EMAIL, YOUR_APP_PASSWORD)
                server.send_message(msg)

            emit_to_user("message", {
                "message": "Verifizierungscode wurde erfolgreich versendet."
            })
            return jsonify({"message": "Code versendet."}), 200

        except smtplib.SMTPRecipientsRefused:
            emit_to_user("message", {
                "message": "Es gibt keinen Account mit dieser E‑Mail-Adresse."
            })
            return jsonify({"error": "E-Mail nicht vorhanden."}), 400

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Es ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/settings/update_email/code", methods=["GET"])
@login_required
def update_email():

    return render_template("verify-code.html", submit_url="/dashboard/settings/update_email/verify", resend_url="/dashboard/settings/update_email/code/send", room_id=session.get("room_id"))


@app.route("/dashboard/settings/update_email/verify", methods=["POST"])
@login_required
def update_email_verify():
    code = request.form.get("verification_code")

    update_code = session.get("update_code")
    update_email = session.get("update_email")
    expires = session.get("update_expires")

    if not update_code or not update_email or not expires:
        emit_to_user("error", {
            "error": "Dein Code ist abgelaufen. Bitte beginne den Vorgang erneut."
        })
        return jsonify({"error": "Code abgelaufen."}), 400

    if time.time() > expires:
        emit_to_user("error", {
            "error": "Dein Code ist abgelaufen. Bitte beginne den Vorgang erneut."
        })
        session.pop("update_code", None)
        session.pop("update_email", None)
        session.pop("update_expires", None)
        return jsonify({"error": "Code abgelaufen."}), 400

    if code == update_code:
        session_db = Session()

        session_db.query(ProviderCredentials).filter_by(
            provider_id=current_user.id
        ).update({
            ProviderCredentials.email: update_email
        })

        session_db.commit()

        session_db.close()

        session.pop("update_code", None)
        session.pop("update_email", None)
        session.pop("update_expires", None)

        emit_to_user("message", {"message": "E-Mail wurde erfolgreich geändert."})

        return redirect(url_for("settings"))

    emit_to_user("error", {
        "error": "Dieser Code stimmt nicht. Bitte überprüfe deine Eingabe."
    })
    return jsonify({"error": "Code stimmt nicht."}), 400


@app.route("/dashboard/settings/services/save", methods=["POST"])
@login_required
def save_services():
    data = request.get_json()
    services = data.get("services", [])

    session_db = Session()
    try:
        session_db.query(ProviderService).filter_by(
            provider_id=current_user.id
        ).delete()

        for s in services:
            name = s.get("name", "").strip()
            duration = s.get("duration")

            if not name or not duration:
                continue

            session_db.add(ProviderService(
                provider_id=current_user.id,
                name=name,
                duration_minutes=int(duration)
            ))

        session_db.commit()

        if not services:
            emit_to_user("message", {"message": "Services erfolgreich gelöscht."})
            return jsonify({"message": "Services erfolgreich gelöscht."}), 200

        emit_to_user("message", {"message": "Services erfolgreich gespeichert."})
        return jsonify({"message": "Services erfolgreich gespeichert."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Beim Speichern deiner Services ist ein Fehler aufgetreten."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/settings/staff/save", methods=["POST"])
@login_required
def save_staff():
    data = request.get_json()
    staff = data.get("staff", [])

    session_db = Session()
    try:
        session_db.query(ProviderStaff).filter(
            ProviderStaff.provider_id == current_user.id,
            ProviderStaff.is_owner == False
        ).delete()

        for s in staff:
            name = s.get("name", "").strip()

            if not name:
                continue

            session_db.add(ProviderStaff(
                provider_id=current_user.id,
                name=name,
                is_owner=False
            ))

        session_db.commit()

        if not staff:
            emit_to_user("message", {"message": "Personal erfolgreich gelöscht."})
            return jsonify({"message": "Personal erfolgreich gelöscht."}), 200

        emit_to_user("message", {"message": "Personal erfolgreich gespeichert."})
        return jsonify({"message": "Personal erfolgreich gespeichert."}), 200

    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Beim Speichern deines Personals ist ein Fehler aufgetreten."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

def reminder_worker():
    while True:
        session_db = Session()
        try:
            now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(microsecond=0, second=0)
            in_24h = now + datetime.timedelta(hours=24)
            in_3h = now + datetime.timedelta(hours=3)
            
            now_ = time.time()
            for data in [registration_data, password_reset_data]:
                expired = [k for k, v in data.items() if now_ - v.get("created_at", now_) > 600]
                for k in expired:
                    data.pop(k, None)

            appointments = session_db.query(Appointment).filter(
                Appointment.customer_email != None,
                Appointment.customer_email != "",
                Appointment.status.in_(["pending", "confirmed"])
            ).all()

            for a in appointments:
                settings = session_db.query(ProviderSettings).filter_by(
                    provider_id=a.provider_id
                ).first()

                if not settings:
                    continue

                start = a.start.astimezone()

                # 24h Erinnerung – Fenster von 1 Minute
                if settings.reminder_24h:
                    diff_24 = abs((start - in_24h).total_seconds())
                    if diff_24 < 60 and not a.reminded_24h:
                        send_reminder_email(a, "24h")
                        a.reminded_24h = True
                        session_db.commit()

                # 3h Erinnerung – Fenster von 1 Minute
                if settings.reminder_3h:
                    diff_3 = abs((start - in_3h).total_seconds())
                    if diff_3 < 60 and not a.reminded_3h:
                        send_reminder_email(a, "3h")
                        if settings.sms_enabled and a.customer_phone:
                            message = f"Dein Termin bei {a.provider.business_name} ist in 3 Stunden ({start.strftime('%H:%M')} Uhr). Bis gleich!"
                            result = send_sms(
                                a.provider_id,
                                a.customer_phone,
                                message
                            )

                            if result and result["success"]:
                                settings.sms_credits_used += 1
                                session_db.commit()

                        a.reminded_3h = True
                        session_db.commit()

        except Exception as e:
            print("REMINDER ERROR:", e)

        finally:
            session_db.close()

        time.sleep(60)

def send_reminder_email(appointment, timing):
    YOUR_EMAIL = os.getenv("SMTP_EMAIL")
    YOUR_APP_PASSWORD = os.getenv("SMTP_PASSWORD")

    if timing == "24h":
        subject = "Erinnerung: Dein Termin morgen – Flowline"
        zeit_text = "morgen"
    else:
        subject = "Erinnerung: Dein Termin in 3 Stunden – Flowline"
        zeit_text = "in 3 Stunden"

    start_local = appointment.start.astimezone()
    uhrzeit = start_local.strftime("%H:%M")
    datum = start_local.strftime("%d.%m.%Y")

    text_fallback = (f'''
Hallo {appointment.customer_name},

dein Termin ist {zeit_text}.

Datum: {datum}
Uhrzeit: {uhrzeit} Uhr
Service: {appointment.service.name if appointment.service else "–"}

Falls du nicht kommen kannst, melde dich bitte rechtzeitig.

Flowline – {YOUR_EMAIL}
''')

    message = f'''
<html><body style="margin:0;padding:0;background:#f0f2ee;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 20px;">
<tr><td align="center">
  <table width="560" cellpadding="0" cellspacing="0" style="background:white;border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
    <tr><td style="background:#2d6a4f;padding:28px 40px;">
      <span style="font-size:20px;font-weight:700;color:white;">Flowline</span>
    </td></tr>
    <tr><td style="padding:40px;">
      <p style="font-size:14px;color:#6b7280;margin:0 0 24px;">Hallo {appointment.customer_name},</p>
      <h1 style="font-size:22px;font-weight:700;color:#111827;margin:0 0 12px;">Dein Termin ist {zeit_text}</h1>
      <p style="font-size:14px;color:#6b7280;line-height:1.6;margin:0 0 32px;">Wir erinnern dich an deinen bevorstehenden Termin.</p>
      <div style="background:#f0f2ee;border-radius:12px;padding:24px;margin:0 0 32px;">
        <p style="font-size:14px;color:#374151;margin:0 0 8px;"><strong>📅 Datum:</strong> {datum}</p>
        <p style="font-size:14px;color:#374151;margin:0 0 8px;"><strong>🕐 Uhrzeit:</strong> {uhrzeit} Uhr</p>
        <p style="font-size:14px;color:#374151;margin:0;"><strong>✂️ Service:</strong> {appointment.service.name if appointment.service else "–"}</p>
      </div>
      <p style="font-size:12px;color:#9ca3af;line-height:1.6;margin:0;">Falls du den Termin nicht wahrnehmen kannst, melde dich bitte rechtzeitig.<br>Bei Fragen erreichst du uns unter <a href="mailto:{YOUR_EMAIL}" style="color:#2d6a4f;">{YOUR_EMAIL}</a>.</p>
    </td></tr>
    <tr><td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #f3f4f6;">
      <p style="font-size:12px;color:#9ca3af;margin:0;">© 2026 Flowline</p>
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>
'''

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = YOUR_EMAIL
    msg["To"] = appointment.customer_email
    msg.set_content(text_fallback)
    msg.add_alternative(message, subtype='html')

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(YOUR_EMAIL, YOUR_APP_PASSWORD)
        server.send_message(msg)


@app.route("/dashboard/settings/email_reminder_settings/save", methods=["POST"])
@login_required
def save_email_reminder_settings():
    data = request.get_json()
    reminder_24h = data["reminder_24h"]
    reminder_3h = data["reminder_3h"]

    session_db = Session()

    try:
        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=current_user.id
        ).first()

        if not settings:
            settings = ProviderSettings(provider_id=current_user.id)
            session_db.add(settings)

        settings.reminder_24h = reminder_24h
        settings.reminder_3h = reminder_3h

        session_db.commit()
        session_db.close()

        emit_to_user("message", {
            "message": "Einstellungen erfolgreich gespeichert."
        })
        return jsonify({"message": "Einstellungen erfolgreich gespeichert."}), 200


    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Etwas ist schiefgelaufen. Deine Änderungen wurden nicht gespeichert."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()


@app.route("/dashboard/settings/opening_hours/save", methods=["POST"])
@login_required
def save_opening_hours_settings():
    data = request.get_json()
    weekday_open = data["weekday_open"]
    weekday_close = data["weekday_close"]
    saturday_open = data["saturday_open"]
    saturday_close = data["saturday_close"]
    sunday_closed= data["sunday_closed"]

    session_db = Session()

    try:
        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=current_user.id
        ).first()

        if not settings:
            settings = ProviderSettings(provider_id=current_user.id)
            session_db.add(settings)

        settings.weekday_open = weekday_open
        settings.weekday_close = weekday_close
        settings.saturday_open = saturday_open
        settings.saturday_close = saturday_close
        settings.sunday_closed = sunday_closed

        session_db.commit()
        session_db.close()

        emit_to_user("message", {
            "message": "Einstellungen erfolgreich gespeichert."
        })
        return jsonify({"message": "Einstellungen erfolgreich gespeichert."}), 200


    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Etwas ist schiefgelaufen. Deine Änderungen wurden nicht gespeichert."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/settings/queue_settings/save", methods=["POST"])
@login_required
def save_queue_settings():
    data = request.get_json()
    queue_enabled = data["queue_enabled"]
    queue_max_length = data["queue_max_length"]

    session_db = Session()

    try:
        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=current_user.id
        ).first()

        if not settings:
            settings = ProviderSettings(provider_id=current_user.id)
            session_db.add(settings)

        settings.queue_enabled = queue_enabled
        settings.queue_max_length = queue_max_length

        session_db.commit()
        session_db.close()

        emit_to_user("message", {
            "message": "Einstellungen erfolgreich gespeichert."
        })
        return jsonify({"message": "Einstellungen erfolgreich gespeichert."}), 200


    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Etwas ist schiefgelaufen. Deine Änderungen wurden nicht gespeichert."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/dashboard/settings/sms/save", methods=["POST"])
@login_required
def save_sms_settings():
    data = request.get_json()
    sms_enabled = data["sms_enabled"]

    session_db = Session()

    try:
        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=current_user.id
        ).first()

        if not settings:
            settings = ProviderSettings(provider_id=current_user.id)
            session_db.add(settings)

        settings.sms_enabled = sms_enabled

        session_db.commit()
        session_db.close()

        emit_to_user("message", {
            "message": "Einstellungen erfolgreich gespeichert."
        })
        return jsonify({"message": "Einstellungen erfolgreich gespeichert."}), 200


    except Exception as e:
        print(e)
        emit_to_user("error", {
            "error": "Etwas ist schiefgelaufen. Deine Änderungen wurden nicht gespeichert."
        })
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

def send_sms(provider_id, phone, message):
    session_db = Session()

    try:
        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=provider_id
        ).first()

        subscription = session_db.query(ProviderSubscription).filter_by(
            provider_id=provider_id,
            is_active=True
        ).first()

        if not settings or not settings.sms_enabled:
            return {"success": False, "reason": "sms_not_enabled"}

        plan = subscription.plan

        if plan in ("free", "basic"):
            return {"success": False, "reason": "plan"}

        SMS_LIMITS = {"pro": 80, "premium": 200}
        limit = SMS_LIMITS.get(plan, 0)

        now = datetime.datetime.utcnow()
        if (now - settings.sms_credits_reset).days >= 30:
            settings.sms_credits_used = 0
            settings.sms_credits_reset = now

        if settings.sms_credits_used >= limit:
            emit_to_user("error", {
                "error": "Dein SMS-Kontingent für diesen Monat ist aufgebraucht. Upgrade deinen Plan für mehr SMS."
            })
            return {"success": False, "reason": "limit_reached"}

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=phone
        )

        settings.sms_credits_used += 1
        session_db.commit()  # ← wichtig
        return {"success": True}

    except Exception as e:
        print("SMS ERROR:", e)
        return {"success": False, "reason": "SMS ERROR"}

    finally:
        session_db.close()

@app.route("/dashboard/settings/qr/image")
@login_required
def qr_image():
    session_db = Session()
    try:
        settings = session_db.query(ProviderSettings).filter_by(
            provider_id=current_user.id
        ).first()

        token = settings.queue_token

        url = f"http://127.0.0.1:6060/queue/{token}"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4
        )

        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        return send_file(buffer, mimetype="image/png")


    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500


@app.route("/queue/<string:token>") # Room muss anders sein! Weil sonst sieht man Errors im Dashboard
def customer_queue(token):

    session_db = Session()
    try:
        settings = session_db.query(ProviderSettings).filter_by(
            queue_token=token
        ).first()

        if not settings:
            return render_template("queue_invalid.html"), 404

        if not settings.queue_enabled:
            return render_template("queue_closed.html")

        provider = session_db.query(Provider).filter_by(
            id=settings.provider_id
        ).first()

        service = session_db.query(ProviderService).filter_by(
            provider_id=settings.provider_id
        ).all()

        active_count = session_db.query(QueueEntry).filter_by(
            provider_id=settings.provider_id
        ).filter(
            QueueEntry.status.notin_(["completed", "no_show"])
        ).count()

        is_full = active_count >= settings.queue_max_length

        return render_template("customer_queue_join.html",
            provider=provider,
            service=service,
            token=token,
            is_full=is_full
       )

    finally:
        session_db.close()

@app.route("/queue/<string:token>/join", methods=["POST"])
def customer_join_queue(token):
    session_db = Session()
    try:
        settings = session_db.query(ProviderSettings).filter_by(
            queue_token=token
        ).first()

        if not settings or not settings.queue_enabled:
            return jsonify({"error": "Warteschlange ist nicht verfügbar."}), 400

        customer_name = request.form.get("customer_name", "").strip()
        customer_phone = request.form.get("customer_phone", "").strip()
        services = request.form.getlist("services[]")
        custom_duration = request.form.get("custom_duration", None)

        duration_list = []

        if custom_duration == "":
            emit_to_user("error", {"error": "Bitte eine gültige Dauer eingeben."})
            return jsonify({"error": "Custom-Dauer fehlt."}), 400

        if not services and custom_duration is None:
            emit_to_user("error", {"error": "Bitte mindestens einen Service auswählen."})
            return jsonify({"error": "Kein Service ausgewählt."}), 400

        count = session_db.query(QueueEntry).filter_by(
            provider_id=current_user.id,
        ).count()

        if not customer_name:
            customer_name = f"Walk-In #{count + 1}"

        for s in services:
            service = session_db.query(ProviderService).filter_by(
                id=int(s),
                provider_id=settings.provider_id
            ).first()

            if not service:
                return jsonify({"error": "Service nicht gefunden."}), 400

            duration_list.append(service.duration_minutes)

        if custom_duration:
            duration_list.append(int(custom_duration))

        active_count = session_db.query(QueueEntry).filter_by(
            provider_id=settings.provider_id
        ).filter(
            QueueEntry.status.notin_(["completed", "no_show"])
        ).count()

        if active_count >= settings.queue_max_length:
            return jsonify({"error": "Die Warteschlange ist aktuell voll."}), 400

        new_entry = QueueEntry(
            provider_id=settings.provider_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            services_json=json.dumps(services),
            custom_duration=custom_duration if custom_duration else None,
            duration_minutes=sum(duration_list),
            position=active_count + 1,
            original_position=active_count + 1,
            status="pending"
        )

        session_db.add(new_entry)
        session_db.flush()
        queue_id = new_entry.id
        session_db.commit()

        appointments = load_appointments_for_timeline(settings.provider_id)
        queue = load_queue_for_timeline(settings.provider_id)

        events = build_timeline(appointments, queue)

        for e in events:
           if e["type"] == "Walk-in":
               if e["status"] == "pending" or e["status"] == "in_progress":
                   entry = session_db.query(QueueEntry).filter_by(
                        id=e["id"],
                        provider_id=settings.provider_id
                    ).first()

                   if entry:
                        entry.start = e["start"]
                        entry.end = e["end"]
                        entry.status = "assigned"

        session_db.commit()

        socketio.emit("queue_updated", {"message": f"{customer_name} hat sich über QR-Code in die Warteschlange eingetragen."}, room=f"provider_{settings.provider_id}")

        return jsonify({"queue_id": queue_id}), 200

    except Exception as e:
        print(e)
        return jsonify({"error": "Etwas ist schiefgelaufen. Bitte versuche es erneut."}), 500

    finally:
        session_db.close()

@app.route("/queue/<string:token>/status/<int:queue_id>")
def customer_queue_status(token, queue_id):
    session_db = Session()
    try:
        settings = session_db.query(ProviderSettings).filter_by(
            queue_token=token
        ).first()

        if not settings:
            return render_template("queue_invalid.html"), 404

        entry = session_db.query(QueueEntry).filter_by(
            id=queue_id,
            provider_id=settings.provider_id
        ).first()

        if not entry:
            return render_template("queue_invalid.html"), 404

        provider = session_db.query(Provider).filter_by(
            id=settings.provider_id
        ).first()

        return render_template("customer_queue_status.html",
               provider=provider,
               token=token,
               queue_id=queue_id,
       )
    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500

    finally:
        session_db.close()

@app.route("/queue/<string:token>/status/<int:queue_id>/data")
def customer_queue_status_data(token, queue_id):
    statusMap = {
        "pending": "Ausstehend",
        "no_show": "Nicht erschienen",
        "completed": "Erledigt",
        "assigned": "Wartend",
        "in_progress": "Dran"
    }

    session_db = Session()
    try:
        settings = session_db.query(ProviderSettings).filter_by(
            queue_token=token
        ).first()

        if not settings:
            return render_template("queue_invalid.html"), 404

        entry = session_db.query(QueueEntry).filter_by(
            id=queue_id,
            provider_id=settings.provider_id
        ).first()

        appointments = load_appointments_for_timeline(settings.provider_id)
        queue = load_queue_for_timeline(settings.provider_id)

        combine = appointments + queue
        combine.sort(key=lambda x: x["start"])
        combine = [event for event in combine if event["status"] not in ["completed", "no_show"]]

        for item in combine:
            if item["type"] == "Walk-in":
                if item["id"] == queue_id:
                    entry.position_with_appointments = combine.index(item) + 1

        if not entry:
            return jsonify({"error": "Nicht gefunden"}), 404

        if entry.status == "completed":
            return jsonify({"status": statusMap["completed"]}), 200

        if entry.status == "no_show":
            return jsonify({"status": statusMap["no_show"]}), 200

        estimated_minutes = None
        if entry.start:
            start_aware = entry.start.astimezone()
            end_aware = entry.end.astimezone()
            now = datetime.datetime.now(datetime.timezone.utc).astimezone().replace(second=0, microsecond=0)
            diff_seconds = (start_aware - now).total_seconds()
            estimated_minutes = max(round(int(diff_seconds) / 60), 0)

            if end_aware < now:
                session_db.query(QueueEntry).filter_by(
                    id=queue_id,
                    provider_id=settings.provider_id
                ).update({QueueEntry.status: "completed"})

                session_db.commit()

                entry.status = "completed"

            if start_aware <= now <= end_aware:
                session_db.query(QueueEntry).filter_by(
                    id=queue_id,
                    provider_id=settings.provider_id
                ).update({QueueEntry.status: "in_progress"})

                session_db.commit()

                entry.status = "in_progress"

        if not appointments:
            return jsonify({
                "name": entry.customer_name,
                "status": statusMap[f"{entry.status}"],
                "position": entry.position,
                "estimated_wait_minutes": estimated_minutes
            }), 200

        else:
            return jsonify({
                "name": entry.customer_name,
                "status": statusMap[f"{entry.status}"],
                "position": entry.position_with_appointments,
                "estimated_wait_minutes": estimated_minutes
            }), 200

    finally:
        session_db.close()



@app.route("/dashboard/upgrade")
@login_required
def upgrade():
    return render_template("upgrade.html")



reminder_thread = threading.Thread(target=reminder_worker, daemon=True)
reminder_thread.start()

socketio.run(app, use_reloader=True, debug=True, allow_unsafe_werkzeug=True, port=6060)