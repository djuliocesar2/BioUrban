from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from models import db, Usuario, Fazenda, Hortalica, RegistroHidrico
from datetime import datetime
import csv
import io
import numpy as np
from sklearn.linear_model import LinearRegression
import threading
import time
import random
import json
import requests
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env[cite: 4]
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///biourban_pro.db'
app.config['SECRET_KEY'] = 'chave-segura-biourban-2026'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
# INICIALIZAÇÃO DO FLASK-MIGRATE
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# ==============================================================================
# VARIÁVEIS GLOBAIS DE CLIMA E CONTROLE
# ==============================================================================
# Carrega a chave de forma segura a partir do .env[cite: 4]
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

CLIMA_ATUAL = {
    "prob_chuva": 0.0,
    "volume_chuva": 0.0,
    "temperatura": 25.0
}

ID_FAZENDA_PADRAO = 1
sensor_fisico_ativo = False
PLANTA_FOCO_ID = None
FAZENDA_ATUAL_ID = ID_FAZENDA_PADRAO

# ==============================================================================
# THREAD DE ATUALIZAÇÃO CLIMÁTICA (SÃO PAULO) - COM BUSCA IMEDIATA
# ==============================================================================
def atualizar_clima_periodicamente():
    """Busca a previsão do tempo imediatamente ao iniciar e depois a cada 24 horas."""
    global CLIMA_ATUAL
    
    def buscar_dados_clima():
        with app.app_context():
            fazenda = db.session.get(Fazenda, ID_FAZENDA_PADRAO)
            lat = fazenda.latitude if fazenda and fazenda.latitude else -23.5505
            lon = fazenda.longitude if fazenda and fazenda.longitude else -46.6333
            
        try:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
            resposta = requests.get(url)
            
            if resposta.status_code == 200:
                dados = resposta.json()
                previsao = dados['list'][0]
                
                CLIMA_ATUAL['prob_chuva'] = previsao.get('pop', 0) * 100
                CLIMA_ATUAL['volume_chuva'] = previsao.get('rain', {}).get('3h', 0)
                CLIMA_ATUAL['temperatura'] = previsao.get('main', {}).get('temp', 25.0)
                
                print(f"[CLIMA - São Paulo] Atualizado com sucesso -> Temp: {CLIMA_ATUAL['temperatura']}°C | Chuva: {CLIMA_ATUAL['prob_chuva']}%")
            else:
                print(f"[CLIMA] Aguardando ativação da chave API (Erro {resposta.status_code})")
                
        except Exception as e:
            print(f"[CLIMA] Falha na conexão com OpenWeather: {e}")

    # Executa a primeira busca imediatamente na inicialização
    buscar_dados_clima()
    
    # Mantém o loop diário (86400 segundos = 24 horas)
    while True:
        time.sleep(86400)
        buscar_dados_clima()

# Iniciar a thread do clima automaticamente ao arrancar o servidor
thread_clima = threading.Thread(target=atualizar_clima_periodicamente, daemon=True)
thread_clima.start()

