import os
import sqlite3
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_SECRET_KEY")

DATABASE = os.environ.get("DATABASE_PATH", "database.db")

# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            account_type TEXT DEFAULT 'customer',
            balance REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT '',
            customer_price REAL DEFAULT 0,
            reseller_price REAL DEFAULT 0,
            video_url TEXT DEFAULT '',
            update_url TEXT DEFAULT '',
            payment_mode TEXT DEFAULT 'global',
            custom_payment_url TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            key_value TEXT NOT NULL,
            is_sold INTEGER DEFAULT 0,
            sold_to INTEGER,
            sold_at TIMESTAMP,
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            key_id INTEGER,
            price REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS special_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            UNIQUE(user_id, product_id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            payment_mode TEXT DEFAULT 'global',
            payment_api_url TEXT DEFAULT '',
            payment_api_key TEXT DEFAULT '',
            payment_qr_url TEXT DEFAULT '',
            telegram_update_url TEXT DEFAULT '',
            support_url TEXT DEFAULT ''
        )
    """)

    db.execute("""
        INSERT OR IGNORE INTO settings
        (id, payment_mode)
        VALUES (1, 'global')
    """)

    # Default admin account
    admin = db.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin:
        db.execute("""
            INSERT INTO users
            (username, password, account_type)
            VALUES (?, ?, ?)
        """, (
            "admin",
            generate_password_hash("admin123"),
            "admin"
        ))

    db.commit()
    db.close()


init_db()


# =========================================================
# HELPERS
# =========================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    db.close()

    return user


@app.context_processor
def inject_user():
    return {
        "current_user": current_user()
    }


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()

        if not user or user["account_type"] != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated


def get_product_price(user, product_id):
    db = get_db()

    product = db.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()

    if not product:
        db.close()
        return None

    # Special customer price has highest priority
    special = db.execute("""
        SELECT price
        FROM special_prices
        WHERE user_id = ? AND product_id = ?
    """, (
        user["id"],
        product_id
    )).fetchone()

    db.close()

    if special:
        return float(special["price"])

    if user["account_type"] == "reseller":
        return float(product["reseller_price"])

    return float(product["customer_price"])


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("index.html")


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for("register"))

        db = get_db()

        existing = db.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if existing:
            db.close()
            flash("Username already exists.", "error")
            return redirect(url_for("register"))

        db.execute("""
            INSERT INTO users
            (username, password, account_type)
            VALUES (?, ?, ?)
        """, (
            username,
            generate_password_hash(password),
            "customer"
        ))

        db.commit()
        db.close()

        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()

        user = db.execute("""
            SELECT *
            FROM users
            WHERE username = ?
        """, (username,)).fetchone()

        db.close()

        if not user or not check_password_hash(
            user["password"],
            password
        ):
            flash("Invalid username or password.", "error")
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user["id"]

        if user["account_type"] == "admin":
            return redirect(url_for("admin"))

        return redirect(url_for("dashboard"))

    return render_template("login.html")


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# CUSTOMER DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = current_user()

    if user["account_type"] == "admin":
        return redirect(url_for("admin"))

    db = get_db()

    products = db.execute("""
        SELECT *
        FROM products
        WHERE active = 1
        ORDER BY id DESC
    """).fetchall()

    db.close()

    return render_template(
        "dashboard.html",
        products=products
    )


# =========================================================
# PRODUCT PAGE
# =========================================================

@app.route("/product/<int:product_id>")
@login_required
def product_page(product_id):

    user = current_user()

    db = get_db()

    product = db.execute("""
        SELECT *
        FROM products
        WHERE id = ? AND active = 1
    """, (product_id,)).fetchone()

    if not product:
        db.close()
        flash("Product not found.", "error")
        return redirect(url_for("dashboard"))

    stock = db.execute("""
        SELECT COUNT(*) AS total
        FROM keys
        WHERE product_id = ?
        AND is_sold = 0
    """, (product_id,)).fetchone()["total"]

    db.close()

    price = get_product_price(user, product_id)

    return render_template(
        "product.html",
        product=product,
        price=price,
        stock=stock
    )


# =========================================================
# PURCHASE
# =========================================================

@app.route("/buy/<int:product_id>", methods=["POST"])
@login_required
def buy_product(product_id):

    user = current_user()

    if user["account_type"] == "admin":
        flash("Admin cannot purchase products.", "error")
        return redirect(url_for("admin"))

    db = get_db()

    product = db.execute("""
        SELECT *
        FROM products
        WHERE id = ? AND active = 1
    """, (product_id,)).fetchone()

    if not product:
        db.close()
        flash("Product not found.", "error")
        return redirect(url_for("dashboard"))

    # Find available key
    key = db.execute("""
        SELECT *
        FROM keys
        WHERE product_id = ?
        AND is_sold = 0
        ORDER BY id ASC
        LIMIT 1
    """, (product_id,)).fetchone()

    if not key:
        db.close()
        flash("Out of stock.", "error")
        return redirect(
            url_for("product_page", product_id=product_id)
        )

    # Special / reseller / customer price
    special = db.execute("""
        SELECT price
        FROM special_prices
        WHERE user_id = ? AND product_id = ?
    """, (
        user["id"],
        product_id
    )).fetchone()

    if special:
        price = float(special["price"])
    elif user["account_type"] == "reseller":
        price = float(product["reseller_price"])
    else:
        price = float(product["customer_price"])

    balance = float(user["balance"])

    if balance < price:
        db.close()
        flash(
            f"Insufficient balance. Required ₹{price:.2f}.",
            "error"
        )
        return redirect(
            url_for("product_page", product_id=product_id)
        )

    new_balance = balance - price

    # Deduct balance
    db.execute("""
        UPDATE users
        SET balance = ?
        WHERE id = ?
    """, (
        new_balance,
        user["id"]
    ))

    # Mark key sold
    db.execute("""
        UPDATE keys
        SET
            is_sold = 1,
            sold_to = ?,
            sold_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        user["id"],
        key["id"]
    ))

    # Create order
    db.execute("""
        INSERT INTO orders
        (user_id, product_id, key_id, price)
        VALUES (?, ?, ?, ?)
    """, (
        user["id"],
        product_id,
        key["id"],
        price
    ))

    db.commit()
    db.close()

    return render_template(
        "purchase_success.html",
        product=product,
        key_value=key["key_value"],
        price=price
    )


