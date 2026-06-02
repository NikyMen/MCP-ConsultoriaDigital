# MCP Consultoría Digital

Servidor MCP (Model Context Protocol) en Python que expone herramientas para el
**asistente comercial de Consultoría Digital**. Pensado para usarse desde
**n8n** (orquestador) + **GPT** (modelo) + **WaSender** (canal WhatsApp), con
deploy en VPS de Hostinger.

El MCP no responde mensajes por sí solo: ofrece a GPT las herramientas para
calificar leads, validar CUIT, registrar estados y generar PDFs de presupuesto
según el flujo comercial definido.

## Flujo

```
WhatsApp → WaSender → n8n → GPT (con MCP Client) → MCP Server (este repo)
                                                       │
                                                       ├─ productos / FAQs
                                                       ├─ validar_cuit
                                                       ├─ registrar_lead / clasificar_lead
                                                       ├─ generar_presupuesto (PDF)
                                                       └─ prompt_sistema
```

## Clasificación de leads (la que pide el negocio)

| Etapa                    | Cuándo                                                  |
| ------------------------ | ------------------------------------------------------- |
| `INICIAL`                | Llega un mensaje, todavía no identificamos producto.    |
| `PRODUCTO_IDENTIFICADO`  | Sabemos qué producto le interesa, le respondimos FAQs.  |
| `MEDIA`                  | Entregó CUIT válido + nombre de empresa.                |
| `ALTA`                   | Recibió el PDF de presupuesto y se le propuso reunión.  |
| `DESCARTADO`             | No cumple criterios (sin CUIT, fuera de alcance, etc.). |

## Productos

Definidos en [`data/productos.yaml`](data/productos.yaml) (editable sin tocar
código). Incluye descripción, FAQs y precios placeholder a completar:

- `gestion_redes` — Gestión de Redes Sociales
- `pauta_meta` — Pauta Publicitaria en Meta
- `crm` — Automatización con CRM
- `concilia` — Conciliación bancaria con IA
- `turneria` — Software de turnos para salud

## Herramientas MCP expuestas

| Tool                            | Para qué sirve                                        |
| ------------------------------- | ----------------------------------------------------- |
| `productos_disponibles`         | Listar todos los productos.                           |
| `info_producto`                 | Descripción detallada + qué incluye + precio desde.   |
| `faqs_producto`                 | FAQs y respuestas oficiales del producto.             |
| `identificar_producto_interes`  | Inferir producto desde el mensaje del lead.           |
| `validar_cuit`                  | Algoritmo AFIP de validación de CUIT.                 |
| `registrar_lead`                | Crear/actualizar lead (upsert por teléfono).          |
| `clasificar_lead`               | Cambiar la etapa (INICIAL/MEDIA/ALTA/DESCARTADO).     |
| `buscar_lead`                   | Recuperar estado del lead al inicio de cada turno.    |
| `listar_leads`                  | Listado para uso interno.                             |
| `generar_presupuesto`           | Genera PDF, lo guarda y marca el lead como ALTA.      |
| `prompt_sistema`                | Devuelve el system prompt sugerido para GPT en n8n.   |
| `recargar_catalogo`             | Recargar `productos.yaml` sin reiniciar el server.    |

### Kommo CRM

| Tool                            | Para qué sirve                                        |
| ------------------------------- | ----------------------------------------------------- |
| `kommo_listar_pipelines`        | Pipelines + statuses (para descubrir IDs).            |
| `kommo_listar_usuarios`         | Usuarios de Kommo (IDs para asignar responsables).    |
| `kommo_buscar_lead`             | Buscar leads por nombre/teléfono/email.               |
| `kommo_obtener_lead`            | Traer un lead por ID con sus contactos.               |
| `kommo_crear_lead`              | Crear lead con contacto + empresa en una sola llamada.|
| `kommo_actualizar_lead`         | Editar nombre / pipeline / status / responsable / precio. |
| `kommo_mover_lead`              | Mover de estado (acepta `clasificacion` MEDIA/ALTA/…).|
| `kommo_asignar_responsable`     | Cambiar el usuario responsable.                       |
| `kommo_agregar_nota`            | Dejar una nota en el historial del lead.              |
| `kommo_crear_tarea`             | Crear tarea (recordatorio) para el responsable.       |

## Panel de administración web

Además del MCP, el mismo servidor expone un **panel web** en `/admin` para
gestionar el negocio sin tocar la base ni la API:

- **Dashboard**: total de leads y conteo por etapa del pipeline.
- **Leads**: tabla con filtro por clasificación, alta manual, edición de todos
  los campos, cambio de etapa, historial de eventos y presupuestos por lead,
  y baja.

Auth propia por **contraseña** (cookie de sesión firmada), independiente del
bearer token del MCP. Configurar en `.env`:

```
ADMIN_PASSWORD=una-clave-fuerte
ADMIN_SESSION_SECRET=          # opcional, openssl rand -hex 32
```

En local queda en `http://localhost:8765/admin`. En el VPS se sirve por el
mismo Nginx (ver el `location /admin` en `deploy/nginx.conf.example`):
`https://tu-dominio.com/admin`.

> El panel está pensado para **escalar**: sumar un módulo nuevo (catálogo,
> config, system prompt, tester de tools) es agregar una entrada a `NAV` y su
> `Route` en `src/admin.py`.