# ==============================================================================
# FUNÇÃO DE INTELIGÊNCIA ARTIFICIAL (REGRESSÃO LINEAR MÚLTIPLA)
# ==============================================================================
def gerar_relatorio_ia(historico_registros, prob_chuva_futura=0.0, vol_chuva_futuro=0.0, temperatura_atual=25.0):
    """
    Analisa a curva de umidade usando Regressão Linear Múltipla (Tempo, Prob. Chuva, Volume Chuva, Temperatura)
    para prever o estresse hídrico considerando a previsão do tempo real.
    """
    relatorio = {
        "diagnostico_ia": "Aguardando volume de dados para previsão...",
        "acao_recomendada": "Coletando histórico multivariável."
    }

    if not historico_registros or len(historico_registros) < 5:
        return relatorio

    umidade_atual = historico_registros[-1].nivel_porcentagem
    
    # Matriz X: [Ciclo (Tempo), Probabilidade de Chuva, Volume de Chuva, Temperatura]
    X = np.array([
        [i, getattr(r, 'prob_chuva', 0), getattr(r, 'volume_chuva', 0), temperatura_atual] 
        for i, r in enumerate(historico_registros)
    ])
    Y = np.array([r.nivel_porcentagem for r in historico_registros])

    modelo = LinearRegression()
    modelo.fit(X, Y)
    
    taxa_variacao_tempo = modelo.coef_[0]

    if umidade_atual < 30:
        if prob_chuva_futura > 70 and vol_chuva_futuro > 5.0:
            relatorio["diagnostico_ia"] = f"Umidade baixa ({umidade_atual:.1f}%), mas há forte previsão de chuva ({vol_chuva_futuro}mm)."
            relatorio["acao_recomendada"] = "Irrigação suspensa pela IA. Aguardar precipitação natural."
        else:
            relatorio["diagnostico_ia"] = f"Umidade crítica ({umidade_atual:.1f}%). Sem chuva prevista."
            relatorio["acao_recomendada"] = "Irrigação de emergência necessária."
            
    elif taxa_variacao_tempo < -0.5:
        proximo_ciclo = len(historico_registros)
        previsao_futura = modelo.predict([[proximo_ciclo, prob_chuva_futura, vol_chuva_futuro, temperatura_atual]])[0]
        
        if previsao_futura > 30:
            relatorio["diagnostico_ia"] = f"O solo secaria, mas a previsão de chuva ({prob_chuva_futura}%) estabilizará a umidade."
            relatorio["acao_recomendada"] = "Intervenção cancelada pelo clima."
        else:
            passos_restantes = (30 - umidade_atual) / taxa_variacao_tempo
            ciclos_estimados = abs(round(passos_restantes))
            relatorio["diagnostico_ia"] = f"Queda abrupta sem apoio climático. Risco de estresse em ~{ciclos_estimados} ciclos."
            relatorio["acao_recomendada"] = "Preparar sistema de irrigação preditiva."
            
    else:
        relatorio["diagnostico_ia"] = "A curva preditiva mostra que a retenção hídrica está estável e alinhada com o ciclo da planta."
        relatorio["acao_recomendada"] = "Nenhuma intervenção necessária."

    return relatorio

# --- CONTROLE GLOBAL DO SIMULADOR IOT EM SEGUNDO PLANO ---
simulador_ativo = False
simulador_thread = None
ADC_NO_AR = 3180
ADC_NA_AGUA = 1150

def rodar_simulacao(fazenda_id):
    global simulador_ativo, PLANTA_FOCO_ID, CLIMA_ATUAL
    while simulador_ativo:
        adc_simulado = random.randint(1400, 2945)
        pct = (ADC_NO_AR - adc_simulado) / (ADC_NO_AR - ADC_NA_AGUA) * 100.0
        porcentagem = round(max(0.0, min(100.0, pct)), 1)

        with app.app_context():
            novo = RegistroHidrico(
                nivel_porcentagem=porcentagem,
                data_leitura=datetime.now().strftime('%H:%M:%S'),
                origem="simulador",
                fazenda_id=fazenda_id,
                hortalica_id=PLANTA_FOCO_ID,
                prob_chuva=CLIMA_ATUAL['prob_chuva'],
                volume_chuva=CLIMA_ATUAL['volume_chuva']
            )
            db.session.add(novo)
            
            if PLANTA_FOCO_ID:
                planta = db.session.get(Hortalica, PLANTA_FOCO_ID)
                if planta:
                    planta.umidade_atual = porcentagem
                    
            db.session.commit()
        time.sleep(2)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

@app.template_filter('dias_cultivo')
def dias_cultivo_filter(data_plantio_str):
    try:
        if not data_plantio_str: return 0
        data_plantio = datetime.strptime(data_plantio_str, '%Y-%m-%d').date()
        return (datetime.now().date() - data_plantio).days
    except: return 0

