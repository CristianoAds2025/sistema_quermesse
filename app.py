
from flask import Flask, render_template, request, redirect, session, send_file
import sqlite3
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import A4
from openpyxl import Workbook

app = Flask(__name__)
app.secret_key = "quermesse_secret"

DB = "database.db"

def conectar():
    return sqlite3.connect(DB)

def init_db():
    conn = conectar()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, senha TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS produtos (id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT, valor REAL, estoque INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS vendas (id INTEGER PRIMARY KEY AUTOINCREMENT, produto_id INTEGER, quantidade INTEGER, valor_total REAL, data TEXT)")
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def login():
    return render_template("login.html")

@app.route("/autenticar", methods=["POST"])
def autenticar():
    usuario = request.form["usuario"]
    senha = request.form["senha"]
    conn = conectar()
    c = conn.cursor()
    c.execute("SELECT * FROM usuarios WHERE usuario=? AND senha=?", (usuario, senha))
    user = c.fetchone()
    conn.close()
    if user:
        session["usuario"] = usuario
        return redirect("/dashboard")
    return "Login inválido"

@app.route("/cadastro", methods=["GET","POST"])
def cadastro():
    if request.method == "POST":
        usuario = request.form["usuario"]
        senha = request.form["senha"]
        conn = conectar()
        c = conn.cursor()
        c.execute("INSERT INTO usuarios (usuario, senha) VALUES (?,?)", (usuario, senha))
        conn.commit()
        conn.close()
        return redirect("/")
    return render_template("cadastro.html")

@app.route("/dashboard")
def dashboard():
    if "usuario" not in session:
        return redirect("/")
    return render_template("dashboard.html")

@app.route("/produtos", methods=["GET","POST"])
def produtos():
    conn = conectar()
    c = conn.cursor()
    if request.method == "POST":
        descricao = request.form["descricao"]
        valor = float(request.form["valor"])
        estoque = int(request.form["estoque"])
        c.execute("INSERT INTO produtos (descricao, valor, estoque) VALUES (?,?,?)", (descricao, valor, estoque))
        conn.commit()
    c.execute("SELECT * FROM produtos")
    lista = c.fetchall()
    conn.close()
    return render_template("produtos.html", produtos=lista)

@app.route("/vendas", methods=["GET","POST"])
def vendas():
    conn = conectar()
    c = conn.cursor()
    c.execute("SELECT * FROM produtos")
    produtos = c.fetchall()
    if request.method == "POST":
        produto_id = int(request.form["produto"])
        quantidade = int(request.form["quantidade"])
        c.execute("SELECT valor, estoque FROM produtos WHERE id=?", (produto_id,))
        p = c.fetchone()
        total = p[0] * quantidade
        novo = p[1] - quantidade
        c.execute("UPDATE produtos SET estoque=? WHERE id=?", (novo, produto_id))
        c.execute("INSERT INTO vendas (produto_id, quantidade, valor_total, data) VALUES (?,?,?,?)",
                  (produto_id, quantidade, total, datetime.now()))
        conn.commit()
    conn.close()
    return render_template("vendas.html", produtos=produtos)

@app.route("/relatorios")
def relatorios():
    conn = conectar()
    c = conn.cursor()
    c.execute("SELECT * FROM produtos")
    produtos = c.fetchall()
    c.execute("SELECT v.id, p.descricao, v.quantidade, v.valor_total, v.data FROM vendas v JOIN produtos p ON v.produto_id=p.id")
    vendas = c.fetchall()
    conn.close()
    return render_template("relatorios.html", produtos=produtos, vendas=vendas)

@app.route("/relatorio_pdf")
def relatorio_pdf():
    conn = conectar()
    c = conn.cursor()
    c.execute("SELECT descricao, estoque FROM produtos")
    produtos = c.fetchall()
    conn.close()

    file_path = "relatorio.pdf"
    doc = SimpleDocTemplate(file_path, pagesize=A4)
    data = [["Produto","Estoque"]] + produtos
    table = Table(data)
    doc.build([table])
    return send_file(file_path, as_attachment=True)

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
