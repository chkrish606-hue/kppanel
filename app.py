from flask import (
    Flask, render_template, request,
    redirect, session, flash
)
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
app = Flask(__name__)
app.secret_key = "KP_PANEL_CHANGE_THIS_SECRET"
DATABASE = "database.db"
# =========================
# ADMIN SETTINGS
# =========================
ADMIN_EMAIL = "admin@kppanel.com"
ADMIN_PASSWORD = "admin123"
# =========================
# DATABASE
# =========================
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn
def init_db():
    conn = get_db()
    # USERS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0,
            total_added REAL DEFAULT 0,
            order_count INTEGER DEFAULT 0,
            account_type TEXT DEFAULT 'customer',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # PRODUCTS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            duration TEXT NOT NULL,
            customer_price REAL DEFAULT 0,
            reseller_price REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # KEYS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            key_value TEXT NOT NULL,
            status TEXT DEFAULT 'available',
            sold_to INTEGER,
            sold_at TIMESTAMP,
            FOREIGN KEY(product_id)
                REFERENCES products(id)
        )
    """)
    # ORDERS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            key_id INTEGER,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'completed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id),
            FOREIGN KEY(product_id)
                REFERENCES products(id),
            FOREIGN KEY(key_id)
                REFERENCES keys(id)
        )
    """)
    # WALLET TRANSACTIONS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            status TEXT DEFAULT 'approved',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)
                REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()
# =========================
# LOGIN REQUIRED
# =========================
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect("/login")
        return func(*args, **kwargs)
    return wrapper
# =========================
# ADMIN REQUIRED
# =========================
def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin access required.")
            return redirect("/admin/login")
        return func(*args, **kwargs)
    return wrapper
# =========================
# HOME
# =========================
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return render_template("index.html")
# =========================
# REGISTER
# =========================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get(
            "username", ""
        ).strip()
        email = request.form.get(
            "email", ""
        ).strip().lower()
        password = request.form.get(
            "password", ""
        )
        if not username or not email or not password:
            flash("All fields are required.")
            return redirect("/register")
        if len(password) < 6:
            flash("Password must be at least 6 characters.")
            return redirect("/register")
        hashed_password = generate_password_hash(password)
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO users
                (username, email, password)
                VALUES (?, ?, ?)
            """, (
                username,
                email,
                hashed_password
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash(
                "Username or email already exists."
            )
            return redirect("/register")
        conn.close()
        flash("Account created successfully.")
        return redirect("/login")
    return render_template("register.html")
# =========================
# LOGIN
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get(
            "email", ""
        ).strip().lower()
        password = request.form.get(
            "password", ""
        )
        conn = get_db()
        user = conn.execute("""
            SELECT *
            FROM users
            WHERE email = ?
        """, (email,)).fetchone()
        conn.close()
        if user and check_password_hash(
            user["password"],
            password
        ):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect("/dashboard")
        flash("Invalid email or password.")
    return render_template("login.html")
# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        session["user_id"],
    )).fetchone()
    conn.close()
    return render_template(
        "dashboard.html",
        user=user
    )
# =========================
# SHOP
# =========================
@app.route("/shop")
@login_required
def shop():
    conn = get_db()
    products = conn.execute("""
        SELECT
            p.*,
            COUNT(
                CASE
                    WHEN k.status = 'available'
                    THEN 1
                END
            ) AS stock
        FROM products p
        LEFT JOIN keys k
            ON p.id = k.product_id
        GROUP BY p.id
        ORDER BY p.id DESC
    """).fetchall()
    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        session["user_id"],
    )).fetchone()
    conn.close()
    return render_template(
        "shop.html",
        products=products,
        user=user
    )
# =========================
# BUY PRODUCT
# =========================
@app.route("/buy/<int:product_id>", methods=["POST"])
@login_required
def buy_product(product_id):
    user_id = session["user_id"]
    conn = get_db()
    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (user_id,)).fetchone()
    product = conn.execute("""
        SELECT *
        FROM products
        WHERE id = ?
    """, (product_id,)).fetchone()
    if not product:
        conn.close()
        flash("Product not found.")
        return redirect("/shop")
    # Choose reseller price if reseller
    if user["account_type"] == "reseller":
        price = product["reseller_price"]
    else:
        price = product["customer_price"]
    # Find available key
    key = conn.execute("""
        SELECT *
        FROM keys
        WHERE product_id = ?
        AND status = 'available'
        ORDER BY id ASC
        LIMIT 1
    """, (product_id,)).fetchone()
    if not key:
        conn.close()
        flash("Out of stock.")
        return redirect("/shop")
    if user["balance"] < price:
        conn.close()
        flash("Insufficient wallet balance.")
        return redirect("/shop")
    # Deduct balance
    conn.execute("""
        UPDATE users
        SET
            balance = balance - ?,
            order_count = order_count + 1
        WHERE id = ?
    """, (
        price,
        user_id
    ))
    # Mark key sold
    conn.execute("""
        UPDATE keys
        SET
            status = 'sold',
            sold_to = ?,
            sold_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        user_id,
        key["id"]
    ))
    # Create order
    conn.execute("""
        INSERT INTO orders
        (
            user_id,
            product_id,
            key_id,
            amount,
            status
        )
        VALUES (?, ?, ?, ?, 'completed')
    """, (
        user_id,
        product_id,
        key["id"],
        price
    ))
    # Wallet transaction
    conn.execute("""
        INSERT INTO wallet_transactions
        (
            user_id,
            amount,
            type,
            status
        )
        VALUES (?, ?, 'purchase', 'approved')
    """, (
        user_id,
        -price
    ))
    conn.commit()
    conn.close()
    return render_template(
        "key_success.html",
        product=product,
        key_value=key["key_value"],
        price=price
    )