# --- ROTAS DE AUTENTICAÇÃO ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.query.filter_by(username=request.form.get('username')).first()
        if user and user.password == request.form.get('password'):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Login inválido. Verifique suas credenciais.')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        if not Usuario.query.filter_by(username=username).first():
            novo = Usuario(username=username, password=request.form.get('password'))
            db.session.add(novo); db.session.commit()
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- DASHBOARD (LISTA DE UNIDADES) ---
@app.route('/', endpoint='dashboard')
@login_required
def dashboard():
    minhas_fazendas = Fazenda.query.filter_by(usuario_id=current_user.id).all()
    return render_template('dashboard.html', fazendas=minhas_fazendas)

@app.route('/add_fazenda', methods=['POST'])
@login_required
def add_fazenda():
    nome = request.form.get('nome')
    local = request.form.get('localizacao')
    if nome:
        nova = Fazenda(nome=nome, localizacao=local, usuario_id=current_user.id)
        db.session.add(nova); db.session.commit()
    return redirect(url_for('dashboard'))

# --- PÁGINA DA UNIDADE (GESTÃO + DUAL IA) ---
@app.route('/fazenda/<int:id>')
@login_required
def ver_fazenda(id):
    fazenda = db.session.get(Fazenda, id)
    if not fazenda or fazenda.usuario_id != current_user.id: return "Acesso Negado", 403
    
    global PLANTA_FOCO_ID, FAZENDA_ATUAL_ID
    FAZENDA_ATUAL_ID = id
    filtro = request.args.get('filtro', 'Todos')
    hoje = datetime.now().date()
    contagem_variedades = {}
    total_ciclos, qtd_ativas = 0, 0
    previsoes_ia = {}

    stats = {
        'total_ativas': 0,
        'tempo_medio': 0,
        'total_h2o': 0,
        'media_h2o': 0,
        'filtro_atual': filtro,
        'previsoes': {},
        'insight_h2o': None
    }

    if PLANTA_FOCO_ID is None and len(fazenda.hortalicas) > 0:
        PLANTA_FOCO_ID = fazenda.hortalicas[0].id

    for h in fazenda.hortalicas:
        if h.status != 'Colhido':
            if h.ciclo_estimado:
                total_ciclos += h.ciclo_estimado
                qtd_ativas += 1
            contagem_variedades[h.nome] = contagem_variedades.get(h.nome, 0) + 1
            try:
                d_p = datetime.strptime(h.data_plantio, '%Y-%m-%d').date()
                passados = (hoje - d_p).days
                h.atrasada = passados > (h.ciclo_estimado or 0)
                h.dias_restantes = max(0, (h.ciclo_estimado or 0) - passados)
            except:
                h.atrasada = False; h.dias_restantes = 0

    historico = Hortalica.query.filter_by(fazenda_id=id, status='Colhido').all()
    if len(historico) >= 2:
        tipos_ativos = set([h.nome for h in fazenda.hortalicas if h.status != 'Colhido'])
        for tipo in tipos_ativos:
            dados_tipo = [h for h in historico if h.nome == tipo and h.data_plantio and h.data_colheita]
            if len(dados_tipo) >= 2:
                try:
                    X = np.array(range(len(dados_tipo))).reshape(-1, 1)
                    Y = []
                    for h in dados_tipo:
                        d_p = datetime.strptime(h.data_plantio, '%Y-%m-%d').date()
                        d_c = datetime.strptime(h.data_colheita, '%Y-%m-%d').date()
                        Y.append((d_c - d_p).days)
                    model = LinearRegression().fit(X, Y)
                    pred = model.predict([[len(dados_tipo)]])
                    previsoes_ia[tipo] = round(float(pred[0]), 1)
                except: continue

    if PLANTA_FOCO_ID:
        reg_simulador = RegistroHidrico.query.filter_by(fazenda_id=id, origem="simulador", hortalica_id=PLANTA_FOCO_ID).order_by(RegistroHidrico.id.desc()).limit(15).all()
        reg_sensor = RegistroHidrico.query.filter_by(fazenda_id=id, origem="sensor", hortalica_id=PLANTA_FOCO_ID).order_by(RegistroHidrico.id.desc()).limit(15).all()
        todos_recentes = RegistroHidrico.query.filter_by(fazenda_id=id, hortalica_id=PLANTA_FOCO_ID).order_by(RegistroHidrico.id.desc()).limit(15).all()
    else:
        reg_simulador = []
        reg_sensor = []
        todos_recentes = []

    reg_simulador.reverse()
    labels_simulador = [r.data_leitura for r in reg_simulador]
    dados_simulador = [r.nivel_porcentagem for r in reg_simulador]

    reg_sensor.reverse()
    labels_sensor = [r.data_leitura for r in reg_sensor]
    dados_sensor = [r.nivel_porcentagem for r in reg_sensor]

    if todos_recentes:
        stats['media_h2o'] = round(sum(r.nivel_porcentagem for r in todos_recentes) / len(todos_recentes), 1)
        media_val = stats['media_h2o']
        
        categoria_foco = "hortalica"
        nome_foco_str = "Planta Monitorada"
        if PLANTA_FOCO_ID:
            p_foco = db.session.get(Hortalica, PLANTA_FOCO_ID)
            if p_foco:
                categoria_foco = p_foco.categoria_hidrica or "hortalica"
                nome_foco_str = p_foco.nome
        
        if categoria_foco == 'arida':
            if media_val < 5:
                stats['insight_h2o'] = {"tipo": "perigo", "msg": f"{nome_foco_str} (Árida): Nível muito baixo ({media_val}%). Considere uma rega ligeira."}
            elif media_val > 40:
                stats['insight_h2o'] = {"tipo": "alerta", "msg": f"{nome_foco_str} (Árida): Nível elevado ({media_val}%). Risco de apodrecimento das raízes, reduza a rega."}
            else:
                stats['insight_h2o'] = {"tipo": "sucesso", "msg": f"{nome_foco_str} (Árida): Nível hídrico perfeito ({media_val}%). Condições ideais para suculentas/cactos."}
                
        elif categoria_foco == 'tropical':
            if media_val < 50:
                stats['insight_h2o'] = {"tipo": "perigo", "msg": f"{nome_foco_str} (Tropical): Nível baixo ({media_val}%). Aumente a irrigação urgentemente."}
            elif media_val > 90:
                stats['insight_h2o'] = {"tipo": "alerta", "msg": f"{nome_foco_str} (Tropical): Nível muito alto ({media_val}%). Solo demasiado encharcado."}
            else:
                stats['insight_h2o'] = {"tipo": "sucesso", "msg": f"{nome_foco_str} (Tropical): Nível hídrico ideal ({media_val}%). Mantenha o fluxo."}
                
        else:
            if media_val < 30.0:
                stats['insight_h2o'] = {"tipo": "perigo", "msg": f"{nome_foco_str}: Nível baixo ({media_val}%). Aumente a irrigação para evitar o estresse hídrico."}
            elif media_val > 70.0:
                stats['insight_h2o'] = {"tipo": "alerta", "msg": f"{nome_foco_str}: Nível elevado ({media_val}%). Reduza a irrigação para evitar saturação."}
            else:
                stats['insight_h2o'] = {"tipo": "sucesso", "msg": f"{nome_foco_str}: Nível hídrico ideal ({media_val}%). Mantenha o ciclo atual."}

    stats['total_ativas'] = qtd_ativas
    stats['tempo_medio'] = round(total_ciclos / qtd_ativas, 1) if qtd_ativas > 0 else 0
    stats['previsoes'] = previsoes_ia

    if filtro == 'Crescendo': hortalicas_exibidas = [h for h in fazenda.hortalicas if h.status != 'Colhido']
    elif filtro == 'Colhido': hortalicas_exibidas = [h for h in fazenda.hortalicas if h.status == 'Colhido']
    else: hortalicas_exibidas = fazenda.hortalicas

    return render_template('index.html', fazenda=fazenda, hortalicas=hortalicas_exibidas, 
                           stats=stats, chart_data=contagem_variedades, 
                           labels_simulador=labels_simulador, dados_simulador=dados_simulador,
                           labels_sensor=labels_sensor, dados_sensor=dados_sensor, hoje=hoje,
                           planta_foco_id=PLANTA_FOCO_ID)

