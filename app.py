
from flask import Flask, render_template, request, redirect, session, send_file, flash, jsonify
import psycopg2
import psycopg2.extras
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from reportlab.platypus import SimpleDocTemplate, Table
from reportlab.lib.pagesizes import A4
from openpyxl import Workbook
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "quermesse_secret"

# =========================
# CONEXÃO POSTGRES
# =========================
def conectar():
    try:
        conn = psycopg2.connect(
            os.getenv("DATABASE_URL"),
            sslmode="require"
        )
        return conn
    except Exception as e:
        print("ERRO GRAVE AO CONECTAR NO POSTGRES:", e)
        return None

def agora_amazonas():
    return datetime.now(ZoneInfo("America/Manaus"))
    
# =========================
# LOGIN
# =========================
@app.route("/")
def login():
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

    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM usuarios WHERE usuario=%s", (usuario,))
    user = c.fetchone()
    conn.close()

    if user and check_password_hash(user["senha"], senha):
        session["usuario"] = user["usuario"]
        session["perfil"] = user.get("perfil", "usuario")
        return redirect("/dashboard")

    flash("Usuário ou senha inválidos", "danger")
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
    
# =========================
# CADASTRO USUÁRIO
# =========================
@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if not session.get("usuario"):
        return redirect("/")

    conn = conectar()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if request.method == "POST":
        usuario = request.form["usuario"]
        senha = generate_password_hash(request.form["senha"])
        perfil = request.form["perfil"]

        # Verifica se já existe
        c.execute("SELECT id FROM usuarios WHERE usuario = %s", (usuario,))
        if c.fetchone():
            conn.close()
            flash("Usuário já cadastrado!", "danger")
            return redirect("/cadastro")

        c.execute(
            "INSERT INTO usuarios (usuario, senha, perfil) VALUES (%s, %s, %s)",
            (usuario, senha, perfil)
        )
        conn.commit()
        flash("Usuário cadastrado com sucesso!", "success")
        conn.close()
        return redirect("/cadastro")

    # 🔹 IMPORTANTE: SEMPRE EXECUTA NO GET
    c.execute("SELECT id, usuario, perfil FROM usuarios ORDER BY usuario ASC")
    usuarios = c.fetchall()
    conn.close()

    return render_template("cadastro.html", usuarios=usuarios)
   
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

    if session.get("perfil") != "administrador":
        return redirect("/dashboard")

    conn = conectar()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

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
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        
        # 🔢 GERAR NÚMERO DA VENDA ANTES DE USAR
        c.execute("SELECT COALESCE(MAX(numero_venda),0) + 1 AS prox FROM vendas")
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
                       COALESCE(estoque_minimo,5) as estoque_minimo
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
                agora_amazonas()
            ))

        conn.commit()

        return jsonify({
            "sucesso": True,
            "alertas": alertas,
            "registro": venda_registro,
            "numero_venda": numero_venda,
            "data_venda": agora_amazonas().strftime("%d/%m/%Y %H:%M:%S")
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"erro": str(e)}), 500

    finally:
        conn.close()

@app.route("/cancelar_venda", methods=["POST"])
def cancelar_venda():

    if "usuario" not in session:
        return jsonify({"erro": "Não autorizado"}), 403

    dados = request.get_json()
    numero_venda = dados.get("numero_venda")

    if not numero_venda:
        return jsonify({"erro": "Número da venda não informado"}), 400

    conn = conectar()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        
        # 🔎 Buscar itens da venda
        c.execute("""
            SELECT produto_id, quantidade
            FROM vendas
            WHERE numero_venda = %s
        """, (numero_venda,))

        itens = c.fetchall()

        if not itens:
            conn.rollback()
            return jsonify({"erro": "Venda não encontrada"}), 404

        # 🔥 Restaurar estoque
        for item in itens:
            c.execute("""
                UPDATE produtos
                SET estoque_atual = estoque_atual + %s
                WHERE id = %s
            """, (item["quantidade"], item["produto_id"]))

        # ❌ Excluir venda
        c.execute("""
            DELETE FROM vendas
            WHERE numero_venda = %s
        """, (numero_venda,))

        conn.commit()

        return jsonify({"sucesso": True})

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
    if session.get("perfil") != "administrador":
        return redirect("/dashboard")

    conn = conectar()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if request.method == "POST":
        descricao = request.form["descricao"]
        valor = float(request.form["valor"].replace(",", "."))
        estoque_inicial = int(request.form["estoque_inicial"])

        # 👇 AQUI ESTÁ O AJUSTE
        estoque_atual = estoque_inicial

        c.execute("""
            UPDATE produtos
            SET descricao = %s,
                valor = %s,
                estoque_inicial = %s,
                estoque_atual = %s
            WHERE id = %s
        """, (descricao, valor, estoque_inicial, estoque_atual, id))

        conn.commit()
        conn.close()

        flash("Produto atualizado com sucesso!", "success")
        return redirect("/produtos")

    c.execute("SELECT * FROM produtos WHERE id=%s", (id,))
    produto = c.fetchone()
    conn.close()

    return render_template("editar_produto.html", produto=produto)