# =========================
# MY ORDERS
# =========================
@app.route("/orders")
@login_required
def orders():
    conn = get_db()
    orders = conn.execute("""
        SELECT
            o.*,
            p.name,
            p.category,
            p.duration,
            k.key_value
        FROM orders o
        JOIN products p
            ON o.product_id = p.id
        LEFT JOIN keys k
            ON o.key_id = k.id
        WHERE o.user_id = ?
        ORDER BY o.id DESC
    """, (
        session["user_id"],
    )).fetchall()
    conn.close()
    return render_template(
        "orders.html",
        orders=orders
    )
# =========================
# PROFILE
# =========================
@app.route("/profile")
@login_required
def profile():
    conn = get_db()
    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        session["user_id"],
    )).fetchone()
    conn.close()
    return render_template(
        "profile.html",
        user=user
    )
# =====================================================
# ADMIN LOGIN
# =====================================================
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get(
            "email", ""
        ).strip().lower()
        password = request.form.get(
            "password", ""
        )
        if (
            email == ADMIN_EMAIL
            and password == ADMIN_PASSWORD
        ):
            session["is_admin"] = True
            return redirect("/admin")
        flash("Invalid admin login.")
    return render_template(
        "admin_login.html"
    )
# =========================
# ADMIN LOGOUT
# =========================
@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")
# =========================
# ADMIN DASHBOARD
# =========================
@app.route("/admin")
@admin_required
def admin():
    conn = get_db()
    users_count = conn.execute("""
        SELECT COUNT(*) AS total
        FROM users
    """).fetchone()["total"]
    products_count = conn.execute("""
        SELECT COUNT(*) AS total
        FROM products
    """).fetchone()["total"]
    available_keys = conn.execute("""
        SELECT COUNT(*) AS total
        FROM keys
        WHERE status = 'available'
    """).fetchone()["total"]
    orders_count = conn.execute("""
        SELECT COUNT(*) AS total
        FROM orders
    """).fetchone()["total"]
    users = conn.execute("""
        SELECT *
        FROM users
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return render_template(
        "admin.html",
        users_count=users_count,
        products_count=products_count,
        available_keys=available_keys,
        orders_count=orders_count,
        users=users
    )
# =====================================================
# ADMIN ADD PRODUCT
# =====================================================
@app.route(
    "/admin/product/add",
    methods=["GET", "POST"]
)
@admin_required
def admin_add_product():
    if request.method == "POST":
        category = request.form.get(
            "category", ""
        ).strip()
        name = request.form.get(
            "name", ""
        ).strip()
        duration = request.form.get(
            "duration", ""
        ).strip()
        customer_price = float(
            request.form.get(
                "customer_price",
                0
            )
        )
        reseller_price = float(
            request.form.get(
                "reseller_price",
                0
            )
        )
        if not category or not name or not duration:
            flash("Please fill all product fields.")
            return redirect(
                "/admin/product/add"
            )
        conn = get_db()
        conn.execute("""
            INSERT INTO products
            (
                category,
                name,
                duration,
                customer_price,
                reseller_price
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            category,
            name,
            duration,
            customer_price,
            reseller_price
        ))
        conn.commit()
        conn.close()
        flash("Product added successfully.")
        return redirect("/admin")
    return render_template(
        "admin_add_product.html"
    )
