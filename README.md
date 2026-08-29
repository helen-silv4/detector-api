## 🛩️ **Drone Waste Monitoring - API**

API responsável por intermediar a comunicação entre o frontend (Angular) e o drone DJI Tello, expondo endpoints REST para controle e testes.

Este repositório faz parte do TCC "Drone Waste Monitoring", junto com:
- [detector_de_lixo](https://github.com/Jhonydev72/detector_de_lixo):  scripts de controle de voo, visão computacional e YOLOv8
- [detector-mfe](https://github.com/helen-silv4/detector-mfe):  frontend em Angular

### **Status atual**

🚧 Em desenvolvimento. Os endpoints de teste estão **simulados (mock)**, pois ainda não há integração direta com o drone físico nesta API.

### **Requisitos**

- Python 3.10+

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

### **Endpoints disponíveis**

| Método | Rota | Descrição |
|---|---|---|
| GET | `/health` | Verifica se a API está no ar |
| POST | `/testes/voo` | Simula uma rotina de teste de voo |
| POST | `/testes/video` | Simula uma rotina de teste de vídeo |
| POST | `/testes/voo-video` | Simula uma rotina de teste de voo + vídeo simultâneos |

### **Próximos passos**

- Integrar os endpoints de teste com o drone real (via `djitellopy`)
- Endpoints de detecção (Mapeamento 2D / Detecção de Lixo)