# =========================
# ZERAR ESTOQUE
# =========================
@app.route("/zerar_estoque/<int:id>", methods=["POST"])
def zerar_estoque(id):
    if session.get("perfil") != "administrador":
        return redirect("/dashboard")

    conn = conectar()
    c = conn.cursor()

    # Zera apenas o estoque atual
    c.execute("""
        UPDATE produtos
        SET estoque_atual = 0
        WHERE id = %s
    """, (id,))

    conn.commit()
    conn.close()

    flash("Estoque zerado com sucesso!", "warning")
    return redirect("/produtos")

# =========================
# RELATÓRIOS
# =========================
@app.route("/relatorios")
def relatorios():
    if "usuario" not in session:
        return redirect("/")

    if session.get("perfil") != "administrador":
        return redirect("/dashboard")

    conn = conectar()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

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
# EDITAR USUÁRIO
# =========================    
@app.route("/editar_usuario/<int:id>", methods=["GET","POST"])
def editar_usuario(id):
    if not session.get("usuario"):
        return redirect("/")

    conn = conectar()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Busca usuário
    c.execute("SELECT id, usuario, perfil FROM usuarios WHERE id = %s", (id,))
    usuario = c.fetchone()

    if not usuario:
        conn.close()
        flash("Usuário não encontrado.", "danger")
        return redirect("/cadastro")

    if request.method == "POST":
        novo_usuario = request.form["usuario"]
        novo_perfil = request.form["perfil"]
        nova_senha = request.form["senha"]
    
        if nova_senha:
            senha_hash = generate_password_hash(nova_senha)
            c.execute(
                "UPDATE usuarios SET usuario = %s, perfil = %s, senha = %s WHERE id = %s",
                (novo_usuario, novo_perfil, senha_hash, id)
            )
        else:
            c.execute(
                "UPDATE usuarios SET usuario = %s, perfil = %s WHERE id = %s",
                (novo_usuario, novo_perfil, id)
            )
    
        conn.commit()
        conn.close()
    
        flash("Usuário atualizado com sucesso!", "success")
        return redirect("/cadastro")

    conn.close()
    return render_template("editar_usuario.html", usuario=usuario)

# =========================
# EXCLUIR USUÁRIO
# =========================
@app.route("/excluir_usuario/<int:id>", methods=["POST"])
def excluir_usuario(id):
    if not session.get("usuario"):
        return redirect("/")

    conn = conectar()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Busca usuário a excluir
    c.execute("SELECT usuario FROM usuarios WHERE id = %s", (id,))
    usuario_excluir = c.fetchone()

    if not usuario_excluir:
        conn.close()
        flash("Usuário não encontrado.", "danger")
        return redirect("/cadastro")

    # 🔒 NÃO permite excluir o próprio usuário logado
    if usuario_excluir["usuario"] == session["usuario"]:
        conn.close()
        flash("Você não pode excluir o próprio usuário!", "danger")
        return redirect("/cadastro")

    # Exclui
    c.execute("DELETE FROM usuarios WHERE id = %s", (id,))
    conn.commit()
    conn.close()

    flash("Usuário excluído com sucesso!", "success")
    return redirect("/cadastro")

# =========================
# PDF
# =========================
@app.route("/relatorio_pdf")
def relatorio_pdf():
    if session.get("perfil") != "administrador":
        return redirect("/dashboard")
        
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
    if session.get("perfil") != "administrador":
        return redirect("/dashboard")
    
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

