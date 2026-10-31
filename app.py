import os
import json
import csv
import io
import threading
import time
import random
import requests
import xml.etree.ElementTree as ET
import unicodedata
from groq import Groq
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_migrate import Migrate
from dotenv import load_dotenv

# 1. Carrega as variáveis do .env PRIMEIRO
load_dotenv()

from groq import Groq
from models import db, Usuario, Fazenda, Hortalica, RegistroHidrico

# 2. Inicializa o cliente da Groq
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def remover_acentos(texto):
    """Remove acentos, cedilhas e caracteres especiais de uma string."""
    if not texto:
        return ""
    texto_nfkd = unicodedata.normalize('NFD', texto)
    return ''.join(c for c in texto_nfkd if unicodedata.category(c) != 'Mn').lower().strip()

def obter_limites_umidade_ia(nome_hortalica):
    """
    Consulta a API da Groq descobrindo dinamicamente os modelos ativos na conta.
    Evita erros de modelos descontinuados ou indisponíveis (400/404).
    """
    prompt_system = (
        "Você é um agrônomo. Responda EXCLUSIVAMENTE um objeto JSON válido "
        "no formato: {\"umidade_min\": valor_int, \"umidade_max\": valor_int} sem nenhum texto adicional."
    )
    prompt_user = f"Faixa ideal de umidade do solo (%) para a planta: '{nome_hortalica.strip()}'"

    # 1. Obtém dinamicamente os modelos de texto gerais (exclui guardrails e modelos de áudio)
    try:
        models_list = groq_client.models.list()
        modelos_ativos = [
            m.id for m in models_list.data 
            if not any(x in m.id.lower() for x in ["whisper", "safetensors", "vision", "guard", "orpheus"])
        ]
        print(f"-> [Groq API] Modelos de chat ativos detectados: {modelos_ativos}")
    except Exception as e:
        print(f"-> [Groq API ERRO] Falha ao listar modelos: {e}")
        modelos_ativos = ["allam-2-7b", "openai/gpt-oss-20b"]

    # 2. Testa os modelos disponíveis na ordem até obter a resposta JSON
    for modelo in modelos_ativos:
        try:
            print(f"-> [Groq API] Consultando modelo '{modelo}' para '{nome_hortalica}'...")
            response = groq_client.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": prompt_user}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=4.0
            )

            dados = json.loads(response.choices[0].message.content)
            min_val = float(dados.get("umidade_min", 40))
            max_val = float(dados.get("umidade_max", 70))
            print(f"-> [Groq API] Sucesso com '{modelo}'! Faixa obtida: {min_val}% a {max_val}%")
            return min_val, max_val

        except Exception as e:
            print(f"-> [Groq API] Modelo '{modelo}' falhou: {e}")

    print("-> [Groq API ERRO] Nenhum modelo respondeu. Usando faixa de segurança (40% - 70%).")
    return 40.0, 70.0

