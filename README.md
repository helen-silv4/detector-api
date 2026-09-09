## 🛩️ **Drone Waste Monitoring - API (Edge Computing & AI)**

API assíncrona responsável por intermediar a comunicação entre o frontend (Angular) e o drone DJI Tello, executando inferência de Visão Computacional (YOLOv8) na Edge e transmitindo vídeo via streaming MJPEG.

Este repositório faz parte do TCC Drone Waste Monitoring, junto com:

- [detector_de_lixo](https://github.com/Jhonydev72/detector_de_lixo): scripts de treinamento do YOLO e datasets.
- [detector-mfe](https://github.com/helen-silv4/detector-mfe): interface de operação e telemetria em Angular.

### **Status atual**

🚀 **Operacional (Integração IA Concluída).** A API gerencia o ciclo de vida do drone usando o padrão Singleton, evitando conflitos de portas UDP, e executa inferência YOLOv8 acelerada por GPU (CUDA).

### **Arquitetura e Features**

*   **Streaming MJPEG:** Conversão de frames OpenCV para um fluxo contínuo compatível nativamente com tags `<img>` no HTML, sem necessidade de plugins extras no frontend.
*   **Frame Skipping Dinâmico:** Para garantir fluidez de vídeo (30 FPS), a IA processa quadros em intervalos (ex: a cada 3 frames), mantendo a bounding box na tela e eliminando o "Video Delay".
*   **Odometria Inercial (Dead Reckoning):** Cálculo de coordenadas geográficas (Mock GPS) em tempo real integrando a velocidade inercial (`get_speed_x/y`) e tempo (`delta_t`).
*   **Aceleração de Hardware:** Suporte a NVIDIA CUDA / Tensor Cores via PyTorch (`device=0`).

---

### **Requisitos**

- Python 3.10+
- DJI Tello
- **Opcional (Recomendado):** Placa de vídeo NVIDIA (RTX 2050+) com Drivers CUDA 12.1+ para fluidez de inferência.

### **Configuração e Instalação**

Clone o repositório e entre na pasta:

```bash
git clone https://github.com/helen-silv4/detector-api.git
cd detector-api

```

Crie e ative o ambiente virtual:

```bash
python -m venv .venv
source .venv/Scripts/activate  # Git Bash / Linux
# ou .\venv\Scripts\activate   # Windows PowerShell

```

Instale as dependências. Para habilitar a GPU, instale a versão do PyTorch com suporte ao CUDA **antes** do `requirements.txt`:

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt

```


---

### **Execução**

```bash
python -m uvicorn main:app --reload --port 8000

```

* A API estará disponível em `http://localhost:8000`.
* Documentação automática (Swagger) em `http://localhost:8000/docs`.

---

### **Endpoints de Operação**

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/health` | Verifica se a API está no ar e em qual modo (`drone_mode`) |
| GET | `/deteccao/stream` | Retorna o stream MJPEG com bounding boxes da IA e HUD de telemetria |
| POST | `/testes/voo-video` | Aciona a rotina de decolagem (`takeoff`) da missão |
| POST | `/controle` | Recebe um JSON `{lr, fb, ud, yv}` para pilotagem RC ao vivo via teclado |
| POST | `/emergencia` | Interrompe a missão atual e força o pouso imediato (`land`) |

### **Modo mock vs. real**

Variável de ambiente `DRONE_MODE` para testes locais de interface sem o equipamento:

* **`mock`** (padrão): devolve logs simulados, sem tocar em nenhum drone. Útil para testar os botões do frontend.
* **`real`**: conecta de fato ao Tello físico.

⚠️ **Checklist de Voo (Modo Real):**

1. Conecte o PC ao Wi-Fi nativo do DJI Tello.
2. Certifique-se de que a bateria está acima de 20%.
3. O servidor Uvicorn deve ter acesso exclusivo ao drone (não abra scripts paralelos usando a biblioteca DJITelloPy simultaneamente).

### **Próximos passos**

* Integração com banco de dados PostgreSQL/PostGIS para salvamento persistente das coordenadas de infrações detectadas pela IA.