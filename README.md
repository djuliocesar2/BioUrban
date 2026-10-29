# 🌿 BioUrban — Sistema Inteligente de Monitoramento Hídrico

O **BioUrban** é uma plataforma de gestão e monitoramento hídrico desenvolvida para fazendas urbanas e unidades de cultivo inteligente.

O sistema permite acompanhar o desenvolvimento das plantas, registrar lotes de cultivo e monitorar a umidade do solo por meio de sensores físicos ou dados simulados.

O projeto integra **Python, Flask, SQLite, ESP32 e sensores IoT**, disponibilizando informações em um dashboard web para auxiliar no acompanhamento das condições de cultivo e na tomada de decisões relacionadas à irrigação.

---

## 🚀 Funcionalidades

- 📊 Dashboard para acompanhamento das plantações;
- 🌱 Cadastro e gerenciamento de plantas e lotes;
- 💧 Monitoramento da umidade do solo;
- 📡 Integração com ESP32 e sensor capacitivo;
- 🔌 Comunicação entre ESP32 e computador via USB/Serial;
- 🧪 Simulador IoT para testes sem o hardware físico;
- 📈 Gráficos de monitoramento;
- 🎯 Seleção de uma planta para monitoramento individual;
- 🔄 Controle de ativação e desativação do sensor físico;
- 📋 Recomendações relacionadas à necessidade hídrica das plantas;
- 🔐 Sistema de autenticação de usuários;
- 📄 Exportação de dados para análise.

> A disponibilidade de cada funcionalidade depende da configuração do ambiente e da implementação presente na versão do código utilizada.

---

## 🧠 Arquitetura do sistema

### Sensor físico

```text
Sensor capacitivo de umidade
          ↓
         ESP32
          ↓
     USB / Serial
          ↓
        Python
          ↓
        Flask
          ↓
        SQLite
          ↓
      Dashboard
```

### Simulador IoT

```text
    Simulador IoT
          ↓
     Aplicação Flask
          ↓
        SQLite
          ↓
      Dashboard
```

O simulador permite testar o sistema sem a necessidade de manter o ESP32 conectado. O sensor físico e o simulador devem ser utilizados de acordo com os controles e as configurações disponíveis na aplicação.

### Tecnologias e responsabilidades

| Componente | Responsabilidade |
|---|---|
| ESP32 | Realizar a leitura do sensor físico |
| Sensor capacitivo | Medir a resposta elétrica associada à umidade do solo |
| Python | Processar dados e executar a lógica da aplicação |
| Flask | Disponibilizar as rotas e funcionalidades web |
| SQLite | Armazenar os registros da aplicação |
| Dashboard | Apresentar dados e informações ao usuário |
| Simulador IoT | Gerar dados para testes sem hardware |

---

## 📡 Integração com o ESP32

O BioUrban possui integração física com um **ESP32 ESP-WROOM-32**, conectado ao computador por meio de um cabo USB.

O ESP32 recebe as leituras de um sensor capacitivo de umidade do solo e transmite os dados ao computador pela comunicação serial.

### Componentes utilizados

- ESP32 ESP-WROOM-32;
- Sensor capacitivo de umidade do solo;
- Display OLED de 0,96 polegada com interface I²C;
- Protoboard;
- Cabos jumper;
- Cabo USB.

### Comunicação atual

```text
ESP32 → USB → Porta Serial → Python → Flask
```

A biblioteca PySerial pode ser utilizada pela aplicação Python para acessar a porta serial e receber os dados enviados pelo microcontrolador.

### Configuração serial

| Parâmetro | Configuração documentada |
|---|---|
| Porta serial | COM3, como exemplo no Windows |
| Baud rate | 9600 |
| Comunicação física | USB/Serial |

**Importante:** a porta COM varia conforme o computador e a conexão USB. Para identificar a porta correta no Windows, abra o Gerenciador de Dispositivos e consulte a seção **Portas (COM e LPT)**.

A velocidade serial configurada no Python deve ser igual à utilizada no firmware do ESP32.

### Formato dos dados

Se o firmware transmitir dados em JSON, a mensagem deverá seguir o formato esperado pelo código Python. Os nomes dos campos e o conteúdo exato devem corresponder ao firmware instalado no ESP32 e ao processamento implementado na aplicação.

### Comunicação Wi-Fi

A comunicação documentada nesta versão utiliza USB/Serial. A comunicação direta entre ESP32 e aplicação Flask por Wi-Fi exige uma implementação específica de rede, incluindo o endereço do servidor, o protocolo de comunicação e o tratamento das mensagens recebidas.

Essa funcionalidade deve ser considerada concluída somente após a implementação e a realização dos testes de integração.

---

## 🌱 Calibração do sensor

O sensor capacitivo foi calibrado experimentalmente utilizando diferentes condições de umidade do solo.

| Condição observada | Leitura aproximada |
|---|---:|
| Terra seca | 3115 |
| Terra úmida | 2415 |
| Terra muito úmida | 1144 |

Os valores representam leituras experimentais obtidas durante a calibração do projeto. Eles podem variar de acordo com o sensor, a alimentação elétrica, a composição do solo e as condições do experimento.