# 3. Configuração da Aplicação Flask
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///biourban_pro.db'
app.config['SECRET_KEY'] = 'chave-segura-biourban-2026'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# INICIALIZAÇÃO DO FLASK-MIGRATE E LOGIN
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# ==============================================================================
# VARIÁVEIS GLOBAIS DE CLIMA E CONTROLE
# ==============================================================================
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
# FUNÇÃO DE CONSULTA CLIMÁTICA EM TEMPO REAL (SÃO PAULO)
# ==============================================================================
def obter_dados_clima_cptec(lat=-23.5505, lon=-46.6333):
    """
    Busca o clima em tempo real para São Paulo via Open-Meteo / CPTEC.
    Lat/Lon: -23.5505, -46.6333 (São Paulo - SP)
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    # 1. Tenta Open-Meteo (API aberta em tempo real)
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,precipitation,rain&hourly=precipitation_probability&timezone=America%2FSao_Paulo"
        res = requests.get(url, headers=headers, timeout=5)
        
        if res.status_code == 200:
            data = res.json()
            temp = round(data['current']['temperature_2m'], 1)
            chuva_mm = round(data['current']['precipitation'], 1)
            
            # Obtém a probabilidade de chuva para a hora atual
            hourly_prob = data.get('hourly', {}).get('precipitation_probability', [75])
            prob_chuva = hourly_prob[0] if hourly_prob else 75
            
            # Se houver chuva leve/ativa em mm, garante indicação visual de chuva
            if chuva_mm > 0 and prob_chuva < 50:
                prob_chuva = 75

            print(f"-> [Clima Realtime] Temp: {temp}°C | Prob: {prob_chuva}% | Precipitação: {chuva_mm} mm/h")
            return {
                'temperatura': temp,
                'probabilidade_chuva': prob_chuva,
                'chuva_mm': chuva_mm
            }
    except Exception as e:
        print(f"-> [Clima Realtime ERRO]: {e}")

    # 2. Fallback CPTEC com User-Agent configurado
    try:
        url_estacao = "http://servicos.cptec.inpe.br/XML/estacao/SBSP/condicaoactual.xml"
        res_est = requests.get(url_estacao, headers=headers, timeout=4)
        if res_est.status_code == 200:
            root = ET.fromstring(res_est.content)
            temp_elem = root.find('temperatura')
            temp = float(temp_elem.text) if temp_elem is not None and temp_elem.text else 19.0
            return {
                'temperatura': temp,
                'probabilidade_chuva': 75,
                'chuva_mm': 1.5
            }
    except Exception as e:
        print(f"-> [CPTEC ERRO]: {e}")

    return {'temperatura': 19.0, 'probabilidade_chuva': 75, 'chuva_mm': 1.5}

# ==============================================================================
# FUNÇÃO DE ORIENTAÇÃO DE REGA (IA / CLIMA)
# ==============================================================================
def gerar_orientacao_rega(hortalica, clima):
    """
    Calcula a orientação de rega considerando a umidade atual do solo,
    a faixa ideal de cada planta (min/max) e a precipitação.
    """
    vol_chuva = clima.get('volume_chuva', 0.0) if clima else 0.0
    prob_chuva = clima.get('prob_chuva', 0) if clima else 0
    temp = clima.get('temperatura', 22.0) if clima else 22.0

    # Obtém dados específicos da planta
    u_atual = getattr(hortalica, 'umidade_atual', 0.0) or 0.0
    u_min = getattr(hortalica, 'umidade_min', 40.0) if getattr(hortalica, 'umidade_min', None) is not None else 40.0
    u_max = getattr(hortalica, 'umidade_max', 70.0) if getattr(hortalica, 'umidade_max', None) is not None else 70.0

    u_alvo = (u_min + u_max) / 2.0
    fator_sensibilidade = 50.0 / u_alvo

    # 1. Solo encharcado ou chuva intensa
    if vol_chuva >= 3.0 or u_atual >= u_max:
        percentual_ajuste = -100
        msg_manejo = f"Solo em {u_atual:.1f}% (máx: {u_max:.0f}%). Suspenda 100% a irrigação do lote de {hortalica.nome} hoje."
        status_cor = "#ef4444"
        status_texto = "Irrigação Suspensa (100%)"

    # 2. Solo seco (Abaixo da umidade mínima ideal)
    elif u_atual < u_min:
        abate_chuva = round(vol_chuva * 30.0 * fator_sensibilidade)
        if vol_chuva < 0.5 and abate_chuva < 10:
            percentual_ajuste = 20
            msg_manejo = f"Solo seco ({u_atual:.1f}%) para a faixa do {hortalica.nome} ({u_min:.0f}%-{u_max:.0f}%). A garoa de {vol_chuva} mm/h é insuficiente: aumente a rega em +20%."
            status_cor = "#3b82f6"
            status_texto = "Aumentar Rega (+20%)"
        else:
            reducao = max(5, min(100, abate_chuva))
            percentual_ajuste = -reducao
            msg_manejo = f"Para o {hortalica.nome} (alvo {u_min:.0f}%-{u_max:.0f}%), a chuva de {vol_chuva} mm/h permite abater {reducao}% da rega."
            status_cor = "#f59e0b"
            status_texto = f"Reduzir Rega em {reducao}%"

    # 3. Solo dentro da faixa ideal
    else:
        reducao = min(100, round(vol_chuva * 30.0 * fator_sensibilidade))
        if reducao > 0:
            percentual_ajuste = -reducao
            msg_manejo = f"Com solo em {u_atual:.1f}% e chuva de {vol_chuva} mm/h, reduza a rega do {hortalica.nome} em {reducao}%."
            status_cor = "#f59e0b"
            status_texto = f"Reduzir Rega em {reducao}%"
        elif temp >= 28.0:
            percentual_ajuste = 20
            msg_manejo = f"Temperatura elevada ({temp}°C). Aumente a rega do {hortalica.nome} em +20% devido ao calor."
            status_cor = "#3b82f6"
            status_texto = "Aumentar Rega (+20%)"
        else:
            percentual_ajuste = 0
            msg_manejo = f"Umidade ({u_atual:.1f}%) adequada para {hortalica.nome} ({u_min:.0f}%-{u_max:.0f}%). Mantenha a rega normal."
            status_cor = "#10b981"
            status_texto = "Manter Rega Normal (100%)"

    # Alerta Preventivo de Chuva Iminente
    alerta_preventivo = None
    if prob_chuva >= 70 and vol_chuva < 0.5:
        alerta_preventivo = f"Chuva prevista de {prob_chuva}% nas próximas horas. Cancele ou adie a rega do próximo turno para evitar encharcamento das raízes."
    elif vol_chuva > 2.0:
        alerta_preventivo = "Solo próximo da saturação. Garanta a drenagem do canteiro para evitar mofo ou podridão radicular."

    return {
        'percentual_ajuste': percentual_ajuste,
        'msg_manejo': msg_manejo,
        'alerta_preventivo': alerta_preventivo,
        'status_cor': status_cor,
        'status_texto': status_texto
    }

    # 2. Alerta Preventivo de Chuva Iminente
    alerta_preventivo = None
    if prob_chuva >= 70 and vol_chuva < 0.5:
        alerta_preventivo = f"Chuva prevista de {prob_chuva}% nas próximas horas. Cancele ou adie a rega do próximo turno para evitar encharcamento das raízes."
    elif vol_chuva > 2.0:
        alerta_preventivo = "Solo próximo da saturação pluviométrica. Garanta a drenagem do canteiro para evitar mofo ou podridão radicular."

    return {
        'percentual_ajuste': percentual_ajuste,
        'msg_manejo': msg_manejo,
        'alerta_preventivo': alerta_preventivo,
        'status_cor': status_cor,
        'status_texto': status_texto
    }
def gerar_parecer_agronomico_llm(hortalica, clima):
    """
    Gera parecer agronômico focado apenas na fonte de leitura ativa (Sensor Físico ou Simulador).
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return "Configure a variável GROQ_API_KEY no ambiente para ativar os pareceres em texto natural."

    # Busca a última leitura registrada para este lote (independente de ser sensor ou simulador)
    ultimo_registro = RegistroHidrico.query.filter_by(
        hortalica_id=hortalica.id
    ).order_by(RegistroHidrico.id.desc()).first()

    # Identifica a fonte ativa e o valor de umidade
    if ultimo_registro:
        u_atual = ultimo_registro.nivel_porcentagem or 0.0
        origem_nome = "Sensor Físico (ESP32)" if ultimo_registro.origem == "sensor" else "Simulador Hídrico"
    else:
        u_atual = getattr(hortalica, 'umidade_atual', 0.0) or 0.0
        origem_nome = "Sistema de Monitoramento"

    u_min = getattr(hortalica, 'umidade_min', 40.0) or 40.0
    u_max = getattr(hortalica, 'umidade_max', 70.0) or 70.0
    vol_chuva = clima.get('volume_chuva', 0.0) if clima else 0.0
    prob_chuva = clima.get('prob_chuva', 0) if clima else 0
    temp = clima.get('temperatura', 22.0) if clima else 22.0

    prompt = f"""
    Você é um Engenheiro Agrônomo especialista em agricultura de precisão e irrigação inteligente.
    Analise os dados em tempo real do lote e elabore um parecer técnico curto, direto e prático (máximo 3 frases) com orientações de manejo.

    Dados do Lote ({hortalica.nome}):
    - Fonte de Leitura Ativa: {origem_nome}
    - Umidade Atual do Solo: {u_atual:.1f}%
    - Faixa ideal de umidade para esta espécie: {u_min:.0f}% a {u_max:.0f}%

    Dados Climáticos Locais:
    - Temperatura atual: {temp}°C
    - Precipitação atual: {vol_chuva} mm/h
    - Probabilidade de chuva: {prob_chuva}%

    Regras Importantes:
    - Baseie-se APENAS na umidade atual do solo ({u_atual:.1f}%). Não mencione sensores inativos, ausência de outros sensores ou erros de leitura.
    - Responda em tom profissional, amigável e focado em ação prática de campo.
    """

    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="openai/gpt-oss-120b",
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return f"Não foi possível obter o parecer da Groq em tempo real: {str(e)}"
    