# --- OPERAÇÕES DE CRUD E API ---
@app.route('/add_hortalica/<int:fazenda_id>', methods=['POST'])
@login_required
def add_hortalica(fazenda_id):
    nome = request.form.get('nome')
    data = request.form.get('data_plantio')
    ciclo = request.form.get('ciclo_estimado')
    categoria = request.form.get('categoria_hidrica', 'hortalica')
    
    if nome and data:
        nova_hortalica = Hortalica(
            nome=nome, 
            data_plantio=data, 
            ciclo_estimado=int(ciclo or 0), 
            fazenda_id=fazenda_id,
            categoria_hidrica=categoria
        )
        db.session.add(nova_hortalica)
        db.session.commit()
    return redirect(url_for('ver_fazenda', id=fazenda_id))

@app.route('/editar_hortalica/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_hortalica(id):
    h = db.session.get(Hortalica, id)
    if not h or h.fazenda.usuario_id != current_user.id:
        return "Acesso Negado", 403
        
    if request.method == 'POST':
        h.nome = request.form.get('nome')
        h.data_plantio = request.form.get('data_plantio')
        ciclo = request.form.get('ciclo_estimado')
        h.ciclo_estimado = int(ciclo) if ciclo else 0
        h.categoria_hidrica = request.form.get('categoria_hidrica', 'hortalica')
        db.session.commit()
        return redirect(url_for('ver_fazenda', id=h.fazenda_id))
        
    return render_template('editar_hortalica.html', hortalica=h)

@app.route('/colher/<int:id>/<int:fazenda_id>', methods=['POST'])
@login_required
def colher(id, fazenda_id):
    h = db.session.get(Hortalica, id)
    if h:
        data_f = request.form.get('data_colheita')
        h.data_colheita = data_f if data_f else datetime.now().strftime('%Y-%m-%d')
        h.status = "Colhido"
        db.session.commit()
    return redirect(url_for('ver_fazenda', id=fazenda_id))

@app.route('/deletar/<int:id>/<int:fazenda_id>')
@login_required
def deletar(id, fazenda_id):
    h = db.session.get(Hortalica, id)
    if h:
        db.session.delete(h); db.session.commit()
    return redirect(url_for('ver_fazenda', id=fazenda_id))

@app.route('/exportar_csv/<int:fazenda_id>')
@login_required
def exportar_csv(fazenda_id):
    fazenda = db.session.get(Fazenda, fazenda_id)
    if not fazenda: return "Not Found", 404
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Hortalica', 'Data Plantio', 'Data Colheita', 'Status', 'Ciclo Estimado', 'Categoria Hidrica'])
    for h in fazenda.hortalicas:
        cw.writerow([h.nome, h.data_plantio, h.data_colheita, h.status, h.ciclo_estimado, h.categoria_hidrica])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=relatorio_{fazenda.nome}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/api/focar_planta/<int:hortalica_id>', methods=['POST'])
@login_required
def focar_planta(hortalica_id):
    global PLANTA_FOCO_ID
    planta = db.session.get(Hortalica, hortalica_id)
    if not planta:
        return jsonify({"erro": "Planta não encontrada"}), 404

    if PLANTA_FOCO_ID == hortalica_id:
        PLANTA_FOCO_ID = None
        return jsonify({"status": "desativado", "nome": planta.nome, "id": hortalica_id})

    PLANTA_FOCO_ID = hortalica_id
    return jsonify({"status": "sucesso", "nome": planta.nome, "id": hortalica_id})

# ==============================================================================
# ROTA PARA RECEBER DADOS DO ESP32 VIA WI-FI (HTTP POST)
# ==============================================================================
@app.route('/api/receber_dados', methods=['POST'])
def receber_dados():
    global sensor_fisico_ativo, PLANTA_FOCO_ID, FAZENDA_ATUAL_ID, CLIMA_ATUAL
    
    if not sensor_fisico_ativo:
        return jsonify({"mensagem": "Leitura pausada no painel"}), 200
        
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"erro": "Nenhum JSON recebido"}), 400
            
        umidade = dados.get('umidade')
        status = dados.get('status')
        valor_bruto = dados.get('valor_bruto')
        
        if umidade is not None:
            umidade_val = max(0.0, min(100.0, float(umidade)))
            
            novo_registro = RegistroHidrico(
                nivel_porcentagem=umidade_val,
                data_leitura=datetime.now().strftime('%H:%M:%S'),
                origem="sensor",
                fazenda_id=FAZENDA_ATUAL_ID,
                hortalica_id=PLANTA_FOCO_ID,
                prob_chuva=CLIMA_ATUAL['prob_chuva'],
                volume_chuva=CLIMA_ATUAL['volume_chuva']
            )
            db.session.add(novo_registro)
            
            nome_planta = "Nenhuma selecionada"
            if PLANTA_FOCO_ID:
                planta = db.session.get(Hortalica, PLANTA_FOCO_ID)
                if planta:
                    planta.umidade_atual = umidade_val
                    nome_planta = planta.nome
                    
            db.session.commit()
            print(f"[WI-FI] 🌱 {nome_planta} (Bruto: {valor_bruto}): Umidade = {umidade_val}% | Status: {status}")
            
        return jsonify({"mensagem": "Dados processados com sucesso"}), 200
    except Exception as e:
        print(f"[ERRO WI-FI] {e}")
        return jsonify({"erro": str(e)}), 500