A partir das leituras, o firmware pode converter os valores analógicos em uma escala percentual de umidade de 0% a 100%.

### Classificação utilizada

| Percentual de umidade | Classificação |
|---|---|
| Menor que 30% | SECO |
| De 30% a 69% | ADEQUADO |
| Igual ou superior a 70% | MUITO ÚMIDO |

> A porcentagem representa uma escala experimental de calibração utilizada no projeto. Ela não deve ser interpretada como uma medida universal de umidade volumétrica do solo. Os limites de classificação devem ser ajustados de acordo com a calibração e as necessidades de cada cultivo.

---

## 🖥️ Tecnologias utilizadas

### Backend

- Python 3;
- Flask;
- Flask-SQLAlchemy;
- Flask-Login;
- Flask-Migrate;
- SQLite;
- NumPy;
- SciPy;
- Scikit-learn;
- Requests;
- PySerial;
- Python-dotenv.

### Frontend

- HTML5;
- CSS3;
- JavaScript;
- Jinja2;
- Chart.js;
- Font Awesome.

### Hardware

- ESP32 ESP-WROOM-32;
- Sensor capacitivo de umidade do solo;
- Display OLED SSD1306;
- Protoboard e cabos de conexão.

> A lista representa as tecnologias identificadas na documentação e nos trechos de código compartilhados. A relação definitiva de dependências deve ser conferida no código e consolidada em um arquivo `requirements.txt`.

---

## 🔧 Instalação e execução

### 1. Pré-requisitos

Antes de começar, tenha instalado:

- Python compatível com as dependências do projeto;
- Git;
- Visual Studio Code ou outro editor de código;
- Arduino IDE, caso utilize o ESP32 físico;
- Driver USB adequado à placa, se necessário.

### 2. Clonar o repositório

```bash
git clone https://github.com/henriquebmr/BioUrban.git
```

Entre na pasta do projeto:

```bash
cd BioUrban
```

### 3. Criar o ambiente virtual

No Windows:

```bash
python -m venv venv
```

Ative o ambiente:

```powershell
.\venv\Scripts\Activate.ps1
```

Caso utilize o Prompt de Comando (CMD):

```bat
venv\Scripts\activate.bat
```

No Linux/macOS:

```bash
source venv/bin/activate
```

Após a ativação, o terminal deverá indicar o ambiente virtual ativo, normalmente com `(venv)`.

### 4. Instalar as dependências

Se o repositório possuir um arquivo `requirements.txt`, utilize:

```bash
python -m pip install -r requirements.txt
```

Caso esse arquivo ainda não exista, instale as dependências identificadas pelo projeto:

```bash
python -m pip install Flask Flask-SQLAlchemy Flask-Login Flask-Migrate python-dotenv requests numpy scipy scikit-learn pyserial
```

A lista definitiva deve ser validada com os imports de todos os arquivos Python. Recomenda-se manter as dependências registradas no `requirements.txt` para facilitar a reprodução do ambiente.

### 5. Configurar as variáveis de ambiente

Crie um arquivo chamado `.env` na raiz do projeto, no mesmo nível de `app.py`.

Exemplo:

```dotenv
OPENWEATHER_API_KEY=sua_chave_da_api
```

Substitua o valor de exemplo por uma chave válida, caso o projeto utilize a API OpenWeather.

O código pode carregar as variáveis com:

```python
from dotenv import load_dotenv

load_dotenv()
```

**Segurança:**

- Não publique chaves de API ou senhas no repositório;
- Não compartilhe capturas de tela que revelem credenciais;
- Inclua `.env` no `.gitignore`;
- Utilize valores de exemplo no README, nunca credenciais reais.

Exemplo de entrada no `.gitignore`:

```gitignore
.env
venv/
__pycache__/
*.py[cod]
```

O arquivo de banco de dados e outros arquivos locais também devem ser tratados conforme a política de versionamento do projeto.

### 6. Banco de dados

O projeto utiliza SQLite para armazenar os registros da aplicação.

A configuração observada no código é:

```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///biourban_pro.db'
```

No Flask-SQLAlchemy, esse caminho relativo costuma ser resolvido em relação à pasta `instance` da aplicação Flask.

Antes de executar o sistema pela primeira vez, verifique se o código inicializa as tabelas e se o banco de dados é criado automaticamente.

Se o projeto utilizar Flask-Migrate para gerenciar o esquema, as migrações deverão ser executadas conforme o estado dos arquivos existentes em `migrations/`. Não execute comandos de migração indiscriminadamente em um banco com dados importantes.

### 7. Executar o sistema

Com o ambiente virtual ativo e as configurações necessárias concluídas, execute:

```bash
python app.py
```

Consulte a mensagem exibida no terminal para identificar o endereço e a porta em que o servidor foi iniciado.

Se a aplicação estiver configurada para utilizar a porta 8080, acesse:

```text
http://127.0.0.1:8080
```

Se outra porta aparecer no terminal, utilize o endereço correspondente.

Mantenha o terminal aberto enquanto estiver utilizando o sistema.

---

## 🧪 Simulador IoT

O BioUrban possui um simulador para permitir testes sem a