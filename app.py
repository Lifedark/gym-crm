import os
import uuid
import random
import string
from datetime import datetime, timedelta, date
from bson.objectid import ObjectId
import qrcode
from io import BytesIO
import base64

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, session
)
from flask_pymongo import PyMongo
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
import stripe
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

app = Flask(__name__)
app.config.from_object("config.Config")

mongo = PyMongo(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Zaloguj się, aby uzyskać dostęp."

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

# SendGrid
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
MAIL_FROM = os.getenv("MAIL_FROM", "noreply@ironfit.gym")

COLORS = {
    "bg": "#08080f",
    "card": "#0f0f1f",
    "card2": "#15152a",
    "text": "#f0f0f8",
    "text2": "#9898b8",
    "muted": "#5a5a7a",
    "accent1": "#00f0ff",
    "accent2": "#7c3aed",
    "accent3": "#f59e0b",
    "accent4": "#10b981",
    "gradient1": "linear-gradient(135deg, #00f0ff, #7c3aed)",
    "gradient2": "linear-gradient(135deg, #f59e0b, #ef4444)",
    "gradient3": "linear-gradient(135deg, #10b981, #00f0ff)",
}


class User(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data
        self.id = str(user_data["_id"])
        self.username = user_data.get("username", "")
        self.role = user_data.get("role", "staff")
        self.name = user_data.get("name", "")

    def is_admin(self):
        return self.role == "admin"


@login_manager.user_loader
def load_user(user_id):
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    return User(user) if user else None


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash("Brak uprawnień administratora.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def to_date(val):
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return val


def member_status(member):
    today = date.today()
    if member.get("status") == "frozen":
        return "frozen"
    mem_type = mongo.db.membership_types.find_one(
        {"_id": ObjectId(member["membership_type_id"])}
    ) if member.get("membership_type_id") else None
    if mem_type:
        t = mem_type.get("type", "period")
        if t == "period":
            end = member.get("end_date")
            if end:
                if today > to_date(end):
                    return "expired"
        elif t == "entries":
            if member.get("entries_left", 0) <= 0:
                return "expired"
    return "active"


def generate_qr_base64(data):
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def send_email(to_email, subject, html_content):
    if not SENDGRID_API_KEY or SENDGRID_API_KEY.startswith("SG.") == False:
        return False
    try:
        message = Mail(
            from_email=MAIL_FROM,
            to_emails=to_email,
            subject=subject,
            html_content=html_content
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


# ===================== FILTERS + CONTEXT =====================

@app.template_filter("datefmt")
def datefmt_filter(d):
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y")
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    if isinstance(d, str):
        return d
    return "-"


@app.template_filter("datetimefmt")
def datetimefmt_filter(d):
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y %H:%M")
    if isinstance(d, str):
        return d
    return "-"


@app.template_filter("currency")
def currency_filter(v):
    try:
        return f"{float(v):.2f} zł"
    except (ValueError, TypeError):
        return "-"


@app.context_processor
def utility_processor():
    return {"now": datetime.now, "colors": COLORS,
            "STRIPE_PUBLISHABLE_KEY": STRIPE_PUBLISHABLE_KEY,
            "generate_qr_base64": generate_qr_base64,
            "member_status": member_status}


@app.context_processor
def inject_app_config():
    return {
        "app_name": app.config["APP_NAME"],
        "app_color": app.config["APP_COLOR"]
    }


# ===================== AUTH =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user_data = mongo.db.users.find_one({"username": username})
        if user_data and bcrypt.check_password_hash(
            user_data["password"], password
        ):
            user = User(user_data)
            login_user(user)
            mongo.db.users.update_one(
                {"_id": user_data["_id"]},
                {"$set": {"last_login": datetime.now()}}
            )
            flash(f"Witaj, {user.name}!", "success")
            return redirect(url_for("dashboard"))
        flash("Nieprawidłowa nazwa użytkownika lub hasło.", "danger")
    return render_template("login.html", app_name=app.config["APP_NAME"])


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Wylogowano pomyślnie.", "info")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
@login_required
@admin_required
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "staff")
        if not username or not password or not name:
            flash("Wszystkie pola są wymagane.", "danger")
            return render_template("register.html")
        if mongo.db.users.find_one({"username": username}):
            flash("Nazwa użytkownika już istnieje.", "danger")
            return render_template("register.html")
        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        mongo.db.users.insert_one({
            "username": username,
            "password": hashed,
            "name": name,
            "role": role,
            "created_at": datetime.now(),
            "last_login": None
        })
        flash(f"Konto dla {name} utworzone!", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/users")
@login_required
@admin_required
def users_list():
    users = list(mongo.db.users.find())
    return render_template("users.html", users=users)


# ===================== DASHBOARD =====================

@app.route("/")
@login_required
def dashboard():
    today = date.today()
    total_members = mongo.db.members.count_documents({})
    active_members = 0
    expired_members = 0
    for m in mongo.db.members.find():
        st = member_status(m)
        if st == "active":
            active_members += 1
        elif st == "expired":
            expired_members += 1
    today_checkins = mongo.db.checkins.count_documents({
        "timestamp": {"$gte": datetime(today.year, today.month, today.day)}
    })
    week_ago = today - timedelta(days=7)
    week_checkins = mongo.db.checkins.count_documents({
        "timestamp": {"$gte": datetime(week_ago.year, week_ago.month, week_ago.day)}
    })
    expiring_soon = []
    for m in mongo.db.members.find({"status": {"$ne": "frozen"}}):
        mem_type = None
        if m.get("membership_type_id"):
            mem_type = mongo.db.membership_types.find_one(
                {"_id": ObjectId(m["membership_type_id"])}
            )
        if mem_type and mem_type.get("type") == "period":
            end = m.get("end_date")
            if end:
                remaining = (to_date(end) - today).days
                if 0 <= remaining <= 7:
                    expiring_soon.append({"member": m, "remaining": remaining})
    recent_checkins = list(mongo.db.checkins.aggregate([
        {"$sort": {"timestamp": -1}}, {"$limit": 10}
    ]))
    for c in recent_checkins:
        c["member"] = mongo.db.members.find_one({"_id": ObjectId(c["member_id"])})
    return render_template(
        "dashboard.html",
        total_members=total_members, active_members=active_members,
        expired_members=expired_members, today_checkins=today_checkins,
        week_checkins=week_checkins, expiring_soon=expiring_soon,
        recent_checkins=recent_checkins
    )


# ===================== MEMBERSHIP TYPES =====================

@app.route("/types")
@login_required
def membership_types():
    types = list(mongo.db.membership_types.find())
    return render_template("membership_types.html", types=types)


@app.route("/types/add", methods=["GET", "POST"])
@login_required
@admin_required
def membership_type_add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mtype = request.form.get("type", "period")
        price = float(request.form.get("price", 0))
        description = request.form.get("description", "").strip()
        if not name:
            flash("Nazwa karnetu jest wymagana.", "danger")
            return render_template("membership_type_form.html")
        data = {
            "name": name, "type": mtype, "price": price,
            "description": description, "created_at": datetime.now()
        }
        if mtype == "period":
            data["duration_days"] = int(request.form.get("duration_days", 30))
        elif mtype == "entries":
            data["entries_count"] = int(request.form.get("entries_count", 10))
        mongo.db.membership_types.insert_one(data)
        flash(f"Karnet '{name}' dodany!", "success")
        return redirect(url_for("membership_types"))
    return render_template("membership_type_form.html")


@app.route("/types/edit/<type_id>", methods=["GET", "POST"])
@login_required
@admin_required
def membership_type_edit(type_id):
    mt = mongo.db.membership_types.find_one({"_id": ObjectId(type_id)})
    if not mt:
        flash("Karnet nie istnieje.", "danger")
        return redirect(url_for("membership_types"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mtype = request.form.get("type", "period")
        price = float(request.form.get("price", 0))
        description = request.form.get("description", "").strip()
        if not name:
            flash("Nazwa karnetu jest wymagana.", "danger")
            return render_template("membership_type_form.html", mt=mt)
        update = {"name": name, "type": mtype, "price": price, "description": description}
        if mtype == "period":
            update["duration_days"] = int(request.form.get("duration_days", 30))
            update.pop("entries_count", None)
        elif mtype == "entries":
            update["entries_count"] = int(request.form.get("entries_count", 10))
            update.pop("duration_days", None)
        mongo.db.membership_types.update_one({"_id": ObjectId(type_id)}, {"$set": update})
        flash("Karnet zaktualizowany!", "success")
        return redirect(url_for("membership_types"))
    return render_template("membership_type_form.html", mt=mt)


@app.route("/types/delete/<type_id>")
@login_required
@admin_required
def membership_type_delete(type_id):
    mt = mongo.db.membership_types.find_one({"_id": ObjectId(type_id)})
    if not mt:
        flash("Karnet nie istnieje.", "danger")
        return redirect(url_for("membership_types"))
    in_use = mongo.db.members.count_documents({"membership_type_id": type_id})
    if in_use > 0:
        flash(f"Nie można usunąć – {in_use} klientów ma ten karnet.", "danger")
        return redirect(url_for("membership_types"))
    mongo.db.membership_types.delete_one({"_id": ObjectId(type_id)})
    flash("Karnet usunięty.", "success")
    return redirect(url_for("membership_types"))


# ===================== MEMBERS =====================

@app.route("/members")
@login_required
def members():
    query = {}
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip()
    type_filter = request.args.get("type", "").strip()
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"qr_code": {"$regex": search, "$options": "i"}},
        ]
    all_members = list(mongo.db.members.find(query).sort("created_at", -1))
    results = []
    for m in all_members:
        st = member_status(m)
        if status_filter and st != status_filter:
            continue
        if type_filter and m.get("membership_type_id") != type_filter:
            continue
        mt = None
        if m.get("membership_type_id"):
            mt = mongo.db.membership_types.find_one({"_id": ObjectId(m["membership_type_id"])})
        results.append({"member": m, "status": st, "type": mt})
    types = list(mongo.db.membership_types.find())
    return render_template("members.html", members=results, types=types,
                           search=search, status_filter=status_filter, type_filter=type_filter)


@app.route("/members/add", methods=["GET", "POST"])
@login_required
def member_add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        membership_type_id = request.form.get("membership_type_id")
        notes = request.form.get("notes", "").strip()
        if not name:
            flash("Imię i nazwisko jest wymagane.", "danger")
            types = list(mongo.db.membership_types.find())
            return render_template("member_form.html", types=types)
        qr_code = str(uuid.uuid4())[:8].upper()
        now = datetime.now()
        member_data = {
            "name": name, "phone": phone, "email": email,
            "membership_type_id": membership_type_id, "notes": notes,
            "qr_code": qr_code, "status": "active",
            "created_at": now, "created_by": current_user.id,
        }
        if membership_type_id:
            mt = mongo.db.membership_types.find_one({"_id": ObjectId(membership_type_id)})
            if mt:
                if mt["type"] == "period":
                    days = mt.get("duration_days", 30)
                    member_data["start_date"] = now
                    member_data["end_date"] = now + timedelta(days=days)
                    member_data["entries_left"] = None
                    member_data["total_entries"] = None
                elif mt["type"] == "entries":
                    entries = mt.get("entries_count", 10)
                    member_data["start_date"] = now
                    member_data["end_date"] = None
                    member_data["entries_left"] = entries
                    member_data["total_entries"] = entries
        else:
            member_data["start_date"] = now
            member_data["end_date"] = now + timedelta(days=30)
            member_data["entries_left"] = None
            member_data["total_entries"] = None
        mongo.db.members.insert_one(member_data)
        flash(f"Klient {name} dodany! Kod QR: {qr_code}", "success")
        return redirect(url_for("members"))
    types = list(mongo.db.membership_types.find())
    return render_template("member_form.html", types=types)


@app.route("/members/edit/<member_id>", methods=["GET", "POST"])
@login_required
def member_edit(member_id):
    member = mongo.db.members.find_one({"_id": ObjectId(member_id)})
    if not member:
        flash("Klient nie istnieje.", "danger")
        return redirect(url_for("members"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        membership_type_id = request.form.get("membership_type_id")
        notes = request.form.get("notes", "").strip()
        status = request.form.get("status", "active")
        if not name:
            flash("Imię i nazwisko jest wymagane.", "danger")
            types = list(mongo.db.membership_types.find())
            return render_template("member_form.html", member=member, types=types)
        update = {
            "name": name, "phone": phone, "email": email,
            "membership_type_id": membership_type_id, "notes": notes, "status": status
        }
        if membership_type_id and membership_type_id != member.get("membership_type_id"):
            mt = mongo.db.membership_types.find_one({"_id": ObjectId(membership_type_id)})
            if mt:
                if mt["type"] == "period":
                    days = mt.get("duration_days", 30)
                    update["start_date"] = datetime.now()
                    update["end_date"] = datetime.now() + timedelta(days=days)
                    update["entries_left"] = None
                    update["total_entries"] = None
                elif mt["type"] == "entries":
                    entries = mt.get("entries_count", 10)
                    update["start_date"] = datetime.now()
                    update["end_date"] = None
                    update["entries_left"] = entries
                    update["total_entries"] = entries
        mongo.db.members.update_one({"_id": ObjectId(member_id)}, {"$set": update})
        flash("Dane klienta zaktualizowane!", "success")
        return redirect(url_for("member_detail", member_id=member_id))
    types = list(mongo.db.membership_types.find())
    return render_template("member_form.html", member=member, types=types)


@app.route("/members/<member_id>")
@login_required
def member_detail(member_id):
    member = mongo.db.members.find_one({"_id": ObjectId(member_id)})
    if not member:
        flash("Klient nie istnieje.", "danger")
        return redirect(url_for("members"))
    mt = None
    if member.get("membership_type_id"):
        mt = mongo.db.membership_types.find_one({"_id": ObjectId(member["membership_type_id"])})
    st = member_status(member)
    checkins = list(mongo.db.checkins.find({"member_id": member_id}).sort("timestamp", -1).limit(50))
    qr_b64 = generate_qr_base64(member["qr_code"])
    membership_types = list(mongo.db.membership_types.find())
    return render_template("member_detail.html", member=member, membership_type=mt,
                           status=st, checkins=checkins, qr_b64=qr_b64,
                           membership_types=membership_types)


@app.route("/members/delete/<member_id>")
@login_required
@admin_required
def member_delete(member_id):
    member = mongo.db.members.find_one({"_id": ObjectId(member_id)})
    if not member:
        flash("Klient nie istnieje.", "danger")
        return redirect(url_for("members"))
    mongo.db.checkins.delete_many({"member_id": member_id})
    mongo.db.purchases.delete_many({"member_id": member_id})
    mongo.db.members.delete_one({"_id": ObjectId(member_id)})
    flash(f"Klient {member['name']} usunięty.", "success")
    return redirect(url_for("members"))


@app.route("/members/renew/<member_id>", methods=["POST"])
@login_required
@admin_required
def member_renew(member_id):
    member = mongo.db.members.find_one({"_id": ObjectId(member_id)})
    if not member:
        flash("Klient nie istnieje.", "danger")
        return redirect(url_for("members"))
    membership_type_id = request.form.get("membership_type_id")
    if not membership_type_id:
        flash("Wybierz karnet.", "danger")
        return redirect(url_for("member_detail", member_id=member_id))
    mt = mongo.db.membership_types.find_one({"_id": ObjectId(membership_type_id)})
    if not mt:
        flash("Karnet nie istnieje.", "danger")
        return redirect(url_for("member_detail", member_id=member_id))
    now = datetime.now()
    update = {"membership_type_id": membership_type_id, "status": "active", "start_date": now}
    if mt["type"] == "period":
        days = mt.get("duration_days", 30)
        update["end_date"] = now + timedelta(days=days)
        update["entries_left"] = None; update["total_entries"] = None
    elif mt["type"] == "entries":
        entries = mt.get("entries_count", 10)
        update["end_date"] = None
        update["entries_left"] = entries; update["total_entries"] = entries
    mongo.db.members.update_one({"_id": ObjectId(member_id)}, {"$set": update})
    flash(f"Karnet odnowiony dla {member['name']}!", "success")
    return redirect(url_for("member_detail", member_id=member_id))


# ===================== BULK DELETE =====================

@app.route("/admin/bulk-delete", methods=["POST"])
@login_required
@admin_required
def bulk_delete():
    confirm = request.form.get("confirm", "")
    if confirm != "USUN-WSZYSTKO":
        flash("Potwierdź wpisując 'USUN-WSZYSTKO'.", "danger")
        return redirect(url_for("dashboard"))
    mongo.db.members.delete_many({})
    mongo.db.checkins.delete_many({})
    mongo.db.purchases.delete_many({})
    mongo.db.membership_types.delete_many({})
    flash("Wszystkie dane klientów, historii i karnetów usunięte!", "warning")
    return redirect(url_for("dashboard"))


# ===================== SCAN / CHECK-IN =====================

@app.route("/scan")
@login_required
def scan():
    return render_template("scan.html")


@app.route("/api/member/<qr_code>")
@login_required
def api_member_by_qr(qr_code):
    member = mongo.db.members.find_one({"qr_code": qr_code.upper()})
    if not member:
        return jsonify({"found": False, "message": "Nie znaleziono klienta."})
    mt = None
    if member.get("membership_type_id"):
        mt = mongo.db.membership_types.find_one({"_id": ObjectId(member["membership_type_id"])})
    st = member_status(member)
    return jsonify({
        "found": True,
        "member": {
            "id": str(member["_id"]), "name": member["name"],
            "phone": member.get("phone", ""), "email": member.get("email", ""),
            "qr_code": member["qr_code"], "status": st,
            "membership_type": mt["name"] if mt else "Brak",
            "end_date": str(member.get("end_date", "")) if member.get("end_date") else "",
            "entries_left": member.get("entries_left", ""),
        }
    })


@app.route("/api/checkin/<qr_code>", methods=["POST"])
@login_required
def api_checkin(qr_code):
    member = mongo.db.members.find_one({"qr_code": qr_code.upper()})
    if not member:
        return jsonify({"success": False, "message": "Nie znaleziono klienta."})
    st = member_status(member)
    if st == "expired":
        return jsonify({"success": False, "message": "Karnet wygasł."})
    if st == "frozen":
        return jsonify({"success": False, "message": "Karnet zamrożony."})
    if member.get("entries_left") is not None and member["entries_left"] > 0:
        mongo.db.members.update_one({"_id": member["_id"]}, {"$inc": {"entries_left": -1}})
    elif member.get("entries_left") is not None and member["entries_left"] <= 0:
        return jsonify({"success": False, "message": "Brak pozostałych wejść."})
    mongo.db.checkins.insert_one({
        "member_id": str(member["_id"]), "checked_by": current_user.id,
        "timestamp": datetime.now(), "method": "scan"
    })
    mt = None
    if member.get("membership_type_id"):
        mt = mongo.db.membership_types.find_one({"_id": ObjectId(member["membership_type_id"])})
    return jsonify({
        "success": True, "message": f"Wejście zaliczone dla {member['name']}!",
        "member": {
            "name": member["name"],
            "membership_type": mt["name"] if mt else "Brak",
            "entries_left": member.get("entries_left", "-"),
        }
    })


@app.route("/checkin/manual", methods=["GET", "POST"])
@login_required
def checkin_manual():
    if request.method == "POST":
        member_id = request.form.get("member_id")
        member = mongo.db.members.find_one({"_id": ObjectId(member_id)})
        if not member:
            flash("Nie znaleziono klienta.", "danger")
            return redirect(url_for("checkin_manual"))
        st = member_status(member)
        if st == "expired":
            flash("Karnet wygasł.", "danger"); return redirect(url_for("checkin_manual"))
        if st == "frozen":
            flash("Karnet zamrożony.", "danger"); return redirect(url_for("checkin_manual"))
        if member.get("entries_left") is not None and member["entries_left"] > 0:
            mongo.db.members.update_one({"_id": member["_id"]}, {"$inc": {"entries_left": -1}})
        elif member.get("entries_left") is not None and member["entries_left"] <= 0:
            flash("Brak pozostałych wejść.", "danger"); return redirect(url_for("checkin_manual"))
        mongo.db.checkins.insert_one({
            "member_id": str(member["_id"]), "checked_by": current_user.id,
            "timestamp": datetime.now(), "method": "manual"
        })
        flash(f"Wejście zaliczone dla {member['name']}!", "success")
        return redirect(url_for("checkin_manual"))
    search = request.args.get("search", "").strip()
    members = []
    if search:
        for m in mongo.db.members.find({"$or": [
            {"name": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
            {"qr_code": {"$regex": search, "$options": "i"}},
        ]}).limit(20):
            st = member_status(m)
            members.append({"member": m, "status": st})
    return render_template("checkin_manual.html", members=members, search=search)


# ===================== HISTORY =====================

@app.route("/history")
@login_required
def history():
    page = int(request.args.get("page", 1))
    per_page = 30
    skip = (page - 1) * per_page
    total = mongo.db.checkins.count_documents({})
    checkins = list(mongo.db.checkins.find().sort("timestamp", -1).skip(skip).limit(per_page))
    for c in checkins:
        c["member"] = mongo.db.members.find_one({"_id": ObjectId(c["member_id"])}) if ObjectId.is_valid(c["member_id"]) else None
        c["checker"] = mongo.db.users.find_one({"_id": ObjectId(c["checked_by"])}) if ObjectId.is_valid(c["checked_by"]) else None
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template("history.html", checkins=checkins, page=page, total_pages=total_pages, total=total)


# ===================== REPORTS =====================

@app.route("/reports")
@login_required
@admin_required
def reports():
    today = date.today()
    month_start = date(today.year, today.month, 1)
    monthly_checkins = mongo.db.checkins.count_documents({
        "timestamp": {"$gte": datetime(month_start.year, month_start.month, month_start.day)}
    })
    pipeline = [{"$group": {"_id": "$membership_type_id", "count": {"$sum": 1}}}]
    members_by_type = list(mongo.db.members.aggregate(pipeline))
    for mbt in members_by_type:
        if mbt["_id"]:
            t = mongo.db.membership_types.find_one({"_id": ObjectId(mbt["_id"])})
            mbt["name"] = t["name"] if t else "Nieznany"
        else:
            mbt["name"] = "Brak karnetu"
    daily_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        count = mongo.db.checkins.count_documents({
            "timestamp": {"$gte": datetime(d.year, d.month, d.day), "$lt": datetime(d.year, d.month, d.day) + timedelta(days=1)}
        })
        daily_data.append({"date": d.strftime("%d.%m"), "count": count})
    top_members = list(mongo.db.checkins.aggregate([
        {"$group": {"_id": "$member_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 10}
    ]))
    for tm in top_members:
        tm["member"] = mongo.db.members.find_one({"_id": ObjectId(tm["_id"])}) if ObjectId.is_valid(tm["_id"]) else None
    return render_template("reports.html", monthly_checkins=monthly_checkins,
                           members_by_type=members_by_type, daily_data=daily_data, top_members=top_members)


# ===================== CHARTS API =====================

@app.route("/api/charts/dashboard")
@login_required
def api_charts_dashboard():
    today = date.today()
    labels = []; daily_data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%d.%m"))
        count = mongo.db.checkins.count_documents({
            "timestamp": {"$gte": datetime(d.year, d.month, d.day), "$lt": datetime(d.year, d.month, d.day) + timedelta(days=1)}
        })
        daily_data.append(count)
    pie_labels = []; pie_data = []
    for item in mongo.db.members.aggregate([{"$group": {"_id": "$membership_type_id", "count": {"$sum": 1}}}]):
        if item["_id"]:
            t = mongo.db.membership_types.find_one({"_id": ObjectId(item["_id"])})
            name = t["name"] if t else "Nieznany"
        else:
            name = "Brak"
        pie_labels.append(name); pie_data.append(item["count"])
    month_start = date(today.year, today.month, 1)
    monthly_checkins = mongo.db.checkins.count_documents({
        "timestamp": {"$gte": datetime(month_start.year, month_start.month, month_start.day)}
    })
    total = mongo.db.members.count_documents({})
    active = sum(1 for m in mongo.db.members.find() if member_status(m) == "active")
    return jsonify({
        "daily_labels": labels, "daily_data": daily_data,
        "pie_labels": pie_labels, "pie_data": pie_data,
        "monthly_checkins": monthly_checkins,
        "total_members": total, "active_members": active
    })


# ===================== CSV EXPORT =====================

@app.route("/export/members")
@login_required
def export_members():
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Imię i nazwisko", "Telefon", "Email", "Kod QR", "Status", "Karnet", "Data startu", "Data ważności", "Pozostało wejść", "Notatki"])
    for m in mongo.db.members.find().sort("name", 1):
        mt = None
        if m.get("membership_type_id"):
            mt = mongo.db.membership_types.find_one({"_id": ObjectId(m["membership_type_id"])})
        st = member_status(m)
        writer.writerow([m["name"], m.get("phone", ""), m.get("email", ""), m.get("qr_code", ""), st,
                         mt["name"] if mt else "", str(to_date(m.get("start_date"))) if m.get("start_date") else "",
                         str(to_date(m.get("end_date"))) if m.get("end_date") else "", m.get("entries_left", ""), m.get("notes", "")])
    output.seek(0)
    from flask import Response
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=klienci.csv", "Content-Type": "text/csv; charset=utf-8"})


@app.route("/export/history")
@login_required
def export_history():
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Data", "Klient", "Metoda", "Pracownik"])
    for c in mongo.db.checkins.find().sort("timestamp", -1):
        member = mongo.db.members.find_one({"_id": ObjectId(c["member_id"])}) if ObjectId.is_valid(c["member_id"]) else None
        checker = mongo.db.users.find_one({"_id": ObjectId(c["checked_by"])}) if ObjectId.is_valid(c["checked_by"]) else None
        writer.writerow([c["timestamp"].strftime("%d.%m.%Y %H:%M") if isinstance(c.get("timestamp"), datetime) else str(c.get("timestamp", "")),
                         member["name"] if member else "Usunięty", c.get("method", ""), checker["name"] if checker else ""])
    output.seek(0)
    from flask import Response
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=historia_wejsc.csv", "Content-Type": "text/csv; charset=utf-8"})


# ===================== CLIENT PORTAL =====================

@app.route("/client")
def client_home():
    return redirect(url_for("client_login"))


@app.route("/client/login", methods=["GET", "POST"])
def client_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or "@" not in email:
            flash("Podaj prawidłowy adres email.", "danger")
            return render_template("client_login.html")
        code = "".join(random.choices(string.digits, k=6))
        mongo.db.verification_codes.insert_one({
            "email": email, "code": code,
            "created_at": datetime.now(),
            "used": False
        })
        sent = send_email(
            email,
            f"Twój kod weryfikacyjny - {app.config['APP_NAME']}",
            f"""
            <div style="font-family: 'Inter', sans-serif; max-width: 480px; margin: 0 auto; background: #0f0f1f; border-radius: 24px; padding: 40px; text-align: center;">
                <div style="font-size: 48px; margin-bottom: 20px;">💪</div>
                <h2 style="color: #00f0ff; margin-bottom: 8px;">{app.config['APP_NAME']}</h2>
                <p style="color: #9898b8; margin-bottom: 24px;">Twój kod weryfikacyjny</p>
                <div style="background: #1a1a30; border-radius: 16px; padding: 20px; margin-bottom: 24px;">
                    <span style="font-size: 36px; letter-spacing: 12px; font-weight: 800; color: #00f0ff;">{code}</span>
                </div>
                <p style="color: #5a5a7a; font-size: 13px;">Kod ważny przez 10 minut.</p>
            </div>
            """
        )
        if sent:
            session["client_email"] = email
            flash("Kod wysłany na Twój email!", "success")
            return redirect(url_for("client_verify"))
        else:
            flash(f"Nie udało się wysłać maila. Skontaktuj się z recepcją. Twój kod: {code}", "warning")
            session["client_email"] = email
            session["dev_code"] = code
            return redirect(url_for("client_verify"))
    return render_template("client_login.html")


@app.route("/client/verify", methods=["GET", "POST"])
def client_verify():
    email = session.get("client_email")
    if not email:
        return redirect(url_for("client_login"))
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        dev_code = session.get("dev_code")
        valid = mongo.db.verification_codes.find_one({
            "email": email, "code": code, "used": False,
            "created_at": {"$gte": datetime.now() - timedelta(minutes=10)}
        })
        if valid or (dev_code and code == dev_code):
            if valid:
                mongo.db.verification_codes.update_one({"_id": valid["_id"]}, {"$set": {"used": True}})
            session["client_verified"] = True
            session.pop("dev_code", None)
            flash("Zweryfikowano pomyślnie!", "success")
            return redirect(url_for("client_dashboard"))
        flash("Nieprawidłowy kod.", "danger")
    return render_template("client_verify.html")


@app.route("/client/dashboard")
def client_dashboard():
    if not session.get("client_verified") or not session.get("client_email"):
        return redirect(url_for("client_login"))
    email = session["client_email"]
    member = mongo.db.members.find_one({"email": email})
    purchases = list(mongo.db.purchases.find({"email": email}).sort("created_at", -1))
    return render_template("client_dashboard.html", member=member, purchases=purchases)


@app.route("/client/logout")
def client_logout():
    session.clear()
    return redirect(url_for("client_login"))


@app.route("/client/buy")
def client_buy():
    if not session.get("client_verified") or not session.get("client_email"):
        return redirect(url_for("client_login"))
    types = list(mongo.db.membership_types.find())
    return render_template("client_buy.html", types=types, STRIPE_PUBLISHABLE_KEY=STRIPE_PUBLISHABLE_KEY)


@app.route("/client/create-checkout-session", methods=["POST"])
def client_create_checkout():
    if not session.get("client_verified") or not session.get("client_email"):
        return jsonify({"error": "Unauthorized"}), 401
    type_id = request.form.get("type_id")
    mt = mongo.db.membership_types.find_one({"_id": ObjectId(type_id)})
    if not mt:
        return jsonify({"error": "Invalid type"}), 400
    email = session["client_email"]
    try:
        checkout_session = stripe.checkout.Session.create(
            line_items=[{
                "price_data": {
                    "currency": "pln",
                    "product_data": {"name": mt["name"], "description": mt.get("description", "")},
                    "unit_amount": int(mt["price"] * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=request.host_url + "client/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.host_url + "client/buy",
            customer_email=email,
            metadata={"type_id": type_id, "email": email}
        )
        return jsonify({"url": checkout_session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/client/success")
def client_success():
    session_id = request.args.get("session_id")
    if not session_id:
        return redirect(url_for("client_dashboard"))
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        if checkout_session.payment_status == "paid":
            email = checkout_session.customer_email
            type_id = checkout_session.metadata.get("type_id")
            mt = mongo.db.membership_types.find_one({"_id": ObjectId(type_id)})
            if mt and email:
                existing = mongo.db.members.find_one({"email": email})
                qr_code = str(uuid.uuid4())[:8].upper()
                now = datetime.now()
                purchase_data = {
                    "email": email, "type_id": type_id,
                    "type_name": mt["name"], "amount": mt["price"],
                    "stripe_session": session_id, "created_at": now
                }
                mongo.db.purchases.insert_one(purchase_data)
                if existing:
                    flash(f"Karnet {mt['name']} opłacony! Możesz go odebrać w recepcji.", "success")
                else:
                    mongo.db.members.insert_one({
                        "name": email.split("@")[0], "phone": "", "email": email,
                        "membership_type_id": type_id, "notes": "Zakup online",
                        "qr_code": qr_code, "status": "active",
                        "created_at": now, "created_by": None,
                        "start_date": now,
                        **({"end_date": now + timedelta(days=mt["duration_days"]), "entries_left": None, "total_entries": None}
                           if mt["type"] == "period" else
                           {"end_date": None, "entries_left": mt["entries_count"], "total_entries": mt["entries_count"]})
                    })
                    flash(f"Karnet {mt['name']} aktywowany! Twój kod QR: {qr_code}", "success")
            flash("Płatność zakończona sukcesem!", "success")
    except Exception as e:
        flash(f"Błąd weryfikacji płatności: {e}", "danger")
    return redirect(url_for("client_dashboard"))


# ===================== SEARCH API =====================

@app.route("/api/members/search")
@login_required
def api_members_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    members = []
    for m in mongo.db.members.find({"$or": [
        {"name": {"$regex": q, "$options": "i"}},
        {"phone": {"$regex": q, "$options": "i"}},
        {"qr_code": {"$regex": q, "$options": "i"}},
    ]}).limit(10):
        members.append({"id": str(m["_id"]), "name": m["name"], "phone": m.get("phone", ""), "qr_code": m.get("qr_code", "")})
    return jsonify(members)


# ===================== ACTIVITY LOG =====================

@app.route("/api/activity/<member_id>")
@login_required
def api_activity(member_id):
    activities = []
    for c in mongo.db.checkins.find({"member_id": member_id}).sort("timestamp", -1).limit(20):
        checker = mongo.db.users.find_one({"_id": ObjectId(c["checked_by"])}) if ObjectId.is_valid(c["checked_by"]) else None
        activities.append({
            "type": "checkin", "icon": "bi-door-open", "title": "Wejście na siłownię",
            "desc": f"Metoda: {c.get('method', '?')}",
            "time": c["timestamp"].strftime("%d.%m.%Y %H:%M") if isinstance(c.get("timestamp"), datetime) else str(c.get("timestamp", "")),
            "by": checker["name"] if checker else "?"
        })
    activities.sort(key=lambda x: x["time"], reverse=True)
    return jsonify(activities[:30])


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