# =========================================================
# ORDERS
# =========================================================

@app.route("/orders")
@login_required
def orders():

    user = current_user()

    db = get_db()

    orders_list = db.execute("""
        SELECT
            orders.*,
            products.name AS product_name,
            products.category AS category,
            keys.key_value AS key_value
        FROM orders

        LEFT JOIN products
            ON products.id = orders.product_id

        LEFT JOIN keys
            ON keys.id = orders.key_id

        WHERE orders.user_id = ?

        ORDER BY orders.id DESC
    """, (
        user["id"],
    )).fetchall()

    db.close()

    return render_template(
        "orders.html",
        orders=orders_list
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@admin_required
def admin():

    db = get_db()

    products = db.execute("""
        SELECT
            products.*,
            (
                SELECT COUNT(*)
                FROM keys
                WHERE keys.product_id = products.id
                AND keys.is_sold = 0
            ) AS stock
        FROM products
        ORDER BY products.id DESC
    """).fetchall()

    users = db.execute("""
        SELECT *
        FROM users
        ORDER BY id DESC
    """).fetchall()

    orders_list = db.execute("""
        SELECT
            orders.*,
            users.username,
            products.name AS product_name
        FROM orders
        JOIN users
            ON users.id = orders.user_id
        JOIN products
            ON products.id = orders.product_id
        ORDER BY orders.id DESC
        LIMIT 50
    """).fetchall()

    settings = db.execute("""
        SELECT *
        FROM settings
        WHERE id = 1
    """).fetchone()

    db.close()

    return render_template(
        "admin.html",
        products=products,
        users=users,
        orders=orders_list,
        settings=settings
    )


# =========================================================
# ADD PRODUCT
# =========================================================

@app.route("/admin/product/add", methods=["POST"])
@admin_required
def add_product():

    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()

    customer_price = request.form.get(
        "customer_price",
        "0"
    )

    reseller_price = request.form.get(
        "reseller_price",
        "0"
    )

    video_url = request.form.get(
        "video_url",
        ""
    ).strip()

    update_url = request.form.get(
        "update_url",
        ""
    ).strip()

    payment_mode = request.form.get(
        "payment_mode",
        "global"
    )

    custom_payment_url = request.form.get(
        "custom_payment_url",
        ""
    ).strip()

    if not name or not category:
        flash("Product name and category are required.", "error")
        return redirect(url_for("admin"))

    try:
        customer_price = float(customer_price)
        reseller_price = float(reseller_price)
    except ValueError:
        flash("Invalid price.", "error")
        return redirect(url_for("admin"))

    db = get_db()

    db.execute("""
        INSERT INTO products
        (
            name,
            category,
            description,
            customer_price,
            reseller_price,
            video_url,
            update_url,
            payment_mode,
            custom_payment_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        category,
        description,
        customer_price,
        reseller_price,
        video_url,
        update_url,
        payment_mode,
        custom_payment_url
    ))

    db.commit()
    db.close()

    flash("Product added successfully.", "success")
    return redirect(url_for("admin"))


# =========================================================
# EDIT PRODUCT
# =========================================================

@app.route(
    "/admin/product/<int:product_id>/edit",
    methods=["GET", "POST"]
)
@admin_required
def edit_product(product_id):

    db = get_db()

    product = db.execute("""
        SELECT *
        FROM products
        WHERE id = ?
    """, (product_id,)).fetchone()

    if not product:
        db.close()
        flash("Product not found.", "error")
        return redirect(url_for("admin"))

    if request.method == "POST":

        name = request.form.get(
            "name",
            product["name"]
        ).strip()

        category = request.form.get(
            "category",
            product["category"]
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        try:
            customer_price = float(
                request.form.get(
                    "customer_price",
                    product["customer_price"]
                )
            )

            reseller_price = float(
                request.form.get(
                    "reseller_price",
                    product["reseller_price"]
                )
            )

        except ValueError:
            db.close()
            flash("Invalid price.", "error")
            return redirect(
                url_for(
                    "edit_product",
                    product_id=product_id
                )
            )

        video_url = request.form.get(
            "video_url",
            ""
        ).strip()

        update_url = request.form.get(
            "update_url",
            ""
        ).strip()

        payment_mode = request.form.get(
            "payment_mode",
            "global"
        )

        custom_payment_url = request.form.get(
            "custom_payment_url",
            ""
        ).strip()

        active = 1 if request.form.get(
            "active"
        ) else 0

        db.execute("""
            UPDATE products
            SET
                name = ?,
                category = ?,
                description = ?,
                customer_price = ?,
                reseller_price = ?,
                video_url = ?,
                update_url = ?,
                payment_mode = ?,
                custom_payment_url = ?,
                active = ?
            WHERE id = ?
        """, (
            name,
            category,
            description,
            customer_price,
            reseller_price,
            video_url,
            update_url,
            payment_mode,
            custom_payment_url,
            active,
            product_id
        ))

        db.commit()
        db.close()

        flash("Product updated.", "success")
        return redirect(url_for("admin"))

    db.close()

    return render_template(
        "edit_product.html",
        product=product
    )


# =========================================================
# DELETE PRODUCT
# =========================================================

@app.route(
    "/admin/product/<int:product_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_product(product_id):

    db = get_db()

    db.execute("""
        DELETE FROM special_prices
        WHERE product_id = ?
    """, (product_id,))

    db.execute("""
        DELETE FROM keys
        WHERE product_id = ?
        AND is_sold = 0
    """, (product_id,))

    db.execute("""
        DELETE FROM products
        WHERE id = ?
    """, (product_id,))

    db.commit()
    db.close()

    flash("Product deleted.", "success")
    return redirect(url_for("admin"))


# =========================================================
# ADD KEYS
# =========================================================

@app.route(
    "/admin/product/<int:product_id>/keys",
    methods=["GET", "POST"]
)
@admin_required
def manage_keys(product_id):

    db = get_db()

    product = db.execute("""
        SELECT *
        FROM products
        WHERE id = ?
    """, (product_id,)).fetchone()

    if not product:
        db.close()
        flash("Product not found.", "error")
        return redirect(url_for("admin"))

    if request.method == "POST":

        keys_text = request.form.get(
            "keys",
            ""
        ).strip()

        key_lines = [
            line.strip()
            for line in keys_text.splitlines()
            if line.strip()
        ]

        added = 0

        for key_value in key_lines:

            db.execute("""
                INSERT INTO keys
                (product_id, key_value)
                VALUES (?, ?)
            """, (
                product_id,
                key_value
            ))

            added += 1

        db.commit()

        flash(
            f"{added} key(s) added successfully.",
            "success"
        )

    keys = db.execute("""
        SELECT *
        FROM keys
        WHERE product_id = ?
        ORDER BY id DESC
    """, (product_id,)).fetchall()

    db.close()

    return render_template(
        "manage_keys.html",
        product=product,
        keys=keys
    )


# =========================================================
# DELETE UNSOLD KEY
# =========================================================

@app.route(
    "/admin/key/<int:key_id>/delete",
    methods=["POST"]
)
@admin_required
def delete_key(key_id):

    db = get_db()

    db.execute("""
        DELETE FROM keys
        WHERE id = ?
        AND is_sold = 0
    """, (key_id,))

    db.commit()
    db.close()

    flash("Available key deleted.", "success")
    return redirect(url_for("admin"))


# =========================================================
# SPECIAL CUSTOMER PRICE
# =========================================================

@app.route(
    "/admin/special-price",
    methods=["POST"]
)
@admin_required
def special_price():

    username = request.form.get(
        "username",
        ""
    ).strip()

    product_id = request.form.get(
        "product_id"
    )

    price = request.form.get(
        "price"
    )

    if not username or not product_id or not price:
        flash(
            "Username, product and price are required.",
            "error"
        )
        return redirect(url_for("admin"))

    try:
        product_id = int(product_id)
        price = float(price)
    except ValueError:
        flash("Invalid product or price.", "error")
        return redirect(url_for("admin"))

    db = get_db()

    user = db.execute("""
        SELECT id
        FROM users
        WHERE username = ?
    """, (username,)).fetchone()

    if not user:
        db.close()
        flash("Customer not found.", "error")
        return redirect(url_for("admin"))

    db.execute("""
        INSERT INTO special_prices
        (user_id, product_id, price)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, product_id)
        DO UPDATE SET price = excluded.price
    """, (
        user["id"],
        product_id,
        price
    ))

    db.commit()
    db.close()

    flash(
        "Special customer price saved.",
        "success"
    )

    return redirect(url_for("admin"))


# =========================================================
# ADD / REMOVE BALANCE
# =========================================================

@app.route(
    "/admin/user/balance",
    methods=["POST"]
)
@admin_required
def update_balance():

    username = request.form.get(
        "username",
        ""
    ).strip()

    amount = request.form.get(
        "amount",
        "0"
    )

    action = request.form.get(
        "action",
        "add"
    )

    try:
        amount = float(amount)
    except ValueError:
        flash("Invalid amount.", "error")
        return redirect(url_for("admin"))

    if amount < 0:
        flash("Amount cannot be negative.", "error")
        return redirect(url_for("admin"))

    db = get_db()

    user = db.execute("""
        SELECT *
        FROM users
        WHERE username = ?
    """, (username,)).fetchone()

    if not user:
        db.close()
        flash("User not found.", "error")
        return redirect(url_for("admin"))

    balance = float(user["balance"])

    if action == "add":
        new_balance = balance + amount
    else:
        new_balance = max(0, balance - amount)

    db.execute("""
        UPDATE users
        SET balance = ?
        WHERE id = ?
    """, (
        new_balance,
        user["id"]
    ))

    db.commit()
    db.close()

    flash(
        f"Balance updated. New balance: ₹{new_balance:.2f}",
        "success"
    )

    return redirect(url_for("admin"))


# =========================================================
# CHANGE ACCOUNT TYPE
# =========================================================

@app.route(
    "/admin/user/<int:user_id>/type",
    methods=["POST"]
)
@admin_required
def change_account_type(user_id):

    account_type = request.form.get(
        "account_type",
        "customer"
    )

    if account_type not in (
        "customer",
        "reseller"
    ):
        flash("Invalid account type.", "error")
        return redirect(url_for("admin"))

    db = get_db()

    db.execute("""
        UPDATE users
        SET account_type = ?
        WHERE id = ?
    """, (
        account_type,
        user_id
    ))

    db.commit()
    db.close()

    flash("Account type updated.", "success")
    return redirect(url_for("admin"))


# =========================================================
# GLOBAL PAYMENT SETTINGS
# =========================================================

@app.route(
    "/admin/settings",
    methods=["POST"]
)
@admin_required
def payment_settings():

    payment_mode = request.form.get(
        "payment_mode",
        "global"
    )

    payment_api_url = request.form.get(
        "payment_api_url",
        ""
    ).strip()

    payment_api_key = request.form.get(
        "payment_api_key",
        ""
    ).strip()

    payment_qr_url = request.form.get(
        "payment_qr_url",
        ""
    ).strip()

    telegram_update_url = request.form.get(
        "telegram_update_url",
        ""
    ).strip()

    support_url = request.form.get(
        "support_url",
        ""
    ).strip()

    db = get_db()

    db.execute("""
        UPDATE settings
        SET
            payment_mode = ?,
            payment_api_url = ?,
            payment_api_key = ?,
            payment_qr_url = ?,
            telegram_update_url = ?,
            support_url = ?
        WHERE id = 1
    """, (
        payment_mode,
        payment_api_url,
        payment_api_key,
        payment_qr_url,
        telegram_update_url,
        support_url
    ))

    db.commit()
    db.close()

    flash(
        "Payment settings updated.",
        "success"
    )

    return redirect(url_for("admin"))


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():
    return "KP Panel is running."


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