# =====================================================
# ADMIN ADD KEY
# =====================================================
@app.route(
    "/admin/key/add",
    methods=["GET", "POST"]
)
@admin_required
def admin_add_key():
    conn = get_db()
    products = conn.execute("""
        SELECT *
        FROM products
        ORDER BY category, name
    """).fetchall()
    if request.method == "POST":
        product_id = request.form.get(
            "product_id"
        )
        key_value = request.form.get(
            "key_value", ""
        ).strip()
        if not product_id or not key_value:
            conn.close()
            flash("Product and key are required.")
            return redirect(
                "/admin/key/add"
            )
        conn.execute("""
            INSERT INTO keys
            (
                product_id,
                key_value,
                status
            )
            VALUES (?, ?, 'available')
        """, (
            product_id,
            key_value
        ))
        conn.commit()
        conn.close()
        flash("Key added successfully.")
        return redirect("/admin")
    conn.close()
    return render_template(
        "admin_add_key.html",
        products=products
    )
# =====================================================
# ADMIN ADD BALANCE
# =====================================================
@app.route(
    "/admin/balance",
    methods=["POST"]
)
@admin_required
def admin_balance():
    user_id = request.form.get(
        "user_id"
    )
    amount = float(
        request.form.get(
            "amount",
            0
        )
    )
    if amount <= 0:
        flash("Invalid amount.")
        return redirect("/admin")
    conn = get_db()
    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        user_id,
    )).fetchone()
    if not user:
        conn.close()
        flash("User not found.")
        return redirect("/admin")
    conn.execute("""
        UPDATE users
        SET
            balance = balance + ?,
            total_added = total_added + ?
        WHERE id = ?
    """, (
        amount,
        amount,
        user_id
    ))
    conn.execute("""
        INSERT INTO wallet_transactions
        (
            user_id,
            amount,
            type,
            status
        )
        VALUES (?, ?, 'admin_add', 'approved')
    """, (
        user_id,
        amount
    ))
    conn.commit()
    conn.close()
    flash(
        f"₹{amount:.2f} added successfully."
    )
    return redirect("/admin")
# =====================================================
# ADMIN REMOVE BALANCE
# =====================================================
@app.route(
    "/admin/balance/remove",
    methods=["POST"]
)
@admin_required
def admin_remove_balance():
    user_id = request.form.get(
        "user_id"
    )
    amount = float(
        request.form.get(
            "amount",
            0
        )
    )
    if amount <= 0:
        flash("Invalid amount.")
        return redirect("/admin")
    conn = get_db()
    user = conn.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        user_id,
    )).fetchone()
    if not user:
        conn.close()
        flash("User not found.")
        return redirect("/admin")
    new_balance = user["balance"] - amount
    if new_balance < 0:
        new_balance = 0
    conn.execute("""
        UPDATE users
        SET balance = ?
        WHERE id = ?
    """, (
        new_balance,
        user_id
    ))
    conn.execute("""
        INSERT INTO wallet_transactions
        (
            user_id,
            amount,
            type,
            status
        )
        VALUES (?, ?, 'admin_remove', 'approved')
    """, (
        user_id,
        -amount
    ))
    conn.commit()
    conn.close()
    flash("Balance updated.")
    return redirect("/admin")
# =========================
# START APP
# =========================
if __name__ == "__main__":
    init_db()
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
