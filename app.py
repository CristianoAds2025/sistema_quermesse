
from flask import Flask, render_template, request, redirect, session, send_file, flash, jsonify
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
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            port=int(os.getenv("DB_PORT", 3306))
        )
        return conn
    except Exception as e:
        print("ERRO GRAVE AO CONECTAR NO MYSQL:", e)
        return None
# =========================
# LOGIN
# =========================
@app.route("/")
def login():
    session.pop('usuario', None)  # remove usuário da sessão
    return render_template("login.html")

@app.route("/autenticar", methods=["GET", "POST"])
def autenticar():

    # Se alguém tentar acessar via GET, volta para login
    if request.method == "GET":
        return redirect("/")

    usuario = request.form["usuario"]
    senha = request.form["senha"]

    conn = conectar()
    if not conn:
        return "Erro ao conectar no banco", 500

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

        # 🔎 Verifica se usuário já existe
        c.execute("SELECT id FROM usuarios WHERE usuario = %s", (usuario,))
        usuario_existente = c.fetchone()

        if usuario_existente:
            conn.close()
            flash("Usuário já cadastrado!", "danger")
            return redirect("/cadastro")

        # ✅ Se não existir, cadastra
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
@app.route("/produtos", methods=["GET", "POST"])
def produtos():
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor(dictionary=True)

    if request.method == "POST":
        descricao = request.form["descricao"]
        valor = float(request.form["valor"].replace(",", "."))
        estoque_inicial = int(request.form["estoque_inicial"])

        # estoque atual começa igual ao inicial
        estoque_atual = estoque_inicial

        c.execute("""
            INSERT INTO produtos 
            (descricao, valor, estoque_inicial, estoque_atual) 
            VALUES (%s, %s, %s, %s)
        """, (descricao, valor, estoque_inicial, estoque_atual))

        conn.commit()
        flash("Produto cadastrado com sucesso!", "success")

    c.execute("SELECT * FROM produtos ORDER BY descricao ASC")
    lista = c.fetchall()
    conn.close()

    return render_template("produtos.html", produtos=lista)

# =========================
# VENDAS (NOVO MODELO)
# =========================

@app.route("/vendas")
def vendas():
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor(dictionary=True)
    c.execute("SELECT * FROM produtos ORDER BY descricao ASC")
    produtos = c.fetchall()
    conn.close()

    return render_template("vendas.html", produtos=produtos)


@app.route("/salvar_venda", methods=["POST"])
def salvar_venda():
    if "usuario" not in session:
        return jsonify({"erro": "Não autorizado"}), 403

    dados = request.get_json()
    itens = dados.get("itens", [])

    if not itens:
        return jsonify({"erro": "Nenhum item na venda"}), 400

    conn = conectar()
    c = conn.cursor(dictionary=True)

    try:
        conn.start_transaction()

        # 🔢 GERAR NÚMERO DA VENDA ANTES DE USAR
        c.execute("SELECT IFNULL(MAX(numero_venda),0) + 1 AS prox FROM vendas")
        resultado = c.fetchone()
        numero_venda = resultado["prox"] if resultado else 1

        contagem = {}
        for item in itens:
            contagem[item["id"]] = contagem.get(item["id"], 0) + 1

        alertas = []
        venda_registro = []

        for produto_id, quantidade in contagem.items():

            c.execute("""
                UPDATE produtos
                SET estoque_atual = estoque_atual - %s
                WHERE id = %s
                AND estoque_atual >= %s
            """, (quantidade, produto_id, quantidade))

            if c.rowcount == 0:
                conn.rollback()
                return jsonify({
                    "erro": "Estoque insuficiente (venda simultânea detectada)"
                }), 400

            c.execute("""
                SELECT descricao, estoque_atual,
                       IFNULL(estoque_minimo,5) as estoque_minimo
                FROM produtos
                WHERE id = %s
            """, (produto_id,))
            produto = c.fetchone()

            venda_registro.append({
                "descricao": produto["descricao"],
                "quantidade": quantidade
            })

            if produto["estoque_atual"] <= produto["estoque_minimo"]:
                alertas.append(
                    f'{produto["descricao"]} com estoque baixo ({produto["estoque_atual"]})'
                )

        # 🧾 INSERIR ITENS DA VENDA
        for item in itens:
            c.execute("""
                INSERT INTO vendas
                (numero_venda, produto_id, quantidade, valor_total, data_venda)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                numero_venda,
                item["id"],
                1,
                item["valor"],
                datetime.now()
            ))

        conn.commit()

        return jsonify({
            "sucesso": True,
            "alertas": alertas,
            "registro": venda_registro,
            "numero_venda": numero_venda,
            "data_venda": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"erro": str(e)}), 500

    finally:
        conn.close()

# =========================
# EDITAR PRODUTOS
# =========================
@app.route("/editar_produto/<int:id>", methods=["GET", "POST"])
def editar_produto(id):
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor(dictionary=True)

    if request.method == "POST":
        descricao = request.form["descricao"]
        valor = float(request.form["valor"].replace(",", "."))
        estoque_inicial = int(request.form["estoque_inicial"])

        # ⚠ Atualiza também estoque_atual proporcionalmente
        c.execute("""
            UPDATE produtos
            SET descricao = %s,
                valor = %s,
                estoque_inicial = %s
            WHERE id = %s
        """, (descricao, valor, estoque_inicial, id))

        conn.commit()
        conn.close()

        flash("Produto atualizado com sucesso!", "success")
        return redirect("/produtos")

    c.execute("SELECT * FROM produtos WHERE id=%s", (id,))
    produto = c.fetchone()
    conn.close()

    return render_template("editar_produto.html", produto=produto)

# =========================
# RELATÓRIOS
# =========================
@app.route("/relatorios")
def relatorios():
    if "usuario" not in session:
        return redirect("/")

    conn = conectar()
    c = conn.cursor(dictionary=True)

    c.execute("SELECT * FROM produtos ORDER BY descricao ASC")
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
    c.execute("SELECT descricao, estoque_atual FROM produtos")
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
    c.execute("SELECT descricao, estoque_atual FROM produtos")
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

@app.route("/health")
def health():
    return "OK", 200