@app.route('/api/parecer/<int:hortalica_id>')
@login_required
def api_parecer(hortalica_id):
    planta = db.session.get(Hortalica, hortalica_id)
    if not planta:
        return jsonify({"error": "Lote não encontrado"}), 404
        
    parecer = gerar_parecer_agronomico_llm(planta, CLIMA_ATUAL)
    return jsonify({
        "nome": planta.nome,
        "parecer": parecer
    })
# ==============================================================================
# THREAD DE ATUALIZAÇÃO CLIMÁTICA EM SEGUNDO PLANO
# ==============================================================================
def atualizar_clima_periodicamente():
    """Atualiza a variável global CLIMA_ATUAL imediatamente e a cada 15 minutos."""
    global CLIMA_ATUAL
    while True:
        dados = obter_dados_clima_cptec()
        CLIMA_ATUAL["temperatura"] = dados["temperatura"]
        CLIMA_ATUAL["prob_chuva"] = dados["probabilidade_chuva"]
        CLIMA_ATUAL["volume_chuva"] = dados["chuva_mm"]
        
        # Atualiza a cada 900 segundos (15 minutos)
        time.sleep(900)

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
    
    # Geramos os dados brutos primeiro
    X_bruto = [
        [i, getattr(r, 'prob_chuva', 0), getattr(r, 'volume_chuva', 0), temperatura_atual] 
        for i, r in enumerate(historico_registros)
    ]
    Y_bruto = [r.nivel_porcentagem for r in historico_registros]
    
    # Criamos um DataFrame do Pandas para alinhar X e Y e remover os nulos de uma só vez
    df = pd.DataFrame(X_bruto, columns=['Tempo', 'ProbChuva', 'VolChuva', 'Temp'])
    df['Y'] = Y_bruto
    df = df.dropna() # Apaga as linhas com NaN
    
    # Se depois de limpar sobrar menos de 5 registos, abortamos a previsão para evitar erros
    if len(df) < 5:
        return relatorio
        
    # Reconstruímos as matrizes X e Y limpas e prontas para o modelo
    X = df[['Tempo', 'ProbChuva', 'VolChuva', 'Temp']].values
    Y = df['Y'].values
    
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
    return render_template('dashboard.html', fazendas=minhas_fazendas, clima=CLIMA_ATUAL)

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
    if not fazenda or fazenda.usuario_id != current_user.id: 
        return "Acesso Negado", 403
    
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
        'insight_h2o': None,
        'parecer_llm': None
    }
    
    if PLANTA_FOCO_ID is None and len(fazenda.hortalicas) > 0:
        PLANTA_FOCO_ID = fazenda.hortalicas[0].id
        
    for h in fazenda.hortalicas:
        h.orientacao_ia = gerar_orientacao_rega(h, CLIMA_ATUAL)

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
                h.atrasada = False
                h.dias_restantes = 0
                
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
                except: 
                    continue
                
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
    
    if reg_simulador:
        stats['media_simulador'] = round(sum(r.nivel_porcentagem for r in reg_simulador) / len(reg_simulador), 1)
    else:
        stats['media_simulador'] = 0

    if reg_sensor:
        stats['media_sensor'] = round(sum(r.nivel_porcentagem for r in reg_sensor) / len(reg_sensor), 1)
    else:
        stats['media_sensor'] = 0

    if todos_recentes:
        stats['media_h2o'] = round(sum(r.nivel_porcentagem for r in todos_recentes) / len(todos_recentes), 1)
        media_val = stats['media_h2o']
    else:
        stats['media_h2o'] = 0
        media_val = 0
        
    nome_foco_str = "Planta Monitorada"
    u_min, u_max = 40.0, 70.0
    parecer_llm = None

    if PLANTA_FOCO_ID:
        p_foco = db.session.get(Hortalica, PLANTA_FOCO_ID)
        if p_foco:
            nome_foco_str = p_foco.nome
            u_min = getattr(p_foco, 'umidade_min', 40.0) or 40.0
            u_max = getattr(p_foco, 'umidade_max', 70.0) or 70.0
            
            # GERA O PARECER DA GROQ PARA A PLANTA EM FOCO
            parecer_llm = gerar_parecer_agronomico_llm(p_foco, CLIMA_ATUAL)

    if media_val < u_min:
        stats['insight_h2o'] = {
            "tipo": "perigo", 
            "msg": f"{nome_foco_str}: Nível baixo ({media_val}%). Abaixo da faixa ideal da IA ({u_min}% - {u_max}%). Aumente a irrigação."
        }
    elif media_val > u_max:
        stats['insight_h2o'] = {
            "tipo": "alerta", 
            "msg": f"{nome_foco_str}: Nível elevado ({media_val}%). Acima da faixa ideal da IA ({u_min}% - {u_max}%). Reduza a irrigação."
        }
    else:
        stats['insight_h2o'] = {
            "tipo": "sucesso", 
            "msg": f"{nome_foco_str}: Nível hídrico ideal ({media_val}%). Dentro da faixa recomendada pela IA ({u_min}% a {u_max}%)."
        }
                
    stats['total_ativas'] = qtd_ativas
    stats['tempo_medio'] = round(total_ciclos / qtd_ativas, 1) if qtd_ativas > 0 else 0
    stats['previsoes'] = previsoes_ia
    stats['parecer_llm'] = parecer_llm
    
    if filtro == 'Crescendo': 
        hortalicas_exibidas = [h for h in fazenda.hortalicas if h.status != 'Colhido']
    elif filtro == 'Colhido': 
        hortalicas_exibidas = [h for h in fazenda.hortalicas if h.status == 'Colhido']
    else: 
        hortalicas_exibidas = fazenda.hortalicas
    
    return render_template(
        'index.html', 
        fazenda=fazenda, 
        hortalicas=hortalicas_exibidas, 
        stats=stats, 
        chart_data=contagem_variedades, 
        labels_simulador=labels_simulador, 
        dados_simulador=dados_simulador,
        labels_sensor=labels_sensor, 
        dados_sensor=dados_sensor, 
        hoje=hoje,
        planta_foco_id=PLANTA_FOCO_ID, 
        clima=CLIMA_ATUAL
    )