@app.route('/api/sensor_fisico/toggle', methods=['POST'])
@login_required
def toggle_sensor_fisico():
    global sensor_fisico_ativo
    if sensor_fisico_ativo:
        sensor_fisico_ativo = False
        return jsonify({"status": "desativado", "mensagem": "Recebimento de dados do vaso pausado."})
    else:
        sensor_fisico_ativo = True
        return jsonify({"status": "ativo", "mensagem": "Recebimento de dados do vaso ativado."})

@app.route('/api/sensor_fisico/status', methods=['GET'])
@login_required
def status_sensor_fisico():
    return jsonify({"ativo": sensor_fisico_ativo})

# --- ROTA PARA O SIMULADOR EXTERNO (SIMULADOR_IOT.PY) ---
@app.route('/api/sensor_hidrico', methods=['POST'])
def receber_sensor_hidrico():
    global CLIMA_ATUAL
    dados = request.json
    if not dados:
        return jsonify({"erro": "Dados inválidos"}), 400
    
    umidade = dados.get('umidade')
    fazenda_id = dados.get('fazenda_id', FAZENDA_ATUAL_ID)
    
    if umidade is not None:
        global PLANTA_FOCO_ID
        novo_registro = RegistroHidrico(
            nivel_porcentagem=float(umidade),
            data_leitura=datetime.now().strftime('%H:%M:%S'),
            origem="simulador",
            fazenda_id=int(fazenda_id),
            hortalica_id=PLANTA_FOCO_ID,
            prob_chuva=CLIMA_ATUAL['prob_chuva'],
            volume_chuva=CLIMA_ATUAL['volume_chuva']
        )
        db.session.add(novo_registro)
        
        if PLANTA_FOCO_ID:
            planta = db.session.get(Hortalica, PLANTA_FOCO_ID)
            if planta:
                planta.umidade_atual = float(umidade)
                
        db.session.commit()
        return jsonify({"mensagem": "Registado com sucesso"}), 201
        
    return jsonify({"erro": "Umidade não informada"}), 400

