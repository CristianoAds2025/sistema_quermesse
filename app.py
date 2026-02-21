
from flask import Flask, render_template, request, redirect, session, send_file, flash
import mysql.connector
import os
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import A4
from openpyxl import Workbook
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "quermesse_secret"

# =========================
# CONEXÃO MYSQL
# =========================
def conectar():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 3306)),
        connection_timeout=5
    )
# =========================
# LOGIN
# =========================
@app.route("/")
def login():
    return render_template("login.html")

@app.route("/autenticar", methods=["POST"])
def autenticar():
    usuario = request.form["usuario"]
    senha = request.form["senha"]

    conn = conectar()
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM usuarios WHERE usuario=%s", (usuario,))
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user["senha"], senha):
        session["usuario"] = usuario
        return redirect("/dashboard")

    flash("Usuário ou senha inválidos", "danger")
    return redirect("/")

# =========================
# CADASTRO USUÁRIO
# =========================
@app.route("/cadastro", methods=["GET","POST"])
def cadastro():
    if request.method == "POST":
        usuario = request.form["usuario"]
        senha = generate_password_hash(request.form["senha"])

        conn = conectar()
        c = conn.cursor()
        c.execute("INSERT INTO usuarios (usuario, senha) VALUES (%s,%s)", (usuario, senha))
        conn.commit()
        conn.close()

        flash("Usuário cadastrado com sucesso!", "success")
        return redirect("/")

    return render_template("cadastro.html")

# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():
    if "usuario" not in session:
        return redirect("/")
    return render_template("dashboard.html")

# =========================
# PRODUTOS
# =========================
@app.route("/produtos", methods=["GET","POST"])
def produtos():
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor(dictionary=True)

    if request.method == "POST":
        descricao = request.form["descricao"]
        valor = float(request.form["valor"].replace(",", "."))
        estoque = int(request.form["estoque"])

        c.execute("INSERT INTO produtos (descricao, valor, estoque) VALUES (%s,%s,%s)",
                  (descricao, valor, estoque))
        conn.commit()
        flash("Produto cadastrado com sucesso!", "success")

    c.execute("SELECT * FROM produtos")
    lista = c.fetchall()
    conn.close()

    return render_template("produtos.html", produtos=lista)

# =========================
# VENDAS
# =========================
@app.route("/vendas", methods=["GET","POST"])
def vendas():
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor(dictionary=True)

    c.execute("SELECT * FROM produtos")
    produtos = c.fetchall()

    if request.method == "POST":
        produto_id = int(request.form["produto"])
        quantidade = int(request.form["quantidade"])

        c.execute("SELECT * FROM produtos WHERE id=%s", (produto_id,))
        produto = c.fetchone()

        if quantidade > produto["estoque"]:
            flash("Estoque insuficiente!", "danger")
            return redirect("/vendas")

        total = produto["valor"] * quantidade
        novo_estoque = produto["estoque"] - quantidade

        c.execute("UPDATE produtos SET estoque=%s WHERE id=%s",
                  (novo_estoque, produto_id))

        c.execute("""INSERT INTO vendas 
                    (produto_id, quantidade, valor_total, data_venda)
                    VALUES (%s,%s,%s,%s)""",
                  (produto_id, quantidade, total, datetime.now()))

        conn.commit()
        flash("Venda realizada com sucesso!", "success")

    conn.close()
    return render_template("vendas.html", produtos=produtos)

# =========================
# RELATÓRIOS
# =========================
@app.route("/relatorios")
def relatorios():
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor(dictionary=True)

    c.execute("SELECT * FROM produtos")
    produtos = c.fetchall()

    c.execute("""
        SELECT v.id, p.descricao, v.quantidade, v.valor_total, v.data_venda
        FROM vendas v
        JOIN produtos p ON v.produto_id=p.id
        ORDER BY v.data_venda DESC
    """)
    vendas = c.fetchall()

    conn.close()
    return render_template("relatorios.html", produtos=produtos, vendas=vendas)

# =========================
# PDF
# =========================
@app.route("/relatorio_pdf")
def relatorio_pdf():
    conn = conectar()
    c = conn.cursor()
    c.execute("SELECT descricao, estoque FROM produtos")
    produtos = c.fetchall()
    conn.close()

    file_path = "relatorio.pdf"
    doc = SimpleDocTemplate(file_path, pagesize=A4)
    data = [["Produto","Estoque"]] + list(produtos)
    table = Table(data)
    doc.build([table])

    return send_file(file_path, as_attachment=True)

# =========================
# EXCEL
# =========================
@app.route("/relatorio_excel")
def relatorio_excel():
    conn = conectar()
    c = conn.cursor()
    c.execute("SELECT descricao, estoque FROM produtos")
    produtos = c.fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.append(["Produto","Estoque"])
    for p in produtos:
        ws.append(p)

    file_path = "relatorio.xlsx"
    wb.save(file_path)
    return send_file(file_path, as_attachment=True)

if __name__ == "__main__":
    app.run()
