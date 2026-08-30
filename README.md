## 🛩️ **Drone Waste Monitoring - API**

API responsável por intermediar a comunicação entre o frontend (Angular) e o drone DJI Tello, expondo endpoints REST para controle e testes.

Este repositório faz parte do TCC Drone Waste Monitoring, junto com:
- [detector_de_lixo](https://github.com/Jhonydev72/detector_de_lixo): scripts de controle de voo, visão computacional e YOLOv8
- [detector-mfe](https://github.com/helen-silv4/detector-mfe): frontend em Angular
### **Status atual**

🚧 Em desenvolvimento. Os endpoints de teste suportam dois modos de execução (Modo mock vs. real).

### **Requisitos**

- Python 3.10+
- DJI Tello (apenas para o modo real)

### **Configuração**

Clone o repositório e entre na pasta:

```bash
git clone https://github.com/helen-silv4/detector-api.git
cd detector-api
```

Crie o ambiente virtual:

```bash
python -m venv .venv
```

Ative o ambiente virtual (Git Bash):

```bash
source .venv/Scripts/activate
```

Instale as dependências:

```bash
python -m pip install -r requirements.txt
```

### **Execução**

```bash
uvicorn main:app --reload --port 8000
```

A API estará disponível em `http://localhost:8000`.

Documentação automática (Swagger) em `http://localhost:8000/docs`.

### **Modo mock vs. real**

Os endpoints de teste (`/testes/voo`, `/testes/video`, `/testes/voo-video`) funcionam em dois modos, controlados pela variável de ambiente `DRONE_MODE`:

- **`mock`** (padrão): devolve logs simulados, sem tocar em nenhum drone. Útil para desenvolver e testar o frontend sem ter o drone em mãos.
- **`real`**: conecta de fato ao Tello via `djitellopy` e executa as rotinas (conectar, decolar, ativar stream, pousar).

Para rodar em modo real:

```bash
DRONE_MODE=real uvicorn main:app --reload --port 8000
```

⚠️ **Antes de rodar em modo real:**
1. Conecte o computador à rede Wi-Fi do DJI Tello (isso desconecta o PC da internet, a não ser que haja outra interface de rede disponível, ex: cabo Ethernet).
2. Certifique-se de que a bateria do drone está acima de 20% (os testes abortam a decolagem automaticamente abaixo disso).
3. Execute os testes em uma área aberta e segura.

### **Endpoints disponíveis**

| Método | Rota | Descrição |
|---|---|---|
| GET | `/health` | Verifica se a API está no ar e em qual modo (`drone_mode`) |
| POST | `/testes/voo` | Executa rotina de teste de voo (conecta, decola, pousa) |
| POST | `/testes/video` | Executa rotina de teste de vídeo (conecta, ativa stream, valida frame) |
| POST | `/testes/voo-video` | Executa rotina combinada de voo + vídeo simultâneos |

### **Próximos passos**

- Endpoints de detecção (Mapeamento 2D / Detecção de Lixo)