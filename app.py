from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your_secret_key_here")

DB = "database.db"

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            duration TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0
        )
    """)
    admin = con.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not admin:
        con.execute("INSERT INTO users(username, email, password, is_admin) VALUES (?, ?, ?, ?)", ("admin", "admin@kppanel.local", "admin", 1))
    
    count = con.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    if count == 0:
        products = [
            ("iPhone Panel", "1 Hour", 15, 0),
            ("iPhone Panel", "2 Hour", 23, 0),
            ("iPhone Panel", "4 Hour", 30, 0),
            ("iPhone Panel", "24 Hour", 100, 0)
        ]
        con.executemany("INSERT INTO products(name, duration, price, stock) VALUES (?, ?, ?, ?)", products)
    
    con.commit()
    con.close()

# डेटाबेस इनिशियलाइज़ेशन फंक्शन को कॉल करें
init_db()

@app.context_processor
def common():
    return {
        "logged": "user_id" in session,
        "admin": session.get("is_admin", False)
    }

@app.route("/")
def home():
    con = db()
    products = con.execute("SELECT * FROM products ORDER BY id ASC").fetchall()
    con.close()
    return render_template("index.html", products=products)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"].strip()
        password = request.form["password"]
        confirm = request.form["confirm"]

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))
        
        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return redirect(url_for("register"))

        try:
            con = db()
            con.execute("INSERT INTO users(username, email, password) VALUES (?, ?, ?)", (username, email, password))
            con.commit()
            con.close()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "danger")
            return redirect(url_for("register"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        con = db()
        user = con.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        con.close()

        if user:
            session["user_id"] = user["id"]
            session["is_admin"] = bool(user["is_admin"])
            next_page = request.args.get("next")
            return redirect(next_page or url_for("home"))
        else:
            flash("Invalid username or password.", "danger")
            return render_template("login.html")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/buy/<int:product_id>", methods=["GET", "POST"])
def buy(product_id):
    if "user_id" not in session:
        return redirect(url_for("login", next=url_for("buy", product_id=product_id)))

    con = db()
    product = con.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        con.close()
        return "Product not found", 404

    qty = 1
    message = None

    if request.method == "POST":
        qty = max(1, int(request.form.get("qty", 1)))
        total = product["price"] * qty

        user = con.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

        if product["stock"] < qty:
            message = "Not enough stock."
        elif user["balance"] < total:
            message = "Insufficient balance."
        else:
            con.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (total, session["user_id"]))
            con.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, product_id))
            con.commit()
            message = f"Purchase successful! {total:.2f} deducted."

    con.close()
    return render_template("buy.html", product=product, qty=qty, message=message)

@app.route("/admin")
def admin_panel():
    if not session.get("is_admin"):
        return redirect(url_for("login"))
    
    con = db()
    products = con.execute("SELECT * FROM products ORDER BY id ASC").fetchall()
    con.close()
    return render_template("admin.html", products=products)

@app.route("/admin/product/delete", methods=["POST"])
def delete_product():
    if not session.get("is_admin"):
        return "Forbidden", 403

    pid = request.form.get("id")
    con = db()
    con.execute("DELETE FROM products WHERE id = ?", (pid,))
    con.commit()
    con.close()
    return redirect(url_for("admin_panel"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