## Estructura

```
.
├── server.py                # FastMCP server + bearer auth + panel /admin
├── src/
│   ├── admin.py             # Panel web de administración (/admin)
│   ├── catalogo.py          # Carga del YAML
│   ├── config.py            # .env
│   ├── cuit.py              # Validación CUIT
│   ├── db.py                # SQLite
│   ├── leads.py             # CRUD de leads
│   ├── pdf.py               # Generador de PDF
│   └── prompts.py           # System prompt para n8n/GPT
├── data/
│   ├── productos.yaml       # ⇐ EDITAR precios y FAQs acá
│   ├── leads.db             # (auto, ignorado por git)
│   └── presupuestos/        # PDFs generados
├── deploy/
│   ├── consultoria-mcp.service
│   ├── nginx.conf.example
│   └── deploy.sh
└── n8n/
    └── workflow-ejemplo.md
```

## Desarrollo local

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; en Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # ajustar valores
python server.py
```

El server queda en `http://localhost:8765/mcp/`. Probalo con cualquier cliente
MCP (Claude Desktop con config HTTP, n8n MCP Client node, etc.).

## Deploy en VPS Hostinger (paso a paso)

### 1. Crear repo en GitHub y subir el código

```bash
cd D:\dev\MCP-ConsultoriaDigital
git init
git add .
git commit -m "Initial commit: MCP Consultoria Digital"
git branch -M main
git remote add origin git@github.com:TU_USUARIO/mcp-consultoria-digital.git
git push -u origin main
```

### 2. En el VPS (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git nginx
sudo mkdir -p /opt/mcp-consultoria && sudo chown $USER:$USER /opt/mcp-consultoria
git clone git@github.com:TU_USUARIO/mcp-consultoria-digital.git /opt/mcp-consultoria
cd /opt/mcp-consultoria

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cp .env.example .env
# Editar .env con valores reales. Generar token largo:
#   openssl rand -hex 32
nano .env
```

### 3. Instalar service de systemd

```bash
sudo cp deploy/consultoria-mcp.service /etc/systemd/system/consultoria-mcp.service
# Editar si hace falta (User, paths)
sudo nano /etc/systemd/system/consultoria-mcp.service

sudo systemctl daemon-reload
sudo systemctl enable consultoria-mcp
sudo systemctl start consultoria-mcp
sudo systemctl status consultoria-mcp
```

### 4. Reverse proxy con Nginx + TLS

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/consultoria-mcp
sudo nano /etc/nginx/sites-available/consultoria-mcp   # ajustar dominio
sudo ln -s /etc/nginx/sites-available/consultoria-mcp /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Certificado TLS gratis:
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu-dominio.com
```

### 5. Conectar desde n8n

En n8n, agregar un nodo **MCP Client**:

- **URL**: `https://tu-dominio.com/mcp/`
- **Auth**: Header Auth → `Authorization: Bearer <MCP_AUTH_TOKEN>`
- **Tools**: cargar todas las del server.

Ver [`n8n/workflow-ejemplo.md`](n8n/workflow-ejemplo.md) para el detalle del
workflow completo (WaSender → AI Agent → MCP → respuesta).

### 6. Updates posteriores (un comando)

```bash
cd /opt/mcp-consultoria
bash deploy/deploy.sh
```

Hace `git pull`, reinstala deps y reinicia el service.

### 7. (Opcional) Deploy automático con GitHub Actions

Agregar un workflow `.github/workflows/deploy.yml` que se dispare en push a
`main` y haga SSH al VPS ejecutando `deploy/deploy.sh`. Configurar secrets
`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`.

## Pendientes que tenés que completar

1. **Completar precios reales** en [`data/productos.yaml`](data/productos.yaml)
   (los `precio_desde: 0` son placeholders).
2. **Configurar `.env`** con datos reales de la empresa (CUIT, web, etc.) y
   generar un `MCP_AUTH_TOKEN` largo.
3. **Comprar dominio o subdominio** apuntando al VPS Hostinger.
4. **Workflow en n8n**: armar siguiendo `n8n/workflow-ejemplo.md`. Necesitás
   credenciales de WaSender y OpenAI configuradas en n8n.
5. **Branding del PDF** (opcional): agregar logo y colores propios editando
   [`src/pdf.py`](src/pdf.py).
6. **Configurar Kommo**:
   - En Kommo: Configuración → Integraciones → Crear integración (privada)
     → copiar el Access Token (long-lived).
   - Cargar en `.env`: `KOMMO_SUBDOMAIN`, `KOMMO_ACCESS_TOKEN`.
   - Llamar una vez `kommo_listar_pipelines` y `kommo_listar_usuarios`
     desde n8n para descubrir los IDs.
   - Cargar en `.env` los IDs de los statuses del pipeline que mapean a tus
     clasificaciones internas: `KOMMO_PIPELINE_ID`, `KOMMO_STATUS_INICIAL_ID`,
     `KOMMO_STATUS_MEDIA_ID`, `KOMMO_STATUS_ALTA_ID`, `KOMMO_STATUS_DESCARTADO_ID`,
     `KOMMO_RESPONSABLE_DEFAULT_ID`. Con eso, el agente puede mover leads
     usando `clasificacion="MEDIA"` y resuelve el `status_id` solo.
#   M C P - C o n s u l t o r i a D i g i t a l  
 