# --- ENDPOINTS DE ATUALIZAÇÃO DINÂMICA (AJAX) ---
@app.route('/api/dados_grafico/<int:fazenda_id>', methods=['GET'])
@login_required
def dados_grafico(fazenda_id):
    global PLANTA_FOCO_ID, CLIMA_ATUAL

    if PLANTA_FOCO_ID:
        reg_sensor = RegistroHidrico.query.filter_by(
            fazenda_id=fazenda_id,
            origem="sensor",
            hortalica_id=PLANTA_FOCO_ID
        ).order_by(RegistroHidrico.id.desc()).limit(15).all()
    else:
        reg_sensor = RegistroHidrico.query.filter_by(
            fazenda_id=fazenda_id,
            origem="sensor"
        ).order_by(RegistroHidrico.id.desc()).limit(15).all()

    reg_sensor.reverse()
    labels_sensor = [r.data_leitura for r in reg_sensor]
    dados_sensor = [r.nivel_porcentagem for r in reg_sensor]

    if PLANTA_FOCO_ID:
        reg_simulador = RegistroHidrico.query.filter_by(
            fazenda_id=fazenda_id,
            origem="simulador",
            hortalica_id=PLANTA_FOCO_ID
        ).order_by(RegistroHidrico.id.desc()).limit(15).all()
    else:
        reg_simulador = RegistroHidrico.query.filter_by(
            fazenda_id=fazenda_id,
            origem="simulador"
        ).order_by(RegistroHidrico.id.desc()).limit(15).all()

    reg_simulador.reverse()
    labels_simulador = [r.data_leitura for r in reg_simulador]
    dados_simulador = [r.nivel_porcentagem for r in reg_simulador]

    fazenda = db.session.get(Fazenda, fazenda_id)
    umidades_plantas = {}

    if fazenda:
        for h in fazenda.hortalicas:
            umidades_plantas[h.id] = h.umidade_atual or 0.0

    prob_chuva_agora = CLIMA_ATUAL['prob_chuva']
    vol_chuva_agora = CLIMA_ATUAL['volume_chuva']
    temp_atual = CLIMA_ATUAL['temperatura']

    # Geração de IA independente para cada card no dashboard
    analise_ia_simulador = gerar_relatorio_ia(reg_simulador, prob_chuva_agora, vol_chuva_agora, temp_atual)
    analise_ia_sensor = gerar_relatorio_ia(reg_sensor, prob_chuva_agora, vol_chuva_agora, temp_atual)

    return jsonify({
        "labels_sensor": labels_sensor,
        "dados_sensor": dados_sensor,
        "labels_simulador": labels_simulador,
        "dados_simulador": dados_simulador,
        "umidades_plantas": umidades_plantas,
        "inteligencia_artificial_simulador": analise_ia_simulador,
        "inteligencia_artificial_sensor": analise_ia_sensor,
        "clima": CLIMA_ATUAL  # Envia a temperatura e chance de chuva atuais para o front-end
    })

# --- ENDPOINTS DO SIMULADOR INTEGRADO ---
@app.route('/api/simulador/toggle/<int:fazenda_id>', methods=['POST'])
@login_required
def toggle_simulador(fazenda_id):
    global simulador_ativo, simulador_thread
    if simulador_ativo:
        simulador_ativo = False
        return jsonify({"status": "desativado", "mensagem": "Simulador pausado com sucesso."})
    else:
        simulador_ativo = True
        simulador_thread = threading.Thread(target=rodar_simulacao, args=(fazenda_id,), daemon=True)
        simulador_thread.start()
        return jsonify({"status": "ativo", "mensagem": "Simulador iniciado em segundo plano."})

@app.route('/api/simulador/status', methods=['GET'])
@login_required
def status_simulador():
    return jsonify({"ativo": simulador_ativo})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True, use_reloader=False)