# --- OPERAÇÕES DE CRUD E API ---
@app.route('/add_hortalica/<int:fazenda_id>', methods=['POST'])
@login_required
def add_hortalica(fazenda_id):
    nome = request.form.get('nome')
    data_plantio_str = request.form.get('data_plantio')
    ciclo_estimado_str = request.form.get('ciclo_estimado')

    # 1. Consulta a API da Groq para obter os limites de umidade
    umidade_min, umidade_max = obter_limites_umidade_ia(nome)

    # 2. Converte a data do formulário
    if data_plantio_str:
        data_plantio = datetime.strptime(data_plantio_str, '%Y-%m-%d').date()
    else:
        data_plantio = datetime.utcnow().date()

    ciclo_val = int(ciclo_estimado_str) if ciclo_estimado_str else 30

    # 3. Salva a nova hortaliça vinculada à fazenda
    nova_hortalica = Hortalica(
        nome=nome,
        data_plantio=data_plantio,
        ciclo_estimado=ciclo_val,
        umidade_min=umidade_min,
        umidade_max=umidade_max,
        fazenda_id=fazenda_id
    )

    db.session.add(nova_hortalica)
    db.session.commit()

    flash(f"Lote de '{nome}' cadastrado com sucesso! Umidade ideal definida via IA: {umidade_min}% a {umidade_max}%.", "success")

    # 4. Redireciona de volta para o dashboard da própria fazenda ativa
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/editar_hortalica/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_hortalica(id):
    h = db.session.get(Hortalica, id)
    if not h or h.fazenda.usuario_id != current_user.id:
        return "Acesso Negado", 403
        
    if request.method == 'POST':
        novo_nome = request.form.get('nome')
        
        # Se o nome da planta mudou, reconsulta a IA para recalcular as taxas de humidade
        if novo_nome and novo_nome != h.nome:
            h.umidade_min, h.umidade_max = obter_limites_umidade_ia(novo_nome)
            h.nome = novo_nome

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
    fazenda = db.session.get(Fazenda, fazenda_id)
    if not fazenda:
        return jsonify({
            "labels_sensor": [],
            "dados_sensor": [],
            "labels_simulador": [],
            "dados_simulador": [],
            "umidades_plantas": {},
            "inteligencia_artificial_simulador": {"diagnostico_ia": "Fazenda não encontrada", "acao_recomendada": "-"},
            "inteligencia_artificial_sensor": {"diagnostico_ia": "Fazenda não encontrada", "acao_recomendada": "-"},
            "clima": CLIMA_ATUAL
        }), 404
        
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
    umidades_plantas = {}
    for h in fazenda.hortalicas:
        umidades_plantas[h.id] = {
            'atual': h.umidade_atual or 0.0,
            'min': getattr(h, 'umidade_min', 40.0) or 40.0,
            'max': getattr(h, 'umidade_max', 70.0) or 70.0
        }
        
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
        "clima": CLIMA_ATUAL  # Garante o envio dos dados de clima
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